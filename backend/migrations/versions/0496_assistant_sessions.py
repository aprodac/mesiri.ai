"""Assistant conversation memory for v2 on ADK (request 185).

One row in ``assistant_sessions`` per person per day (an ADK session: app, ``<org>:<user>``,
``YYYY-MM-DD``); ``assistant_session_events`` holds every event of it in order (what they said,
tool calls and results, Mesiri's reply as sent), as ADK's own JSON. Read and written only by
``agent_v2/adk/memory.py`` for companies whose ``assistant_mode`` is ``v2_adk``; for everyone
else both tables stay empty.

Additive only: two new tables, nothing existing changes. Row-level security as every company
table has it (0484). Deleting a company or a user deletes its conversations (cascade).

Revision ID: 0496
Revises: 0495
Create Date: 2026-10-31
"""

from __future__ import annotations

from alembic import op

revision = "0496"
down_revision = "0495"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE assistant_sessions (
            app_name text NOT NULL,
            user_id text NOT NULL,
            session_id text NOT NULL,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            state jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (app_name, user_id, session_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE assistant_session_events (
            seq bigserial PRIMARY KEY,
            app_name text NOT NULL,
            user_id text NOT NULL,
            session_id text NOT NULL,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            event_id text NOT NULL,
            invocation_id text,
            author text,
            timestamp double precision NOT NULL,
            event jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (app_name, user_id, session_id)
                REFERENCES assistant_sessions (app_name, user_id, session_id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_assistant_session_events_session "
        "ON assistant_session_events (app_name, user_id, session_id, seq)"
    )
    op.execute("CREATE INDEX ix_assistant_sessions_org ON assistant_sessions (organization_id, updated_at)")
    for table in ("assistant_sessions", "assistant_session_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS assistant_session_events")
    op.execute("DROP TABLE IF EXISTS assistant_sessions")
