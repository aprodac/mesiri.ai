"""Labour on BOQ lines: the automatic split is kept once its week is over, and "on no line" is remembered (BOQ-02b).

BOQ-02 split a site-day's labour over the lines its work went to, worked out on every read; a work update linked or
corrected later then changed last week's labour cost per line, and a report already sent no longer matched the
dashboard. Additive only:

- ``labour_boq_allocations.source``: 'person' (every existing row: what people entered) or 'auto' (BOQ-02's split,
  stored for a day whose week is over, so it stops moving). A person's split replaces either, as before.
- ``labour_boq_day_marks``: a site-day-trade a person took off every line ("on no line"), so the automatic split
  never puts it back. Keyed like the allocations (project, site, day, trade).

Nothing in Labour, Workforce or Payroll changes. Tenant row-level security like 0528. Downgrade refuses while
either holds rows (they are what people chose, or figures reports were built on).

Revision ID: 0554
Revises: 0553
Create Date: 2026-11-15
"""

from __future__ import annotations

from alembic import op

revision = "0554"
down_revision = "0553"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("ALTER TABLE labour_boq_allocations ADD COLUMN source text NOT NULL DEFAULT 'person' "
               "CONSTRAINT ck_labour_boq_allocations_source CHECK (source IN ('person', 'auto'))")
    op.execute("""
        CREATE TABLE labour_boq_day_marks (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            site_id uuid REFERENCES sites(id) ON DELETE CASCADE,
            work_date date NOT NULL,
            trade_key text NOT NULL DEFAULT '',
            mark text NOT NULL CONSTRAINT ck_labour_boq_day_marks_mark CHECK (mark IN ('none')),
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE UNIQUE INDEX uq_labour_boq_day_marks_group ON labour_boq_day_marks "
               "(project_id, COALESCE(site_id, '00000000-0000-0000-0000-000000000000'::uuid), work_date, trade_key)")
    op.execute("CREATE INDEX ix_labour_boq_day_marks_org_project_date ON labour_boq_day_marks "
               "(organization_id, project_id, work_date)")
    op.execute("ALTER TABLE labour_boq_day_marks ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON labour_boq_day_marks USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM labour_boq_day_marks) "
               "OR EXISTS (SELECT 1 FROM labour_boq_allocations WHERE source = 'auto') THEN "
               "RAISE EXCEPTION 'Labour splits are kept (auto or on no line); downgrading would lose them'; END IF; END $$")
    op.execute("DROP TABLE IF EXISTS labour_boq_day_marks")
    op.execute("ALTER TABLE labour_boq_allocations DROP COLUMN IF EXISTS source")
