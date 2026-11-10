"""Physical stock count (PRC-48).

See docs/plans/procurement-phase2-plan.md §5.5. Additive only (two new tables with tenant row-level security):

- ``stock_counts``: one count of one site (SC-0001 per company): all items, one category, or the 20 most valuable
  (``scope``). Status open (being counted) -> approved (differences posted as ADJUSTMENT_IN/OUT) or cancelled.
  Never edited after approval: a new count corrects it.
- ``stock_count_lines``: per material, the book quantity frozen when the count started, what was counted (empty: not
  counted), the reason for a difference, the average rate it is priced at, and the adjustment it posted
  (``receipt_id`` / ``usage_id``).

Revision ID: 0543
Revises: 0542
Create Date: 2026-11-10
"""

from __future__ import annotations

from alembic import op

revision = "0543"
down_revision = "0542"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"
_TABLES = ("stock_counts", "stock_count_lines")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE stock_counts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            number integer NOT NULL,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            site_id uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
            scope text NOT NULL DEFAULT 'all',
            category_id uuid REFERENCES material_categories(id) ON DELETE SET NULL,
            status text NOT NULL DEFAULT 'open',
            notes text,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            approved_by uuid REFERENCES users(id) ON DELETE SET NULL,
            approved_at timestamptz,
            cancel_reason text,
            CONSTRAINT uq_stock_counts_number UNIQUE (organization_id, number),
            CONSTRAINT ck_stock_counts_status CHECK (status IN ('open', 'approved', 'cancelled')),
            CONSTRAINT ck_stock_counts_scope CHECK (scope IN ('all', 'category', 'top'))
        )
        """
    )
    op.execute("CREATE INDEX ix_stock_counts_site ON stock_counts (organization_id, site_id, status)")
    op.execute("CREATE UNIQUE INDEX uq_stock_counts_open_site ON stock_counts (site_id) WHERE status = 'open'")
    op.execute(
        """
        CREATE TABLE stock_count_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            count_id uuid NOT NULL REFERENCES stock_counts(id) ON DELETE CASCADE,
            material_id uuid NOT NULL REFERENCES materials_catalog(id),
            unit_id uuid NOT NULL REFERENCES units_of_measure(id),
            book_qty numeric(14, 3) NOT NULL,
            counted_qty numeric(14, 3),
            reason text,
            rate numeric(14, 2),
            counted_by uuid REFERENCES users(id) ON DELETE SET NULL,
            counted_at timestamptz,
            receipt_id uuid REFERENCES material_receipts(id) ON DELETE SET NULL,
            usage_id uuid REFERENCES material_usage(id) ON DELETE SET NULL,
            CONSTRAINT uq_stock_count_lines UNIQUE (count_id, material_id),
            CONSTRAINT ck_stock_count_lines_counted CHECK (counted_qty IS NULL OR counted_qty >= 0)
        )
        """
    )
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
