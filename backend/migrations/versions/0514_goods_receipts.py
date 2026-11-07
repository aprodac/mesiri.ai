"""Goods received notes: what came against an order, checked at the gate (PRC-29).

A GRN (GRN-0001 per company) is one receiving of an order: the date, the supplier's challan number and its photo,
who received it, and per order line what was accepted (into stock: the delivery, ``material_receipts``) and what was
rejected and why (not in stock; still to come, a replacement is owed).

Additive only: two new tables (row-level security, as every company table).

Revision ID: 0514
Revises: 0513
Create Date: 2026-11-07
"""

from __future__ import annotations

from alembic import op

revision = "0514"
down_revision = "0513"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE goods_receipts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            number integer NOT NULL,
            purchase_order_id uuid NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
            received_on date NOT NULL,
            challan_no text,
            challan_photo_key text,
            received_by_name text,
            notes text,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_goods_receipts_number UNIQUE (organization_id, number)
        )
        """
    )
    op.execute("CREATE INDEX ix_goods_receipts_order ON goods_receipts (purchase_order_id)")
    op.execute(
        """
        CREATE TABLE goods_receipt_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            goods_receipt_id uuid NOT NULL REFERENCES goods_receipts(id) ON DELETE CASCADE,
            purchase_order_line_id uuid NOT NULL REFERENCES purchase_order_lines(id) ON DELETE CASCADE,
            accepted numeric(14, 3) NOT NULL DEFAULT 0,
            rejected numeric(14, 3) NOT NULL DEFAULT 0,
            rejected_reason text,
            material_receipt_id uuid REFERENCES material_receipts(id) ON DELETE SET NULL,
            CONSTRAINT ck_goods_receipt_lines_quantities CHECK (accepted >= 0 AND rejected >= 0 AND accepted + rejected > 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_goods_receipt_lines_grn ON goods_receipt_lines (goods_receipt_id)")
    op.execute("CREATE INDEX ix_goods_receipt_lines_po_line ON goods_receipt_lines (purchase_order_line_id)")
    for table in ("goods_receipts", "goods_receipt_lines"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS goods_receipt_lines")
    op.execute("DROP TABLE IF EXISTS goods_receipts")
