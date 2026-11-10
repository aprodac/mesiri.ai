"""Minimum stock and reorder quantity per site and material (PRC-47).

See docs/plans/procurement-phase2-plan.md §5.4. Additive only (one new table with tenant row-level security):

- ``stock_levels``: for one site and one material, the minimum the site should hold (``min_qty``, in the material's
  stock unit) and how much to ask for when it goes below (``reorder_qty``; empty: up to twice the minimum). How it was
  set (``set_how``): typed on the dashboard, from the Excel import, suggested from use, or on WhatsApp. No row: no
  minimum, and stock behaves as before.

Revision ID: 0541
Revises: 0540
Create Date: 2026-11-10
"""

from __future__ import annotations

from alembic import op

revision = "0541"
down_revision = "0540"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE stock_levels (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            site_id uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
            material_id uuid NOT NULL REFERENCES materials_catalog(id) ON DELETE CASCADE,
            min_qty numeric(14, 3) NOT NULL,
            reorder_qty numeric(14, 3),
            set_how text NOT NULL DEFAULT 'typed',
            set_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_stock_levels UNIQUE (site_id, material_id),
            CONSTRAINT ck_stock_levels_min CHECK (min_qty >= 0),
            CONSTRAINT ck_stock_levels_reorder CHECK (reorder_qty IS NULL OR reorder_qty > 0),
            CONSTRAINT ck_stock_levels_how CHECK (set_how IN ('typed', 'excel', 'suggested', 'whatsapp'))
        )
        """
    )
    op.execute("CREATE INDEX ix_stock_levels_org ON stock_levels (organization_id, site_id)")
    op.execute("ALTER TABLE stock_levels ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON stock_levels USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stock_levels")
