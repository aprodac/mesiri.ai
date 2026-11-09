"""Company activity log (ADM-01, decided in session by Ilan 9 Nov 2026; module 22 of the capability framework).

Who changed what, when, for the company's owner and admins. One row per successful change made through the API
(POST, PUT, PATCH, DELETE with a login), written by one recorder (``mesiri.http.activity``) on the dashboard, the
production app and the WhatsApp assistant's API, so every module is covered without code in each. Additive only:

- ``activity_log``: the actor (user id; name and role as they were), the source (``web`` / ``whatsapp``), the
  method and route template, the action in words, the record (kind, id, ref or name from the reply), the ids in the
  path, the status, when. No request bodies: amounts, phone numbers and notes stay in their own tables.

Never updated or deleted by the app. Tenant row-level security like 0533. Downgrade drops it (a log, no record
depends on it).

Revision ID: 0536
Revises: 0535
Create Date: 2026-11-09
"""

from __future__ import annotations

from alembic import op

revision = "0536"
down_revision = "0535"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE activity_log (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            actor_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
            actor_name text,
            actor_role text,
            source text NOT NULL DEFAULT 'web',
            method text NOT NULL,
            route text NOT NULL,
            action text NOT NULL,
            record_kind text,
            record_id text,
            record_label text,
            path_ids jsonb NOT NULL DEFAULT '{}'::jsonb,
            status_code integer NOT NULL,
            correlation_id text,
            at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_activity_log_source CHECK (source IN ('web', 'whatsapp')),
            CONSTRAINT ck_activity_log_method CHECK (method IN ('POST', 'PUT', 'PATCH', 'DELETE'))
        )""")
    op.execute("CREATE INDEX ix_activity_log_org_at ON activity_log (organization_id, at DESC)")
    op.execute("CREATE INDEX ix_activity_log_org_actor_at ON activity_log (organization_id, actor_user_id, at DESC)")
    op.execute("ALTER TABLE activity_log ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON activity_log USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DROP TABLE activity_log")
