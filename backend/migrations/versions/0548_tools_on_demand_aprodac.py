"""Tools on demand on for Aprodac, the team's own demo company (WA-277 step E; asked in session, 11 Nov 2026,
so Ilan can test the upgrade from his own company).

`tools_on_demand` = "on", as 0547 did for Mesiri Test Builders. Only "Aprodac" changes; every other company keeps
what it has.

Additive and idempotent: an upsert of one settings row. The assistant reads the setting every 10 minutes.
Downgrade: the row is removed (back to the default), only while it still holds "on", so a later manual change is
left alone.

Revision ID: 0548
Revises: 0547
Create Date: 2026-11-11
"""

from __future__ import annotations

from alembic import op

revision = "0548"
down_revision = "0547"
branch_labels = None
depends_on = None

_TARGETS = "SELECT o.id FROM organizations o WHERE o.name = 'Aprodac'"


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
