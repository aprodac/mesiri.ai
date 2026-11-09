"""Quotations: ask several suppliers, record what each quoted, compare, award into orders (PRC-40..44).

See docs/plans/procurement-phase2-plan.md §5.1. Additive only (four new tables with tenant row-level security, two
nullable columns on the order tables):

- ``rfqs``: one request for quotation, RFQ-0001 per company, for one site (where it is delivered). Status open,
  awarded (orders placed from it), closed (no order: prices only), cancelled. ``due_date``: quotes wanted by;
  ``needed_by``: when the site needs it. May start from a site's request (``request_id``).
- ``rfq_lines``: what is asked, in the material's stock unit. ``awarded_quote_line_id`` + ``award_reason`` once a
  supplier is chosen for it (the reason is kept when the chosen one was not the cheapest).
- ``rfq_vendors``: each supplier asked, and their answer: invited, quoted or declined (with why); when the RFQ was
  sent to them; the quote's own terms (valid until, delivery days, payment days, their number, a photo of it).
- ``rfq_quote_lines``: what a supplier quoted for one line: rate per stock unit, GST (as PRC-34), brand, remark.
- ``purchase_orders.rfq_id``, ``purchase_order_lines.quote_line_id``: the order an award made, and the quote line it
  took its rate from.

Revision ID: 0540
Revises: 0539
Create Date: 2026-11-09
"""

from __future__ import annotations

from alembic import op

revision = "0540"
down_revision = "0539"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"
_TABLES = ("rfqs", "rfq_lines", "rfq_vendors", "rfq_quote_lines")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE rfqs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            number integer NOT NULL,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            site_id uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
            request_id uuid REFERENCES material_requests(id) ON DELETE SET NULL,
            status text NOT NULL DEFAULT 'open',
            due_date date,
            needed_by date,
            terms text,
            notes text,
            status_note text,
            status_by uuid REFERENCES users(id) ON DELETE SET NULL,
            status_at timestamptz,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_rfqs_number UNIQUE (organization_id, number),
            CONSTRAINT ck_rfqs_status CHECK (status IN ('open', 'awarded', 'closed', 'cancelled'))
        )
        """
    )
    op.execute("CREATE INDEX ix_rfqs_org_status ON rfqs (organization_id, status)")
    op.execute(
        """
        CREATE TABLE rfq_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            rfq_id uuid NOT NULL REFERENCES rfqs(id) ON DELETE CASCADE,
            material_id uuid NOT NULL REFERENCES materials_catalog(id),
            unit_id uuid NOT NULL REFERENCES units_of_measure(id),
            quantity numeric(14, 3) NOT NULL,
            said text,
            request_line_id uuid REFERENCES material_request_lines(id) ON DELETE SET NULL,
            position integer NOT NULL DEFAULT 0,
            awarded_quote_line_id uuid,
            award_reason text,
            CONSTRAINT ck_rfq_lines_quantity CHECK (quantity > 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_rfq_lines_rfq ON rfq_lines (rfq_id)")
    op.execute(
        """
        CREATE TABLE rfq_vendors (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            rfq_id uuid NOT NULL REFERENCES rfqs(id) ON DELETE CASCADE,
            vendor_id uuid NOT NULL REFERENCES vendors(id),
            status text NOT NULL DEFAULT 'invited',
            sent_at timestamptz,
            decline_reason text,
            quoted_at timestamptz,
            quoted_by uuid REFERENCES users(id) ON DELETE SET NULL,
            valid_until date,
            delivery_days integer,
            payment_days integer,
            their_ref text,
            quote_notes text,
            quote_source text,
            quote_photo_key text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_rfq_vendors UNIQUE (rfq_id, vendor_id),
            CONSTRAINT ck_rfq_vendors_status CHECK (status IN ('invited', 'quoted', 'declined')),
            CONSTRAINT ck_rfq_vendors_days CHECK ((delivery_days IS NULL OR delivery_days BETWEEN 0 AND 365)
                                                 AND (payment_days IS NULL OR payment_days BETWEEN 0 AND 365))
        )
        """
    )
    op.execute("CREATE INDEX ix_rfq_vendors_vendor ON rfq_vendors (organization_id, vendor_id)")
    op.execute(
        """
        CREATE TABLE rfq_quote_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            rfq_vendor_id uuid NOT NULL REFERENCES rfq_vendors(id) ON DELETE CASCADE,
            rfq_line_id uuid NOT NULL REFERENCES rfq_lines(id) ON DELETE CASCADE,
            rate numeric(14, 2) NOT NULL,
            gst_percent numeric(5, 2),
            rate_includes_gst boolean,
            brand text,
            remark text,
            CONSTRAINT uq_rfq_quote_lines UNIQUE (rfq_vendor_id, rfq_line_id),
            CONSTRAINT ck_rfq_quote_lines_rate CHECK (rate >= 0),
            CONSTRAINT ck_rfq_quote_lines_gst CHECK (gst_percent IS NULL OR gst_percent BETWEEN 0 AND 100)
        )
        """
    )
    op.execute("CREATE INDEX ix_rfq_quote_lines_line ON rfq_quote_lines (rfq_line_id)")
    op.execute("ALTER TABLE rfq_lines ADD CONSTRAINT fk_rfq_lines_awarded FOREIGN KEY (awarded_quote_line_id) "
               "REFERENCES rfq_quote_lines(id) ON DELETE SET NULL")
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")
    op.execute("ALTER TABLE purchase_orders ADD COLUMN rfq_id uuid REFERENCES rfqs(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX ix_purchase_orders_rfq ON purchase_orders (rfq_id)")
    op.execute("ALTER TABLE purchase_order_lines ADD COLUMN quote_line_id uuid "
               "REFERENCES rfq_quote_lines(id) ON DELETE SET NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE purchase_order_lines DROP COLUMN IF EXISTS quote_line_id")
    op.execute("DROP INDEX IF EXISTS ix_purchase_orders_rfq")
    op.execute("ALTER TABLE purchase_orders DROP COLUMN IF EXISTS rfq_id")
    op.execute("ALTER TABLE rfq_lines DROP CONSTRAINT IF EXISTS fk_rfq_lines_awarded")
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
