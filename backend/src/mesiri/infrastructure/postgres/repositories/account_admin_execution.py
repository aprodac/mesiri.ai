"""PostgreSQL implementation of mesiri.application.finance.repository.AccountAdminExecutionRepository.

Only file permitted to hold SQL for ManageMoneyAccount execution
(capability-boundary convention, mirrors expense_execution.py). Every method
takes an externally-supplied connection. `persist_success` assumes cmd is
already valid and resolved (the Handler's resolver step already ran) — it
performs the create/rename/deactivate write, composing
PostgresMoneyAccountRepository rather than inlining new account SQL here,
same reasoning as expense_execution.py's use of PostgresExpensePaymentRepository.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa

from mesiri.application.finance.commands import ManageMoneyAccountCommand
from mesiri.application.finance.repository import AccountAdminExecutionRepository
from mesiri.domains.shared import clock
from mesiri.infrastructure.postgres.repositories.finance import PostgresMoneyAccountRepository
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

_COMMAND_TYPE = "manage_money_account"


class PostgresAccountAdminExecutionRepository(AccountAdminExecutionRepository):
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

    async def _try_claim(self, conn: AsyncConnection, cmd: ManageMoneyAccountCommand) -> bool:
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
        self, conn: AsyncConnection, cmd: ManageMoneyAccountCommand
    ) -> ExecutionResult:
        if not await self._try_claim(conn, cmd):
            existing = await self.check_idempotency(conn, cmd.idempotency_key)
            assert existing is not None
            return as_replay(existing)

        repo = PostgresMoneyAccountRepository(conn)
        organization_id = uuid.UUID(cmd.organization_id)
        created_by = uuid.UUID(cmd.created_by)

        if cmd.action == "create":
            assert cmd.name is not None
            account = await repo.create(
                organization_id=organization_id,
                name=cmd.name,
                account_type=cmd.account_type,
                currency="INR",
                opening_balance=Decimal("0"),
                opening_balance_date=clock.today(),
                created_by=created_by,
            )
            row_id = account.id
        elif cmd.action == "rename":
            assert cmd.target_account_id is not None and cmd.new_name is not None
            row_id = uuid.UUID(cmd.target_account_id)
            await repo.rename(organization_id, row_id, cmd.new_name, updated_by=created_by)
        else:  # deactivate
            assert cmd.target_account_id is not None
            row_id = uuid.UUID(cmd.target_account_id)
            await repo.deactivate(organization_id, row_id, updated_by=created_by)

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
        self, conn: AsyncConnection, cmd: ManageMoneyAccountCommand, reasons: list[str]
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
