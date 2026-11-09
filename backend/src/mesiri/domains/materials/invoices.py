"""Recording a supplier invoice: one document, many purchases, one expense.

Everything here happens on the caller's connection, inside the caller's
transaction. A half-recorded invoice -- stock updated but no money owed, or an
expense with no purchases behind it -- is worse than a failed submission the
user can retry, so the whole thing lands or none of it does.

Ordering matters and is deliberate:

1. The invoice row, so purchases have a parent to point at.
2. Each line: a `material_receipts` row plus its ledger movement, through the
   same `post_material_movement` every other write path uses. No second stock
   mechanism, no special invoice accounting.
3. The attachment reference, if the original document was uploaded.
4. The Finance expense, via Finance's own handler.

Finance is called, never written to. `RecordExpenseHandler.handle(conn, cmd)`
takes a connection precisely so a caller can enlist it in an existing
transaction, so Materials passes its own and stores the returned id. Materials
does not know how expenses are numbered, categorised, or paid, and must not
learn -- it knows only that a purchase creates an obligation.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.materials.posting import post_material_movement

#: What a material invoice becomes in Finance. An explicit category rather than
#: the org default, so material spend is separable from everything else without
#: anyone having to reclassify it later.
MATERIALS_EXPENSE_CATEGORY = "Materials"


async def insert_invoice(
    conn: AsyncConnection,
    *,
    invoice_id: uuid.UUID,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    site_id: uuid.UUID | None,
    vendor_id: uuid.UUID | None,
    supplier_name: str | None,
    invoice_number: str | None,
    invoice_date: datetime.date | None,
    invoice_total: Decimal | None,
    currency: str,
    source: str,
    correlation_id: str | None,
    notes: str | None,
    created_by: uuid.UUID,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO material_invoices "
            "(id, organization_id, project_id, site_id, vendor_id, supplier_name, "
            "invoice_number, invoice_date, invoice_total, currency, source, correlation_id, "
            "notes, created_by) "
            "VALUES (:id, :organization_id, :project_id, :site_id, :vendor_id, :supplier_name, "
            ":invoice_number, :invoice_date, :invoice_total, :currency, :source, "
            ":correlation_id, :notes, :created_by)"
        ),
        {
            "id": invoice_id,
            "organization_id": organization_id,
            "project_id": project_id,
            "site_id": site_id,
            "vendor_id": vendor_id,
            "supplier_name": supplier_name,
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "invoice_total": invoice_total,
            "currency": currency,
            "source": source,
            "correlation_id": correlation_id,
            "notes": notes,
            "created_by": created_by,
        },
    )


async def insert_invoice_line(
    conn: AsyncConnection,
    *,
    invoice_id: uuid.UUID,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    site_id: uuid.UUID | None,
    material: dict,
    unit: dict,
    quantity: Decimal,
    unit_cost: Decimal | None,
    total_cost: Decimal | None,
    supplier_name: str | None,
    occurred_date: datetime.date,
    created_by: uuid.UUID,
    vendor_id: uuid.UUID | None = None,
    gst_percent: Decimal | None = None,
    rate_includes_gst: bool | None = None,
) -> uuid.UUID:
    """One purchase, recorded exactly like any other inflow but carrying its
    invoice's id. Deliberately a normal `material_receipts` row: inventory,
    ledger, history and corrections must not care whether a purchase arrived by
    photograph or by typing."""
    receipt_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO material_receipts "
            "(id, organization_id, project_id, site_id, material_name, quantity, unit, unit_id, "
            "supplier, vendor_id, occurred_date, occurred_date_source, source, movement_reason, "
            "material_id, unit_cost, total_cost, invoice_id, created_by, gst_percent, rate_includes_gst) "
            "VALUES (:id, :organization_id, :project_id, :site_id, :material_name, :quantity, "
            ":unit, :unit_id, :supplier, :vendor_id, :occurred_date, 'reported', 'invoice', 'RECEIVED', "
            ":material_id, :unit_cost, :total_cost, :invoice_id, :created_by, :gst_percent, :includes_gst)"
        ),
        {
            "id": receipt_id,
            "organization_id": organization_id,
            "project_id": project_id,
            "site_id": site_id,
            "material_name": material["name"],
            "quantity": quantity,
            "unit": unit["code"],
            "unit_id": unit["id"],
            "supplier": supplier_name,
            "vendor_id": vendor_id,
            "occurred_date": occurred_date,
            "material_id": material["id"],
            "unit_cost": unit_cost,
            "total_cost": total_cost,
            "invoice_id": invoice_id,
            "created_by": created_by,
            "gst_percent": gst_percent,
            "includes_gst": rate_includes_gst,
        },
    )
    await post_material_movement(
        conn,
        movement_type="RECEIPT",
        material_id=material["id"],
        unit_id=unit["id"],
        quantity=quantity,
        organization_id=organization_id,
        project_id=project_id,
        site_id=site_id,
        occurred_at=datetime.datetime.combine(occurred_date, datetime.time.min),
        source_type="material_receipt",
        source_id=receipt_id,
        recorded_by_user_id=created_by,
    )
    return receipt_id


async def attach_invoice_document(
    conn: AsyncConnection,
    *,
    invoice_id: uuid.UUID,
    media_object_key: str,
    created_by: uuid.UUID,
    attachment_type: str = "bill",
) -> uuid.UUID:
    """Reference the already-uploaded document. Never copies or re-uploads it:
    the same object key is what Finance's expense attachment points at too, so
    there is one file and several referrers."""
    attachment_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO material_invoice_attachments "
            "(id, invoice_id, media_object_key, attachment_type, created_by) "
            "VALUES (:id, :invoice_id, :media_object_key, :attachment_type, :created_by)"
        ),
        {
            "id": attachment_id,
            "invoice_id": invoice_id,
            "media_object_key": media_object_key,
            "attachment_type": attachment_type,
            "created_by": created_by,
        },
    )
    return attachment_id


def build_expense_command(
    *,
    invoice_id: uuid.UUID,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    site_id: uuid.UUID | None,
    vendor_id: uuid.UUID | None,
    supplier_name: str | None,
    amount: Decimal,
    currency: str,
    occurred_date: datetime.date,
    media_object_key: str | None,
    created_by: uuid.UUID,
    correlation_id: str | None,
):
    """The obligation this invoice creates, in Finance's own command shape.

    Imported lazily by the caller so the materials domain does not import the
    expenses application layer at module scope.

    The idempotency key is derived from the invoice id rather than random, so a
    retried invoice submission can never produce a second expense for the same
    document -- the guarantee that makes "one confirmation, both modules" safe.

    Left unpaid on purpose: accepting a supplier's invoice creates a liability,
    but paying it is a separate decision made later by someone else. Finance
    already models that (`PaymentStatus.UNPAID` with no `account_id`).
    """
    from mesiri.application.expenses.commands import RecordExpenseCommand

    return RecordExpenseCommand(
        idempotency_key=f"material-invoice:{invoice_id}",
        organization_id=str(organization_id),
        project_id=str(project_id),
        site_id=str(site_id) if site_id else None,
        vendor_id=str(vendor_id) if vendor_id else None,
        vendor_text=supplier_name,
        category_text=MATERIALS_EXPENSE_CATEGORY,
        amount=amount,
        currency=currency,
        occurred_date=occurred_date,
        description=f"Material purchase — invoice {invoice_id}",
        # The same object key the material invoice attachment points at, so the
        # bill is viewable from Finance without a second copy of the file.
        media_object_key=media_object_key,
        source="materials_invoice",
        correlation_id=correlation_id,
        created_by=str(created_by),
    )
