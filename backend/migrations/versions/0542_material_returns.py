"""Returns to the supplier and their debit notes (PRC-46).

See docs/plans/procurement-phase2-plan.md §5.3. Additive only (two new tables with tenant row-level security):

- ``material_returns``: one return to one supplier from one site; its number is the debit note's (DN-0001 per
  company). Status waiting (for pickup) -> sent (back) -> settled (by a replacement delivery, or by credit on the next
  bill or payment); or cancelled while still waiting. Where it started (``goods_receipt_id``: a GRN's rejected
  quantity), photos (``photo_keys``), who collected it and when it went back, and how it was settled
  (``settled_how`` with the replacement delivery, the bill or the payment it went against).
- ``material_return_lines``: what went back: material, quantity (stock unit), rate (the delivery's, as recorded; GST
  as on a delivery, PRC-34), reason (damaged, short, wrong_size, excess, quality_failed), and the delivery it came
  from (``receipt_id``) or the GRN line whose rejected quantity it is (``grn_line_id``). ``usage_id``: the
  RETURN_TO_VENDOR use that took it out of stock (none for a GRN's rejected quantity: never in stock).

Revision ID: 0542
Revises: 0541
Create Date: 2026-11-10
"""

from __future__ import annotations

from alembic import op

revision = "0542"
down_revision = "0541"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"
_TABLES = ("material_returns", "material_return_lines")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE material_returns (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            number integer NOT NULL,
            vendor_id uuid NOT NULL REFERENCES vendors(id),
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            site_id uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
            goods_receipt_id uuid REFERENCES goods_receipts(id) ON DELETE SET NULL,
            status text NOT NULL DEFAULT 'waiting',
            returned_on date NOT NULL,
            notes text,
            photo_keys text[] NOT NULL DEFAULT '{}',
            source text NOT NULL DEFAULT 'web',
            sent_on date,
            collected_by text,
            settled_how text,
            settled_receipt_id uuid REFERENCES material_receipts(id) ON DELETE SET NULL,
            settled_expense_id uuid REFERENCES expenses(id) ON DELETE SET NULL,
            settled_payment_id uuid REFERENCES expense_payments(id) ON DELETE SET NULL,
            settled_note text,
            settled_on date,
            cancel_reason text,
            status_by uuid REFERENCES users(id) ON DELETE SET NULL,
            status_at timestamptz,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_material_returns_number UNIQUE (organization_id, number),
            CONSTRAINT ck_material_returns_status CHECK (status IN ('waiting', 'sent', 'settled', 'cancelled')),
            CONSTRAINT ck_material_returns_settled CHECK (settled_how IS NULL OR settled_how IN ('replacement', 'credit'))
        )
        """
    )
    op.execute("CREATE INDEX ix_material_returns_org_status ON material_returns (organization_id, status)")
    op.execute("CREATE INDEX ix_material_returns_vendor ON material_returns (organization_id, vendor_id)")
    op.execute(
        """
        CREATE TABLE material_return_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            return_id uuid NOT NULL REFERENCES material_returns(id) ON DELETE CASCADE,
            material_id uuid NOT NULL REFERENCES materials_catalog(id),
            unit_id uuid NOT NULL REFERENCES units_of_measure(id),
            quantity numeric(14, 3) NOT NULL,
            rate numeric(14, 2),
            gst_percent numeric(5, 2),
            rate_includes_gst boolean,
            reason text NOT NULL,
            receipt_id uuid REFERENCES material_receipts(id) ON DELETE SET NULL,
            grn_line_id uuid REFERENCES goods_receipt_lines(id) ON DELETE SET NULL,
            usage_id uuid REFERENCES material_usage(id) ON DELETE SET NULL,
            position integer NOT NULL DEFAULT 0,
            CONSTRAINT ck_material_return_lines_quantity CHECK (quantity > 0),
            CONSTRAINT ck_material_return_lines_rate CHECK (rate IS NULL OR rate >= 0),
            CONSTRAINT ck_material_return_lines_gst CHECK (gst_percent IS NULL OR gst_percent BETWEEN 0 AND 100),
            CONSTRAINT ck_material_return_lines_reason CHECK (
                reason IN ('damaged', 'short', 'wrong_size', 'excess', 'quality_failed'))
        )
        """
    )
    op.execute("CREATE INDEX ix_material_return_lines_return ON material_return_lines (return_id)")
    op.execute("CREATE INDEX ix_material_return_lines_receipt ON material_return_lines (receipt_id)")
    op.execute("CREATE INDEX ix_material_return_lines_grn_line ON material_return_lines (grn_line_id)")
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
