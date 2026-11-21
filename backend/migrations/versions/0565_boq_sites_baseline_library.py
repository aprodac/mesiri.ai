"""BOQ, what construction ERPs have (PS phase 2b): quantities per site, the approved budget, a rate library, and the
other cost head and provisional sums on a line.

- ``work_package_planned_items.other_rate``: a fifth budget rate (temporary works, testing, small tools), beside labour,
  material, subcontract and machinery (0564).
- ``work_package_planned_items.is_provisional``: a provisional sum (PS): an allowance agreed with the client and priced
  when the work is known ("lifts: ₹2,00,000").
- ``boq_line_sites``: how much of a line each site has ("plastering 1,450 sqm: Villa 1 362.5, Villa 2 362.5 ..."); a
  line without rows here is for the whole project, as before. Moves with the line's revisions, like its norms.
- ``boq_baselines``: the approved budget, as it stood when it was locked (lines and totals copied), so later changes
  show against it ("approved ₹61.3 L, now ₹65.1 L, +₹3.8 L").
- ``boq_library_items``: the company's own rate library: a line saved once (work, unit, rates, materials per unit) and
  added to any project's BOQ.

Additive: new nullable columns (``is_provisional`` NOT NULL with a constant default, no rewrite) and new tables; no row is
changed. Downgrade drops them.

Revision ID: 0565
Revises: 0564
Create Date: 2026-11-20
"""

from __future__ import annotations

from alembic import op

revision = "0565"
down_revision = "0564"
branch_labels = None
depends_on = None

#: Tenant isolation, as every newer table has it (0561).
_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"
_TABLES = ("boq_line_sites", "boq_baselines", "boq_library_items")


def upgrade() -> None:
    op.execute("""
        ALTER TABLE work_package_planned_items
            ADD COLUMN other_rate numeric(14,2),
            ADD COLUMN is_provisional boolean NOT NULL DEFAULT false,
            ADD CONSTRAINT ck_planned_items_other_rate CHECK (other_rate IS NULL OR other_rate >= 0)
    """)
    op.execute("""
        CREATE TABLE boq_line_sites (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            planned_item_id uuid NOT NULL REFERENCES work_package_planned_items(id) ON DELETE CASCADE,
            site_id uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
            quantity numeric(14,3) NOT NULL CHECK (quantity >= 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_boq_line_site UNIQUE (planned_item_id, site_id)
        )""")
    op.execute("CREATE INDEX ix_boq_line_sites_org ON boq_line_sites (organization_id)")
    op.execute("""
        CREATE TABLE boq_baselines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name text NOT NULL,
            note text,
            totals jsonb NOT NULL,
            lines jsonb NOT NULL,
            locked_by uuid REFERENCES users(id) ON DELETE SET NULL,
            locked_at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX ix_boq_baselines_project ON boq_baselines (project_id, locked_at DESC)")
    op.execute("""
        CREATE TABLE boq_library_items (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            work text NOT NULL,
            unit_id uuid NOT NULL REFERENCES units_of_measure(id),
            client_rate numeric(14,2),
            labour_rate numeric(14,2),
            material_rate numeric(14,2),
            subcontract_rate numeric(14,2),
            machinery_rate numeric(14,2),
            other_rate numeric(14,2),
            materials jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE UNIQUE INDEX uq_boq_library_item ON boq_library_items (organization_id, lower(work), unit_id)")
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS boq_library_items")
    op.execute("DROP TABLE IF EXISTS boq_baselines")
    op.execute("DROP TABLE IF EXISTS boq_line_sites")
    op.execute("""
        ALTER TABLE work_package_planned_items
            DROP CONSTRAINT IF EXISTS ck_planned_items_other_rate,
            DROP COLUMN is_provisional,
            DROP COLUMN other_rate
    """)
