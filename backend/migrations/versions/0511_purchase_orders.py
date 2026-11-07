"""Purchase orders: what the office ordered from a supplier, and what has come against it (PRC-06, PRC-08).

A purchase order (PO-0001 per company) is for one site, from one vendor, with one or more lines (material,
quantity in its stock unit, the agreed rate per stock unit). A line may come from a site's request
(`request_line_id`, PRC-22). A delivery points at the order line it fills (`material_receipts.purchase_order_line_id`),
so "received" and "still to come" are read from the deliveries, never typed: the status stored is only `open`,
`closed` (the rest will not come) or `cancelled`; part received / received are worked out.

Additive only: two new tables (row-level security, as every company table) and a nullable column with an index.

Revision ID: 0511
Revises: 0510
Create Date: 2026-11-07
"""

from __future__ import annotations

from alembic import op

revision = "0511"
down_revision = "0510"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE purchase_orders (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            number integer NOT NULL,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            site_id uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
            vendor_id uuid NOT NULL REFERENCES vendors(id),
            status text NOT NULL DEFAULT 'open',
            expected_date date,
            notes text,
            status_note text,
            raised_over_duplicate boolean NOT NULL DEFAULT false,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            status_by uuid REFERENCES users(id) ON DELETE SET NULL,
            status_at timestamptz,
            CONSTRAINT uq_purchase_orders_number UNIQUE (organization_id, number),
            CONSTRAINT ck_purchase_orders_status CHECK (status IN ('open', 'closed', 'cancelled'))
        )
        """
    )
    op.execute("CREATE INDEX ix_purchase_orders_org_status ON purchase_orders (organization_id, status)")
    op.execute("CREATE INDEX ix_purchase_orders_vendor ON purchase_orders (organization_id, vendor_id)")
    op.execute(
        """
        CREATE TABLE purchase_order_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            purchase_order_id uuid NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
            material_id uuid NOT NULL REFERENCES materials_catalog(id),
            unit_id uuid NOT NULL REFERENCES units_of_measure(id),
            quantity numeric(14, 3) NOT NULL,
            rate numeric(14, 2),
            said text,
            request_line_id uuid REFERENCES material_request_lines(id) ON DELETE SET NULL,
            position integer NOT NULL DEFAULT 0,
            CONSTRAINT ck_purchase_order_lines_quantity CHECK (quantity > 0),
            CONSTRAINT ck_purchase_order_lines_rate CHECK (rate IS NULL OR rate >= 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_purchase_order_lines_order ON purchase_order_lines (purchase_order_id)")
    op.execute(
        "CREATE INDEX ix_purchase_order_lines_material ON purchase_order_lines (organization_id, material_id)"
    )
    op.execute("CREATE INDEX ix_purchase_order_lines_request ON purchase_order_lines (request_line_id)")
    for table in ("purchase_orders", "purchase_order_lines"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")
    op.execute(
        "ALTER TABLE material_receipts ADD COLUMN purchase_order_line_id uuid "
        "REFERENCES purchase_order_lines(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX ix_material_receipts_po_line ON material_receipts (purchase_order_line_id) "
        "WHERE purchase_order_line_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_material_receipts_po_line")
    op.execute("ALTER TABLE material_receipts DROP COLUMN IF EXISTS purchase_order_line_id")
    op.execute("DROP TABLE IF EXISTS purchase_order_lines")
    op.execute("DROP TABLE IF EXISTS purchase_orders")
