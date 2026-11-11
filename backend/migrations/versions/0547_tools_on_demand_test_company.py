"""Tools on demand on for the test company (WA-277 step E; Ilan, 11 Nov 2026, in session: "can't you turn on").

`tools_on_demand` = "on": the WhatsApp assistant sends the model its everyday tools and opens the rest by area
(apps/whatsapp-assistant/src/agent_api/tool_areas.py). Only "Mesiri Test Builders" changes; every other company
keeps the default ("off").

Additive and idempotent: an upsert of one settings row. The assistant reads the setting every 10 minutes.
Downgrade: the row is removed (back to the default), only while it still holds "on", so a later manual change is
left alone. To turn it off without a migration: the control panel's settings, `tools_on_demand` = "off".

Revision ID: 0547
Revises: 0546
Create Date: 2026-11-11
"""

from __future__ import annotations

from alembic import op

revision = "0547"
down_revision = "0546"
branch_labels = None
depends_on = None

_TARGETS = "SELECT o.id FROM organizations o WHERE o.name = 'Mesiri Test Builders'"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO organization_settings (id, organization_id, key, value)
        SELECT gen_random_uuid(), t.id, 'tools_on_demand', '"on"'::jsonb
        FROM ({_TARGETS}) t
        ON CONFLICT (organization_id, key) DO UPDATE SET value = EXCLUDED.value
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM organization_settings
        WHERE key = 'tools_on_demand' AND value = '"on"'::jsonb
          AND organization_id IN ({_TARGETS})
        """
    )
