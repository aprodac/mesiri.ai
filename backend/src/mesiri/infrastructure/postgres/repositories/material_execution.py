"""PostgreSQL implementation of mesiri.application.materials.repository.MaterialExecutionRepository.

The only file permitted to hold SQL for material_receipts/material_usage
execution (capability-boundary convention). Every method takes an externally-
supplied connection — the Application Handler opens the one transaction
(via PostgresDatabase.transaction()); this repository never commits.

Reuses backend.postgres.workflow_instance's connection-scoped helpers
(transition_on_connection, get_by_id_on_connection) rather than duplicating
workflow_instances SQL here — that table's SQL stays owned by one file.
"""

from __future__ import annotations

import datetime
import json
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from mesiri.application.materials.repository import MaterialCommand, MaterialExecutionRepository
from mesiri.domains.materials.posting import post_material_movement
from mesiri.domains.materials.transfers import (
    MaterialRuleError,
    assert_no_opening_stock,
    record_transfer,
)
from mesiri.domains.materials.validation import OPENING_STOCK
from mesiri.infrastructure.postgres.workflow_instance import (
    get_by_id_on_connection,
    transition_on_connection,
)
from mesiri_contracts.application.commands.material import (
    RecordMaterialReceiptCommand,
    RecordMaterialTransferCommand,
)
from mesiri_contracts.application.results.execution_result import (
    ExecutionResult,
    ExecutionStatus,
    as_replay,
)
from mesiri_contracts.context.enums import WorkflowPhase

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


def _command_type(cmd: MaterialCommand) -> str:
    if isinstance(cmd, RecordMaterialTransferCommand):
        return "record_material_transfer"
    return (
        "record_material_receipt"
        if isinstance(cmd, RecordMaterialReceiptCommand)
        else "record_material_usage"
    )


def _optional_uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value is not None else None


async def _keep_bill_with_receipt(
    conn: AsyncConnection,
    cmd: RecordMaterialReceiptCommand,
    *,
    receipt_id: uuid.UUID,
    project_id: uuid.UUID,
    site_id: uuid.UUID | None,
) -> None:
    """PHO-03: the photo of the bill the delivery was read from stays with the
    receipt: one invoice record (source "whatsapp", no total -- the photo is the
    document) holding the attachment, and the receipt points at it. The same
    tables and the same ``/invoices/{id}/attachment`` link the dashboard already
    uses for a bill uploaded there; the object itself is not copied."""
    from sqlalchemy import text

    from mesiri.domains.materials.invoices import attach_invoice_document, insert_invoice

    invoice_id = uuid.uuid4()
    created_by = uuid.UUID(cmd.created_by)
    await insert_invoice(
        conn,
        invoice_id=invoice_id,
        organization_id=uuid.UUID(cmd.organization_id),
        project_id=project_id,
        site_id=site_id,
        vendor_id=None,
        supplier_name=cmd.supplier,
        invoice_number=None,
        invoice_date=cmd.occurred_date,
        invoice_total=None,
        currency="INR",
        source="whatsapp",
        correlation_id=cmd.correlation_id,
        notes=None,
        created_by=created_by,
    )
    await attach_invoice_document(
        conn, invoice_id=invoice_id, media_object_key=cmd.media_object_key or "", created_by=created_by
    )
    await conn.execute(
        text("UPDATE material_receipts SET invoice_id = :invoice WHERE id = :id"),
        {"invoice": invoice_id, "id": receipt_id},
    )


class PostgresMaterialExecutionRepository(MaterialExecutionRepository):
    async def check_idempotency(self, conn: AsyncConnection, key: str) -> ExecutionResult | None:
        from sqlalchemy import text

        row = (
            (
                await conn.execute(
                    text("SELECT status, result FROM idempotency_keys WHERE key = :key"),
                    {"key": key},
                )
            )
            .mappings()
            .first()
        )
        if row is None or row["status"] != "completed" or row["result"] is None:
            return None
        result_json = row["result"]
        if not isinstance(result_json, str):
            result_json = json.dumps(result_json)
        return ExecutionResult.model_validate_json(result_json)

    async def _try_claim(self, conn: AsyncConnection, cmd: MaterialCommand) -> bool:
        """INSERT ... ON CONFLICT DO NOTHING — True if this call won the claim."""
        from sqlalchemy import text

        claimed = (
            await conn.execute(
                text(
                    "INSERT INTO idempotency_keys (key, command_type, status) "
                    "VALUES (:key, :command_type, 'in_progress') "
                    "ON CONFLICT (key) DO NOTHING RETURNING key"
                ),
                {"key": cmd.idempotency_key, "command_type": _command_type(cmd)},
            )
        ).first()
        return claimed is not None

    async def persist_success(self, conn: AsyncConnection, cmd: MaterialCommand) -> ExecutionResult:
        from sqlalchemy import text

        if not await self._try_claim(conn, cmd):
            # A concurrent transaction already claimed this key. Postgres's row
            # lock on the conflicting INSERT means this call only reaches here
            # after the winner's transaction has committed (or rolled back) --
            # so the row is already visible as completed by the time we look.
            # This call did not perform the write, so a cached SUCCEEDED is
            # reported as ALREADY_EXECUTED, not SUCCEEDED again.
            existing = await self.check_idempotency(conn, cmd.idempotency_key)
            assert existing is not None
            return as_replay(existing)

        if cmd.material_id is None or cmd.unit_id is None:
            raise RuntimeError(
                "persist_success called with unresolved material_id/unit_id — "
                "the Handler must resolve these before calling persist_success"
            )
        material_id = uuid.UUID(cmd.material_id)
        unit_id = uuid.UUID(cmd.unit_id)
        project_id = _optional_uuid(cmd.project_id)
        site_id = _optional_uuid(cmd.site_id)
        occurred_at = datetime.datetime.combine(cmd.occurred_date, datetime.time.min)

        if isinstance(cmd, RecordMaterialTransferCommand):
            return await self._persist_transfer(conn, cmd, material_id, unit_id)

        row_id = uuid.uuid4()
        if isinstance(cmd, RecordMaterialReceiptCommand):
            # Request 164: a cost said with the delivery; one of the two gives the other.
            total_cost, unit_cost = cmd.total_cost, cmd.unit_cost
            if total_cost is None and unit_cost is not None:
                total_cost = unit_cost * cmd.quantity
            elif unit_cost is None and total_cost is not None and cmd.quantity:
                unit_cost = (total_cost / cmd.quantity).quantize(Decimal("0.01"))
            await conn.execute(
                text(
                    "INSERT INTO material_receipts "
                    "(id, organization_id, project_id, site_id, material_name, quantity, unit, "
                    "unit_id, material_id, supplier, occurred_date, occurred_date_source, "
                    "movement_reason, notes, correlation_id, created_by, unit_cost, total_cost) "
                    "VALUES (:id, :organization_id, :project_id, :site_id, :material_name, "
                    ":quantity, :unit, :unit_id, :material_id, :supplier, :occurred_date, "
                    ":occurred_date_source, COALESCE(:movement_reason, 'RECEIVED'), :notes, "
                    ":correlation_id, :created_by, :unit_cost, :total_cost)"
                ),
                {
                    "id": row_id,
                    "organization_id": uuid.UUID(cmd.organization_id),
                    "project_id": project_id,
                    "site_id": site_id,
                    "material_name": cmd.material_name,
                    "quantity": cmd.quantity,
                    "unit": cmd.unit,
                    "unit_id": unit_id,
                    "material_id": material_id,
                    "supplier": cmd.supplier,
                    "unit_cost": unit_cost,
                    "total_cost": total_cost,
                    "movement_reason": cmd.movement_reason,
                    "notes": cmd.notes,
                    "occurred_date": cmd.occurred_date,
                    "occurred_date_source": cmd.occurred_date_source,
                    "correlation_id": cmd.correlation_id,
                    "created_by": uuid.UUID(cmd.created_by),
                },
            )
            if cmd.media_object_key and project_id is not None:
                await _keep_bill_with_receipt(conn, cmd, receipt_id=row_id, project_id=project_id, site_id=site_id)
            aggregate_type, event_type = "material_receipt", "MaterialReceived"
            movement_type, source_type = "RECEIPT", "material_receipt"
        else:
            await conn.execute(
                text(
                    "INSERT INTO material_usage "
                    "(id, organization_id, project_id, site_id, material_name, quantity, unit, "
                    "unit_id, material_id, work_item, occurred_date, occurred_date_source, "
                    "movement_reason, notes, correlation_id, created_by) "
                    "VALUES (:id, :organization_id, :project_id, :site_id, :material_name, "
                    ":quantity, :unit, :unit_id, :material_id, :work_item, :occurred_date, "
                    ":occurred_date_source, COALESCE(:movement_reason, 'CONSUMED'), :notes, "
                    ":correlation_id, :created_by)"
                ),
                {
                    "id": row_id,
                    "organization_id": uuid.UUID(cmd.organization_id),
                    "project_id": project_id,
                    "site_id": site_id,
                    "material_name": cmd.material_name,
                    "quantity": cmd.quantity,
                    "unit": cmd.unit,
                    "unit_id": unit_id,
                    "material_id": material_id,
                    "work_item": cmd.work_item,
                    "movement_reason": cmd.movement_reason,
                    "notes": cmd.notes,
                    "occurred_date": cmd.occurred_date,
                    "occurred_date_source": cmd.occurred_date_source,
                    "correlation_id": cmd.correlation_id,
                    "created_by": uuid.UUID(cmd.created_by),
                },
            )
            aggregate_type, event_type = "material_usage", "MaterialUsed"
            movement_type, source_type = "ISSUE", "material_usage"

        if project_id is None:
            raise RuntimeError("project_id is required to post a material_movement")
        await post_material_movement(
            conn,
            movement_type=movement_type,
            material_id=material_id,
            unit_id=unit_id,
            quantity=cmd.quantity,
            organization_id=uuid.UUID(cmd.organization_id),
            project_id=project_id,
            site_id=site_id,
            occurred_at=occurred_at,
            source_type=source_type,
            source_id=row_id,
            recorded_by_user_id=uuid.UUID(cmd.created_by),
            idempotency_key=cmd.idempotency_key,
        )

        payload = {
            "material_name": cmd.material_name,
            "quantity": str(cmd.quantity),
            "unit": cmd.unit,
            "occurred_date": cmd.occurred_date.isoformat(),
            "occurred_date_source": cmd.occurred_date_source,
        }
        await conn.execute(
            text(
                "INSERT INTO outbox_events "
                "(id, aggregate_type, aggregate_id, event_type, payload, correlation_id) "
                "VALUES (:id, :aggregate_type, :aggregate_id, :event_type, "
                "CAST(:payload AS jsonb), :correlation_id)"
            ),
            {
                "id": uuid.uuid4(),
                "aggregate_type": aggregate_type,
                "aggregate_id": row_id,
                "event_type": event_type,
                "payload": json.dumps(payload),
                "correlation_id": cmd.correlation_id,
            },
        )

        result = ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            idempotency_key=cmd.idempotency_key,
            material_row_id=str(row_id),
        )
        await conn.execute(
            text(
                "UPDATE idempotency_keys "
                "SET status = 'completed', result = CAST(:result AS jsonb), completed_at = now() "
                "WHERE key = :key"
            ),
            {"result": result.model_dump_json(), "key": cmd.idempotency_key},
        )

        await self._transition(conn, cmd.idempotency_key, WorkflowPhase.COMPLETED)
        return result

    async def check_rules(self, conn: AsyncConnection, cmd: MaterialCommand) -> list[str]:
        """Stock rules that refuse a save (opening stock once per site + material).
        Runs in the Handler's transaction before ``persist_success``; the lock it
        takes holds until that transaction ends."""
        if isinstance(cmd, RecordMaterialReceiptCommand) and cmd.movement_reason == OPENING_STOCK:
            try:
                await assert_no_opening_stock(
                    conn,
                    uuid.UUID(cmd.organization_id),
                    _optional_uuid(cmd.site_id),
                    {"id": uuid.UUID(str(cmd.material_id)), "name": cmd.material_name},
                )
            except MaterialRuleError as exc:
                return [str(exc.detail)]
        if isinstance(cmd, RecordMaterialTransferCommand):
            from sqlalchemy import text

            for site in (cmd.site_id, cmd.to_site_id):
                found = (
                    await conn.execute(
                        text(
                            "SELECT 1 FROM sites WHERE id = :id AND organization_id = :org"
                        ),
                        {"id": uuid.UUID(str(site)), "org": uuid.UUID(cmd.organization_id)},
                    )
                ).first()
                if found is None:
                    return ["site not found"]
        return []

    async def _persist_transfer(
        self,
        conn: AsyncConnection,
        cmd: RecordMaterialTransferCommand,
        material_id: uuid.UUID,
        unit_id: uuid.UUID,
    ) -> ExecutionResult:
        """The same write the web route makes (``domains/materials/transfers``).
        The outflow row's id is the execution's ``material_row_id``: it is the
        reviewable fact, and rejecting it takes back both halves.

        Over-stock is allowed, as for any usage from WhatsApp: the stock line on
        the card warns instead of refusing."""
        from sqlalchemy import text

        from mesiri.domains.materials.router import _publish_outbox_event

        from_project = _optional_uuid(cmd.project_id)
        to_project = _optional_uuid(cmd.to_project_id)
        site_projects = {
            row[0]: row[1]
            for row in (
                await conn.execute(
                    text("SELECT id, project_id FROM sites WHERE organization_id = :org AND id = ANY(:ids)"),
                    {
                        "org": uuid.UUID(cmd.organization_id),
                        "ids": [uuid.UUID(str(cmd.site_id)), uuid.UUID(str(cmd.to_site_id))],
                    },
                )
            ).all()
        }
        from_site, to_site = uuid.UUID(str(cmd.site_id)), uuid.UUID(str(cmd.to_site_id))
        # The site's own project, not the one the sender had selected.
        from_project = site_projects.get(from_site, from_project)
        to_project = site_projects.get(to_site, to_project)
        ids = await record_transfer(
            conn,
            organization_id=uuid.UUID(cmd.organization_id),
            user_id=uuid.UUID(cmd.created_by),
            material={"id": material_id, "name": cmd.material_name},
            unit={"id": unit_id, "code": cmd.unit},
            from_project_id=from_project,
            from_site_id=from_site,
            to_project_id=to_project,
            to_site_id=to_site,
            quantity=cmd.quantity,
            occurred_date=cmd.occurred_date,
            allow_negative=True,
            source="whatsapp",
            correlation_id=cmd.correlation_id,
            publish_event=_publish_outbox_event,
        )
        result = ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            idempotency_key=cmd.idempotency_key,
            material_row_id=str(ids.outflow_id),
        )
        await conn.execute(
            text(
                "UPDATE idempotency_keys "
                "SET status = 'completed', result = CAST(:result AS jsonb), completed_at = now() "
                "WHERE key = :key"
            ),
            {"result": result.model_dump_json(), "key": cmd.idempotency_key},
        )
        await self._transition(conn, cmd.idempotency_key, WorkflowPhase.COMPLETED)
        return result

    async def persist_rejection(
        self, conn: AsyncConnection, cmd: MaterialCommand, reasons: list[str]
    ) -> ExecutionResult:
        from sqlalchemy import text

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
            text(
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
        domain write, using the current version read fresh from this connection."""
        loaded = await get_by_id_on_connection(conn, workflow_instance_id)
        if loaded is None:
            return  # nothing to transition (shouldn't happen; defensive, not fatal)
        new_state = loaded.state.model_copy(update={"phase": new_phase})
        await transition_on_connection(conn, workflow_instance_id, loaded.version, new_state)
