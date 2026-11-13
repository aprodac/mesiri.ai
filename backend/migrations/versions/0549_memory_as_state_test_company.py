"""Memory as state on for the test company (WA-270 step 4; asked in session, 13 Nov 2026, for the live round).

`memory_as_state` = "on": the WhatsApp assistant gives the model the code's state block (today per site, the card,
what waits, what was cancelled and saved) and today's last 6 messages, in place of the day's chat replayed
(apps/whatsapp-assistant/src/agent_api/state_block.py). Only "Mesiri Test Builders" changes; every other company
keeps the default ("off").

Additive and idempotent: an upsert of one settings row. The assistant reads the setting every 10 minutes.
Downgrade: the row is removed (back to the default), only while it still holds "on", so a later manual change is
left alone. To turn it off without a migration: the control panel's settings, `memory_as_state` = "off".

Revision ID: 0549
Revises: 0548
Create Date: 2026-11-13
"""

from __future__ import annotations

from alembic import op

revision = "0549"
down_revision = "0548"
branch_labels = None
depends_on = None

_TARGETS = "SELECT o.id FROM organizations o WHERE o.name = 'Mesiri Test Builders'"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO organization_settings (id, organization_id, key, value)
        SELECT gen_random_uuid(), t.id, 'memory_as_state', '"on"'::jsonb
        FROM ({_TARGETS}) t
        ON CONFLICT (organization_id, key) DO UPDATE SET value = EXCLUDED.value
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM organization_settings
        WHERE key = 'memory_as_state' AND value = '"on"'::jsonb
          AND organization_id IN ({_TARGETS})
        """
    )
