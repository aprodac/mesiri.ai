"""Moving material between two sites, and entering what was already on site.

The one implementation behind the web routes (``router.py``) and the WhatsApp
assistant's save (``application/materials``): a transfer is two rows sharing
a ``transfer_id`` (TRANSFER_OUT at the sender, TRANSFER_IN at the receiver) and
their two ledger movements, always written together in the caller's transaction.
Opening stock is entered once per site + material (BE-12).

Callers resolve and authorise first (who may write to which site, which
material and unit); this module only applies the stock rules and writes.
Rule failures raise ``MaterialRuleError`` carrying the HTTP status the web
routes answer with, so the router's behaviour is unchanged.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.materials.posting import post_material_movement
from mesiri.domains.materials.validation import OPENING_STOCK
from mesiri.infrastructure.postgres.repositories.materials import PostgresMaterialReadRepository


class MaterialRuleError(Exception):
    """A stock rule refused the write. ``detail`` is the message (or the
    structured detail the web route returns); ``status_code`` its HTTP status."""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class TransferIds:
    transfer_id: uuid.UUID
    outflow_id: uuid.UUID
    inflow_id: uuid.UUID


async def assert_no_opening_stock(
    conn: AsyncConnection,
    organization_id: uuid.UUID,
    site_id: uuid.UUID | None,
    material: dict,
) -> None:
    """Opening stock is entered once per site+material (BE-12). A second one
    would count what was on site twice; the fix for a wrong figure is to
    correct the first entry or post an adjustment. A corrected (reversed)
    opening entry no longer counts, so it can be entered again.

    Takes the same per-site+material lock as the outflow stock guard, so two
    people entering opening stock at once cannot both pass."""
    await PostgresMaterialReadRepository(conn).lock_stock_for_update(site_id, material["id"])
    existing = (
        await conn.execute(
            text(
                "SELECT r.occurred_date FROM material_receipts r "
                "WHERE r.organization_id = :org_id AND r.material_id = :material_id "
                "AND r.site_id IS NOT DISTINCT FROM CAST(:site_id AS uuid) "
                "AND r.movement_reason = :reason "
                "AND NOT EXISTS (SELECT 1 FROM material_usage u WHERE u.reverses_movement_id = r.id) "
                "LIMIT 1"
            ),
            {
                "org_id": organization_id,
                "material_id": material["id"],
                "site_id": site_id,
                "reason": OPENING_STOCK,
            },
        )
    ).first()
    if existing is not None:
        raise MaterialRuleError(
            409,
            f"Opening stock for {material['name']} at this site was already entered "
            f"(dated {existing[0]}). Correct that entry, or record an adjustment.",
        )


async def record_transfer(
    conn: AsyncConnection,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    material: dict,
    unit: dict,
    from_project_id: uuid.UUID,
    from_site_id: uuid.UUID,
    to_project_id: uuid.UUID,
    to_site_id: uuid.UUID,
    quantity: Decimal,
    occurred_date: datetime.date,
    notes: str | None = None,
    allow_negative: bool = False,
    source: str = "web",
    correlation_id: str | None = None,
    publish_event: Any,
) -> TransferIds:
    """Write one transfer: TRANSFER_OUT + TRANSFER_IN rows, their ISSUE and
    RECEIPT movements and both outbox events, in the caller's transaction.

    ``publish_event`` is the caller's outbox writer (the router's
    ``_publish_outbox_event``), so both paths publish identically."""
    if quantity <= 0:
        raise MaterialRuleError(422, "quantity must be greater than zero")
    if from_site_id == to_site_id:
        raise MaterialRuleError(422, "A transfer needs two different sites")

    if not allow_negative:
        read_repo = PostgresMaterialReadRepository(conn)
        await read_repo.lock_stock_for_update(from_site_id, material["id"])
        available = await read_repo.get_available_stock(organization_id, from_site_id, material["id"])
        if quantity > available:
            raise MaterialRuleError(
                409,
                {
                    "message": (
                        f"Only {available} {unit['code']} of {material['name']} "
                        f"at the sending site, but {quantity} was entered."
                    ),
                    "available": str(available),
                    "requested": str(quantity),
                    "unit": unit["code"],
                    "material_name": material["name"],
                },
            )

    transfer_id = uuid.uuid4()
    outflow_id = uuid.uuid4()
    inflow_id = uuid.uuid4()
    notes = notes.strip() if notes else None
    occurred_at = datetime.datetime.combine(occurred_date, datetime.time.min)
    common = {
        "organization_id": organization_id,
        "material_name": material["name"],
        "quantity": quantity,
        "unit": unit["code"],
        "unit_id": unit["id"],
        "occurred_date": occurred_date,
        "notes": notes,
        "material_id": material["id"],
        "created_by": user_id,
        "transfer_id": transfer_id,
        "source": source,
        "correlation_id": correlation_id,
    }
    await conn.execute(
        text(
            "INSERT INTO material_usage "
            "(id, organization_id, project_id, site_id, material_name, quantity, unit, unit_id, "
            "work_item, occurred_date, occurred_date_source, source, movement_reason, notes, "
            "material_id, created_by, transfer_id, correlation_id) "
            "VALUES (:id, :organization_id, :project_id, :site_id, :material_name, "
            ":quantity, :unit, :unit_id, NULL, :occurred_date, 'reported', :source, "
            "'TRANSFER_OUT', :notes, :material_id, :created_by, :transfer_id, :correlation_id)"
        ),
        {**common, "id": outflow_id, "project_id": from_project_id, "site_id": from_site_id},
    )
    await conn.execute(
        text(
            "INSERT INTO material_receipts "
            "(id, organization_id, project_id, site_id, material_name, quantity, unit, unit_id, "
            "supplier, occurred_date, occurred_date_source, source, movement_reason, notes, "
            "material_id, created_by, transfer_id, correlation_id) "
            "VALUES (:id, :organization_id, :project_id, :site_id, :material_name, "
            ":quantity, :unit, :unit_id, NULL, :occurred_date, 'reported', :source, "
            "'TRANSFER_IN', :notes, :material_id, :created_by, :transfer_id, :correlation_id)"
        ),
        {**common, "id": inflow_id, "project_id": to_project_id, "site_id": to_site_id},
    )
    for movement_type, source_type, source_id, project_id, site_id in (
        ("ISSUE", "material_usage", outflow_id, from_project_id, from_site_id),
        ("RECEIPT", "material_receipt", inflow_id, to_project_id, to_site_id),
    ):
        await post_material_movement(
            conn,
            movement_type=movement_type,
            material_id=material["id"],
            unit_id=unit["id"],
            quantity=quantity,
            organization_id=organization_id,
            project_id=project_id,
            site_id=site_id,
            occurred_at=occurred_at,
            source_type=source_type,
            source_id=source_id,
            recorded_by_user_id=user_id,
        )
    event = {
        "material_name": material["name"],
        "quantity": str(quantity),
        "unit": unit["code"],
        "occurred_date": occurred_date.isoformat(),
        "occurred_date_source": "reported",
        "transfer_id": str(transfer_id),
    }
    await publish_event(
        conn,
        aggregate_type="material_usage",
        aggregate_id=outflow_id,
        event_type="MaterialUsed",
        payload={**event, "movement_reason": "TRANSFER_OUT"},
    )
    await publish_event(
        conn,
        aggregate_type="material_receipt",
        aggregate_id=inflow_id,
        event_type="MaterialReceived",
        payload={**event, "movement_reason": "TRANSFER_IN"},
    )
    return TransferIds(transfer_id, outflow_id, inflow_id)


__all__ = ["MaterialRuleError", "TransferIds", "assert_no_opening_stock", "record_transfer"]
