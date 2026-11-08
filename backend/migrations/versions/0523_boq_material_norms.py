"""Material norms per BOQ line (MP-01, was CC-03): what one unit of a BOQ line consumes.

See docs/plans/material-plan-plan.md. Additive only:

- ``boq_material_norms``: one row per BOQ line and material: "1 m³ of M20 in columns uses 8 bags of cement,
  0.42 m³ of M-sand, 0.84 m³ of 20 mm metal", plus a wastage %. The quantity is in ``unit_id`` (the unit the
  material is stocked in, its stock unit); nothing is converted. A line's revision (a new
  planned quantity, ``superseded_by_id``) carries its norms over to the new row (repository code), so norms always
  hang off the current revision.

The material plan (MP-02) multiplies the line's remaining quantity by these. A material named in a norm is "in use"
and can't be deleted from the catalog (deactivated instead). Row-level security like 0522. Downgrade refuses while
norms exist.

Revision ID: 0523
Revises: 0522
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "0523"
down_revision = "0522"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE boq_material_norms (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            planned_item_id uuid NOT NULL REFERENCES work_package_planned_items(id) ON DELETE CASCADE,
            material_id uuid NOT NULL REFERENCES materials_catalog(id) ON DELETE RESTRICT,
            unit_id uuid NOT NULL REFERENCES units_of_measure(id),
            quantity_per_unit numeric(14,4) NOT NULL,
            wastage_pct numeric(5,2) NOT NULL DEFAULT 0,
            note text,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_boq_material_norm UNIQUE (planned_item_id, material_id),
            CONSTRAINT ck_boq_material_norm_qty CHECK (quantity_per_unit > 0),
            CONSTRAINT ck_boq_material_norm_wastage CHECK (wastage_pct BETWEEN 0 AND 100)
        )""")
    op.execute("CREATE INDEX ix_boq_material_norms_material ON boq_material_norms (material_id)")
    op.execute("CREATE INDEX ix_boq_material_norms_org ON boq_material_norms (organization_id)")
    op.execute("ALTER TABLE boq_material_norms ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON boq_material_norms USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM boq_material_norms) THEN "
               "RAISE EXCEPTION 'material norms exist; downgrading would lose them'; END IF; END $$")
    op.execute("DROP TABLE IF EXISTS boq_material_norms")
