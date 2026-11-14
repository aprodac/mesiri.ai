"""Live's ready messages on for the test company (asked in session, 14 Nov 2026).

`live_ready_messages` = true: Live's "Stories" (the demo deck and the test list, one ready message for every kind of
message Live shows) is offered to "Mesiri Test Builders", which is not a demo company (no one-tap reset). Each message
sent is a real entry, which is what the test company is for. Every other company keeps the default (false).

Additive and idempotent: an upsert of one settings row. Downgrade: the row is removed, only while it still holds
true, so a later manual change is left alone. Off again without a migration: the control panel's settings,
`live_ready_messages` = false.

Revision ID: 0550
Revises: 0549
Create Date: 2026-11-14
"""

from __future__ import annotations

from alembic import op

revision = "0550"
down_revision = "0549"
branch_labels = None
depends_on = None

_TARGETS = "SELECT o.id FROM organizations o WHERE o.name = 'Mesiri Test Builders'"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO organization_settings (id, organization_id, key, value)
        SELECT gen_random_uuid(), t.id, 'live_ready_messages', 'true'::jsonb
        FROM ({_TARGETS}) t
        ON CONFLICT (organization_id, key) DO UPDATE SET value = EXCLUDED.value
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM organization_settings
        WHERE key = 'live_ready_messages' AND value = 'true'::jsonb
          AND organization_id IN ({_TARGETS})
        """
    )
