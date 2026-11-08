"""Labour put on BOQ lines (CC-05).

See docs/plans/cost-control-plan.md (CC-05, section 13). Additive only:

- ``labour_boq_allocations``: a site's day of one trade (masons, helpers ...) put on a BOQ line, by man-days,
  so labour cost can be set against the labour budget each line earned. Keyed by project, site, day and trade
  (``trade_key``: the trade trimmed and lower-cased, '' when none was said), not by attendance line: attendance
  is a snapshot per site and day, and a re-sent list replaces the earlier lines (BE-10), so a link on a line
  would be lost on every correction. Several rows for one site, day and trade split it over several lines.
  ``planned_item_id`` may point at an earlier revision of a line; readers map it to the current one.

Nothing in Labour, Workforce or Payroll changes. Tenant row-level security like 0527.
Downgrade refuses while allocations exist (they are what people entered).

Revision ID: 0528
Revises: 0527
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "0528"
down_revision = "0527"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE labour_boq_allocations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            site_id uuid REFERENCES sites(id) ON DELETE CASCADE,
            work_date date NOT NULL,
            trade_key text NOT NULL DEFAULT '',
            planned_item_id uuid NOT NULL REFERENCES work_package_planned_items(id) ON DELETE CASCADE,
            man_days numeric(10, 2) NOT NULL,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_labour_boq_allocations_man_days CHECK (man_days > 0)
        )""")
    op.execute("CREATE UNIQUE INDEX uq_labour_boq_allocations_group_line ON labour_boq_allocations "
               "(project_id, COALESCE(site_id, '00000000-0000-0000-0000-000000000000'::uuid), work_date, trade_key, "
               "planned_item_id)")
    op.execute("CREATE INDEX ix_labour_boq_allocations_org_project_date ON labour_boq_allocations "
               "(organization_id, project_id, work_date)")
    op.execute("CREATE INDEX ix_labour_boq_allocations_item ON labour_boq_allocations (planned_item_id)")
    op.execute("ALTER TABLE labour_boq_allocations ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON labour_boq_allocations USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM labour_boq_allocations) THEN "
               "RAISE EXCEPTION 'Labour is put on BOQ lines; downgrading would lose it'; END IF; END $$")
    op.execute("DROP TABLE IF EXISTS labour_boq_allocations")
