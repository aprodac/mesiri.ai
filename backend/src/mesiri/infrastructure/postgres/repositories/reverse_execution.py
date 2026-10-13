"""PostgreSQL implementation of mesiri.application.finance.reverse_repository.ReverseExecutionRepository.

Only file permitted to hold SQL for ReverseTransaction execution
(capability-boundary convention, mirrors account_admin_execution.py).
Every method takes an externally-supplied connection.

`persist_success` for `target_kind='expense'` composes
`PostgresExpensePaymentRepository.reverse_payment` (same connection, same
transaction) for whichever payment is still `confirmed` -- an expense may
have no confirmed payment at all (unpaid, or paid from own pocket, see
Finance Module Slice 0), in which case there is nothing to reverse in the
ledger and only the expense itself gets voided. `target_kind='transfer'`
composes `PostgresMoneyTransactionRepository.reverse` directly on the given
transaction id -- same reasoning as expense_execution.py's use of
PostgresExpensePaymentRepository, duplicating this SQL here would be worse
than the minor capability-boundary bend of calling out to another repository.
`target_kind='activity'` composes
`PostgresProgressReadRepository.void_activity` (ADR-D15) the same way --
Daily Reporting owns its own soft-delete + activity_corrections audit
write, this file only calls it.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from mesiri.application.finance.reverse_commands import ReverseTransactionCommand
from mesiri.application.finance.reverse_repository import ReverseExecutionRepository
from mesiri.infrastructure.postgres.repositories.expenses import PostgresExpensePaymentRepository
from mesiri.infrastructure.postgres.repositories.finance import PostgresMoneyTransactionRepository
from mesiri.infrastructure.postgres.workflow_instance import (
    get_by_id_on_connection,
    transition_on_connection,
)
from mesiri_contracts.application.results.execution_result import (
    ExecutionResult,
    ExecutionStatus,
    as_replay,
)
from mesiri_contracts.context.enums import WorkflowPhase

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

_COMMAND_TYPE = "reverse_transaction"


class PostgresReverseExecutionRepository(ReverseExecutionRepository):
    async def check_idempotency(self, conn: AsyncConnection, key: str) -> ExecutionResult | None:
        row = (
            await conn.execute(
                sa.text("SELECT status, result FROM idempotency_keys WHERE key = :key"),
                {"key": key},
            )
        ).mappings().first()
        if row is None or row["status"] != "completed" or row["result"] is None:
            return None
        result_json = row["result"]
        if not isinstance(result_json, str):
            result_json = json.dumps(result_json)
        return ExecutionResult.model_validate_json(result_json)

    async def _try_claim(self, conn: AsyncConnection, cmd: ReverseTransactionCommand) -> bool:
        """INSERT ... ON CONFLICT DO NOTHING — True if this call won the claim."""
        claimed = (
            await conn.execute(
                sa.text(
                    "INSERT INTO idempotency_keys (key, command_type, status) "
                    "VALUES (:key, :command_type, 'in_progress') "
                    "ON CONFLICT (key) DO NOTHING RETURNING key"
                ),
                {"key": cmd.idempotency_key, "command_type": _COMMAND_TYPE},
            )
        ).first()
        return claimed is not None

    async def persist_success(
        self, conn: AsyncConnection, cmd: ReverseTransactionCommand
    ) -> ExecutionResult:
        if not await self._try_claim(conn, cmd):
            existing = await self.check_idempotency(conn, cmd.idempotency_key)
            assert existing is not None
            return as_replay(existing)

        organization_id = uuid.UUID(cmd.organization_id)
        created_by = uuid.UUID(cmd.created_by)

        if cmd.target_kind == "expense":
            assert cmd.expense_id is not None
            expense_id = uuid.UUID(cmd.expense_id)
            payments = PostgresExpensePaymentRepository(conn)
            confirmed_payment = next(
                (
                    p
                    for p in await payments.list_for_expense(organization_id, expense_id)
                    if p.status == "confirmed"
                ),
                None,
            )
            if confirmed_payment is not None:
                await payments.reverse_payment(organization_id, confirmed_payment.id, created_by)
            await conn.execute(
                sa.text(
                    "UPDATE expenses SET workflow_status = 'voided', updated_by = :updated_by, "
                    "updated_at = now() WHERE id = :id AND organization_id = :organization_id"
                ),
                {"updated_by": created_by, "id": expense_id, "organization_id": organization_id},
            )
            row_id = expense_id
            await conn.execute(
                sa.text(
                    "INSERT INTO outbox_events "
                    "(id, aggregate_type, aggregate_id, event_type, payload, correlation_id) "
                    "VALUES (:id, 'expense', :aggregate_id, 'ExpenseVoided', '{}'::jsonb, :correlation_id)"
                ),
                {"id": uuid.uuid4(), "aggregate_id": expense_id, "correlation_id": cmd.correlation_id},
            )
        elif cmd.target_kind == "activity":
            assert cmd.activity_id is not None
            from mesiri.infrastructure.postgres.repositories.progress import (
                PostgresProgressReadRepository,
            )

            activity_id = uuid.UUID(cmd.activity_id)
            progress = PostgresProgressReadRepository(conn)
            rejection = await progress.void_activity(
                organization_id=organization_id,
                activity_id=activity_id,
                reason="Undone via WhatsApp",
                corrected_by_user_id=created_by,
                correlation_id=cmd.correlation_id,
            )
            if rejection is not None:
                # reverse_resolution.py already re-checked existence/
                # reporter/frozen-status in this same transaction --
                # reaching a rejection here means something raced within
                # it, which shouldn't happen. Fail loudly rather than
                # silently report success for a write that didn't happen.
                raise RuntimeError(f"activity undo unexpectedly rejected: {rejection}")
            row_id = activity_id
            # void_activity already writes its own activity_corrections
            # audit row -- no separate outbox_events insert here (an undo
            # retracts a fact, it doesn't create a new one to project into
            # the timeline the way progress_execution.py's create/append
            # paths do).
        elif cmd.target_kind == "attendance":
            assert cmd.attendance_report_id is not None
            from mesiri.infrastructure.postgres.repositories.workforce import (
                PostgresWorkforceReadRepository,
            )

            report_id = uuid.UUID(cmd.attendance_report_id)
            workforce = PostgresWorkforceReadRepository(conn)
            rejection = await workforce.void_attendance_report(
                organization_id=organization_id,
                report_id=report_id,
                reason="Withdrawn via WhatsApp",
                voided_by_user_id=created_by,
            )
            if rejection is not None:
                # Same reasoning as the activity branch: resolution already
                # re-checked existence, ownership and frozen status inside
                # this transaction, so a rejection here means a race that
                # should not be possible. Never report success for a write
                # that did not land.
                raise RuntimeError(f"attendance withdrawal unexpectedly rejected: {rejection}")
            row_id = report_id
            # No outbox event, matching the activity branch: a withdrawal
            # retracts a fact rather than asserting a new one, and the
            # voided_at/voided_by/void_reason stamp is itself the audit
            # record.
        else:  # transfer
            assert cmd.money_transaction_id is not None
            transactions = PostgresMoneyTransactionRepository(conn)
            transaction_id = uuid.UUID(cmd.money_transaction_id)
            await transactions.reverse(organization_id, transaction_id, created_by)
            row_id = transaction_id
            await conn.execute(
                sa.text(
                    "INSERT INTO outbox_events "
                    "(id, aggregate_type, aggregate_id, event_type, payload, correlation_id) "
                    "VALUES (:id, 'money_transaction', :aggregate_id, 'MoneyTransferReversed', "
                    "'{}'::jsonb, :correlation_id)"
                ),
                {"id": uuid.uuid4(), "aggregate_id": transaction_id, "correlation_id": cmd.correlation_id},
            )

        result = ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            idempotency_key=cmd.idempotency_key,
            material_row_id=str(row_id),
        )
        await conn.execute(
            sa.text(
                "UPDATE idempotency_keys "
                "SET status = 'completed', result = CAST(:result AS jsonb), completed_at = now() "
                "WHERE key = :key"
            ),
            {"result": result.model_dump_json(), "key": cmd.idempotency_key},
        )
        await self._transition(conn, cmd.idempotency_key, WorkflowPhase.COMPLETED)
        return result

    async def persist_rejection(
        self, conn: AsyncConnection, cmd: ReverseTransactionCommand, reasons: list[str]
    ) -> ExecutionResult:
        if not await self._try_claim(conn, cmd):
            existing = await self.check_idempotency(conn, cmd.idempotency_key)
            assert existing is not None
            return as_replay(existing)

        result = ExecutionResult(
            status=ExecutionStatus.REJECTED,
            idempotency_key=cmd.idempotency_key,
            rejection_reasons=reasons,
        )
        await conn.execute(
            sa.text(
                "UPDATE idempotency_keys "
                "SET status = 'completed', result = CAST(:result AS jsonb), completed_at = now() "
                "WHERE key = :key"
            ),
            {"result": result.model_dump_json(), "key": cmd.idempotency_key},
        )
        await self._transition(conn, cmd.idempotency_key, WorkflowPhase.EXECUTION_REJECTED)
        return result

    async def _transition(
        self, conn: AsyncConnection, workflow_instance_id: str, new_phase: WorkflowPhase
    ) -> None:
        """Move workflow_instances to `new_phase` on the same connection as the
        domain write. No-op when `workflow_instance_id` doesn't match any row
        (mirrors expense_execution.py's docstring on this same mechanic)."""
        try:
            loaded = await get_by_id_on_connection(conn, workflow_instance_id)
        except ValueError:
            return
        if loaded is None:
            return
        new_state = loaded.state.model_copy(update={"phase": new_phase})
        await transition_on_connection(conn, workflow_instance_id, loaded.version, new_state)
