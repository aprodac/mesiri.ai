"""BOQ on the existing planning tables: rates, codes and order (CC-02).

A project's Bill of Quantities is the planning layer 0420 created and never wired:
a section is a ``work_packages`` row ("Concrete work", "Ground floor"), a BOQ line is
a ``work_package_planned_items`` row (what, unit, planned quantity, with revision
history). No parallel BOQ table (docs/plans/cost-control-plan.md section 4).

This adds what a line needs to be a budget, all nullable so a quantity-only BOQ works:
- ``boq_code``: the line's number in the customer's estimate ("3.2").
- ``client_rate``: what the client pays per unit (the quoted rate).
- ``labour_rate``, ``material_rate``, ``subcontract_rate``: the internal budget per unit,
  split the way cost is compared later (CC-07). Budget cost per unit is their sum.
- ``sort_order`` on lines and sections: the estimate's order.
- ``organization_id`` on lines, filled from their section, so the table gets the same
  row-level security as every company table (0484). 0420 left it out because nothing
  wrote the table; it is empty in production, and the fill covers any row regardless.

Additive only: no column is dropped, renamed or rewritten.

Revision ID: 0508
Revises: 0507
Create Date: 2026-11-06
"""

from __future__ import annotations

from alembic import op

revision = "0508"
down_revision = "0507"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"
_RATES = ("client_rate", "labour_rate", "material_rate", "subcontract_rate")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE work_package_planned_items ADD COLUMN organization_id uuid "
        "REFERENCES organizations(id) ON DELETE CASCADE"
    )
    op.execute(
        "UPDATE work_package_planned_items i SET organization_id = w.organization_id "
        "FROM work_packages w WHERE w.id = i.work_package_id"
    )
    op.execute("ALTER TABLE work_package_planned_items ALTER COLUMN organization_id SET NOT NULL")
    op.execute(
        "CREATE INDEX ix_work_package_planned_items_organization_id "
        "ON work_package_planned_items (organization_id)"
    )
    op.execute("ALTER TABLE work_package_planned_items ADD COLUMN boq_code text")
    for column in _RATES:
        op.execute(
            f"ALTER TABLE work_package_planned_items ADD COLUMN {column} numeric(14, 2) "
            f"CONSTRAINT ck_planned_items_{column}_not_negative CHECK ({column} >= 0)"
        )
    op.execute("ALTER TABLE work_package_planned_items ADD COLUMN sort_order integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE work_packages ADD COLUMN sort_order integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE work_package_planned_items ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON work_package_planned_items USING ({_RULE}) WITH CHECK ({_RULE})"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON work_package_planned_items")
    op.execute("ALTER TABLE work_package_planned_items DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE work_packages DROP COLUMN IF EXISTS sort_order")
    op.execute("ALTER TABLE work_package_planned_items DROP COLUMN IF EXISTS sort_order")
    for column in _RATES:
        op.execute(f"ALTER TABLE work_package_planned_items DROP COLUMN IF EXISTS {column}")
    op.execute("ALTER TABLE work_package_planned_items DROP COLUMN IF EXISTS boq_code")
    op.execute("DROP INDEX IF EXISTS ix_work_package_planned_items_organization_id")
    op.execute("ALTER TABLE work_package_planned_items DROP COLUMN IF EXISTS organization_id")
