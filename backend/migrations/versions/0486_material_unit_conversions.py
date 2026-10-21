"""Unit conversions per material, learned once per company (WA-41).

A material is stocked in ONE unit (materials_catalog.default_unit_id), so stock
stays a single figure. Sites still say what they use: "40 bags sand" for sand
stocked in m³. This table holds how many of the reported unit make one stock
unit ("28 bags of sand = 1 m³" -> per_stock_unit 28), set once by an admin or
project manager (Ilan, 21 Oct 2026) and used for every later report of that
material in that unit, company-wide.

Additive only: a new table, nothing existing changes. Row-level security as
every company table has it (0484).

Revision ID: 0486
Revises: 0485
Create Date: 2026-10-21
"""

from __future__ import annotations

from alembic import op

revision = "0486"
down_revision = "0485"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE material_unit_conversions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            material_id uuid NOT NULL REFERENCES materials_catalog(id) ON DELETE CASCADE,
            from_unit_id uuid NOT NULL REFERENCES units_of_measure(id),
            per_stock_unit numeric NOT NULL CHECK (per_stock_unit > 0),
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_material_unit_conversions UNIQUE (organization_id, material_id, from_unit_id)
        )
        """
    )
    op.execute("ALTER TABLE material_unit_conversions ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON material_unit_conversions USING ({_RULE}) WITH CHECK ({_RULE})"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS material_unit_conversions")
