"""The schedule, as construction planners keep it (QA Step 11, 23 Nov 2026): a working calendar, "starts with" links
and the approved programme.

- ``projects.work_week``: the days site works, Monday first, "1" worked ("1111110": Sunday off). Projects that exist
  keep "1111111" (every day, how their schedule was counted until now); new projects start at "1111110".
- ``projects.holidays``: days off besides (Onam, Diwali, a local festival).
- ``work_package_links.kind``: "FS" (starts after the other ends, as every link was) or "SS" (starts with it, plus the
  lag): electrical and plumbing alongside the masonry.
- ``schedule_baselines``: the programme as approved (each activity's dates copied), so later moves show against it
  ("approved finish 26 Sep, now 3 Oct, +7 days"): what a delay or extension-of-time claim is argued on.

Additive: new columns with constant defaults (no row is rewritten) and a new table; downgrade drops them.

Revision ID: 0567
Revises: 0566
Create Date: 2026-11-23
"""

from __future__ import annotations

from alembic import op

revision = "0567"
down_revision = "0566"
branch_labels = None
depends_on = None

#: Tenant isolation, as every newer table has it (0561).
_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE projects
            ADD COLUMN work_week varchar(7) NOT NULL DEFAULT '1111111',
            ADD COLUMN holidays date[] NOT NULL DEFAULT '{}',
            ADD CONSTRAINT ck_projects_work_week CHECK (work_week ~ '^[01]{7}$' AND work_week LIKE '%1%')
    """)
    # Every project there keeps every day; a project made from now on starts with Sunday off.
    op.execute("ALTER TABLE projects ALTER COLUMN work_week SET DEFAULT '1111110'")
    op.execute("""
        ALTER TABLE work_package_links
            ADD COLUMN kind varchar(2) NOT NULL DEFAULT 'FS',
            ADD CONSTRAINT ck_work_package_links_kind CHECK (kind IN ('FS', 'SS'))
    """)
    op.execute("""
        CREATE TABLE schedule_baselines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name text NOT NULL,
            note text,
            finish date,
            activities jsonb NOT NULL,
            locked_by uuid REFERENCES users(id) ON DELETE SET NULL,
            locked_at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX ix_schedule_baselines_project ON schedule_baselines (project_id, locked_at DESC)")
    op.execute("ALTER TABLE schedule_baselines ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON schedule_baselines USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS schedule_baselines")
    op.execute("""
        ALTER TABLE work_package_links
            DROP CONSTRAINT IF EXISTS ck_work_package_links_kind,
            DROP COLUMN kind
    """)
    op.execute("""
        ALTER TABLE projects
            DROP CONSTRAINT IF EXISTS ck_projects_work_week,
            DROP COLUMN holidays,
            DROP COLUMN work_week
    """)
