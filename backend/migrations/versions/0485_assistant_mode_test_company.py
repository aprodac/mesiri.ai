"""Switch the assistant agent on for the Mesiri test company (request [40]).

`assistant_mode` is a company setting (default "off", so every other company
keeps the classic pipeline). The agent is first tried on "Mesiri Test Builders"
only; the owner decides when real companies switch, from the control panel.

Additive and idempotent: one settings row for the company when it exists, and
nothing when it does not (a fresh database) or the row is already there.
Downgrade removes only the row this migration added ("agent" for that
company); a value someone has since changed is left alone.

Revision ID: 0485
Revises: 0484
Create Date: 2026-10-19
"""

from __future__ import annotations

from alembic import op

revision = "0485"
down_revision = "0484"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO organization_settings (id, organization_id, key, value)
        SELECT gen_random_uuid(), o.id, 'assistant_mode', '"agent"'::jsonb
        FROM organizations o
        WHERE o.name = 'Mesiri Test Builders'
        ON CONFLICT (organization_id, key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM organization_settings s
        USING organizations o
        WHERE s.organization_id = o.id
          AND o.name = 'Mesiri Test Builders'
          AND s.key = 'assistant_mode'
          AND s.value = '"agent"'::jsonb
        """
    )
