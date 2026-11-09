"""Tasks as a module (TSK-01, asked in session by Adarsh 9 Nov 2026: "want new module proper").

See docs/plans/tasks-plan.md. Additive only:

- ``tasks``: who does what by when. One row per task: project, site, ``number`` (T-1, T-2... per project), title,
  notes, status (open, doing, blocked, done, cancelled), priority, due date; for a person (``assignee_user_id``), a
  subcontractor (``assignee_vendor_id``) or a team in words (``assignee_team``); optional links to a place, a
  schedule activity (BOQ section), a BOQ line with the quantity expected, and the site issue it came from.
- ``task_events``: the history, never updated or deleted: created, changed (old and new values), status moves,
  comments and photos (a WhatsApp photo is an ``inbound_messages.media_object_key`` of the same company).
- ``tasks`` added to ``organization_settings.enabled_modules`` where that list is stored, recorded in
  ``tasks_switched_on_0533`` so the downgrade takes it off exactly there (as 0518 and 0521 did).

Tenant row-level security like 0527. Downgrade refuses while tasks exist.

Revision ID: 0533
Revises: 0532
Create Date: 2026-11-09
"""

from __future__ import annotations

from alembic import op

revision = "0533"
down_revision = "0532"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE tasks (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            site_id uuid REFERENCES sites(id) ON DELETE SET NULL,
            number integer NOT NULL,
            title text NOT NULL,
            notes text,
            status text NOT NULL DEFAULT 'open',
            priority text NOT NULL DEFAULT 'normal',
            due_date date,
            assignee_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
            assignee_vendor_id uuid REFERENCES vendors(id) ON DELETE SET NULL,
            assignee_team text,
            place_id uuid REFERENCES location_nodes(id) ON DELETE SET NULL,
            work_package_id uuid REFERENCES work_packages(id) ON DELETE SET NULL,
            planned_item_id uuid REFERENCES work_package_planned_items(id) ON DELETE SET NULL,
            expected_quantity numeric(14, 3),
            site_issue_id uuid REFERENCES site_issues(id) ON DELETE SET NULL,
            blocked_reason text,
            started_at timestamptz,
            done_at timestamptz,
            done_by uuid REFERENCES users(id) ON DELETE SET NULL,
            source text NOT NULL DEFAULT 'web',
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_tasks_project_number UNIQUE (project_id, number),
            CONSTRAINT ck_tasks_number CHECK (number > 0),
            CONSTRAINT ck_tasks_status CHECK (status IN ('open', 'doing', 'blocked', 'done', 'cancelled')),
            CONSTRAINT ck_tasks_priority CHECK (priority IN ('normal', 'high', 'urgent')),
            CONSTRAINT ck_tasks_source CHECK (source IN ('web', 'whatsapp')),
            CONSTRAINT ck_tasks_one_assignee CHECK (assignee_user_id IS NULL OR assignee_vendor_id IS NULL),
            CONSTRAINT ck_tasks_expected_quantity CHECK (expected_quantity IS NULL
                OR (expected_quantity > 0 AND planned_item_id IS NOT NULL))
        )""")
    op.execute("CREATE INDEX ix_tasks_org_project_status ON tasks (organization_id, project_id, status)")
    op.execute("CREATE INDEX ix_tasks_assignee ON tasks (assignee_user_id, status, due_date) "
               "WHERE assignee_user_id IS NOT NULL")
    op.execute("ALTER TABLE tasks ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON tasks USING ({_RULE}) WITH CHECK ({_RULE})")

    op.execute("""
        CREATE TABLE task_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            kind text NOT NULL,
            from_status text,
            to_status text,
            text text,
            media_object_key text,
            changes jsonb,
            actor_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
            source text NOT NULL DEFAULT 'web',
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_task_events_kind CHECK (kind IN ('created', 'changed', 'status', 'comment')),
            CONSTRAINT ck_task_events_source CHECK (source IN ('web', 'whatsapp'))
        )""")
    op.execute("CREATE INDEX ix_task_events_task ON task_events (task_id, created_at)")
    op.execute("ALTER TABLE task_events ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON task_events USING ({_RULE}) WITH CHECK ({_RULE})")

    op.execute("""
        CREATE TABLE tasks_switched_on_0533 (
            organization_id uuid PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
            switched_on_at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("ALTER TABLE tasks_switched_on_0533 ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON tasks_switched_on_0533 USING ({_RULE}) WITH CHECK ({_RULE})")
    op.execute("""
        INSERT INTO tasks_switched_on_0533 (organization_id)
        SELECT organization_id FROM organization_settings
         WHERE key = 'enabled_modules'
           AND jsonb_typeof(value) = 'array'
           AND NOT value @> '["tasks"]'::jsonb""")
    op.execute("""
        UPDATE organization_settings s
           SET value = s.value || '["tasks"]'::jsonb, updated_at = now()
          FROM tasks_switched_on_0533 f
         WHERE s.organization_id = f.organization_id AND s.key = 'enabled_modules'""")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM tasks) THEN "
               "RAISE EXCEPTION 'Tasks exist; downgrading would lose them'; END IF; END $$")
    op.execute("""
        UPDATE organization_settings s
           SET value = COALESCE(
                   (SELECT jsonb_agg(m) FROM jsonb_array_elements(s.value) m WHERE m <> '"tasks"'::jsonb),
                   '[]'::jsonb),
               updated_at = now()
          FROM tasks_switched_on_0533 f
         WHERE s.organization_id = f.organization_id AND s.key = 'enabled_modules'""")
    op.execute("DROP TABLE IF EXISTS tasks_switched_on_0533")
    op.execute("DROP TABLE IF EXISTS task_events")
    op.execute("DROP TABLE IF EXISTS tasks")
