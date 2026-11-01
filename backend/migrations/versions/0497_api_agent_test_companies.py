"""Switch the API agent on for the two test companies (WA-121; Ilan, 1 Nov: "both test companies").

`assistant_mode` = "api": one model + one SOP + the dashboard's own API as tools
(apps/whatsapp-assistant/src/agent_api). Only "Mesiri Test Builders" and the
Paraclette test company move; every other company is unchanged. Same targets
and matching as 0495 (Paraclette by name ILIKE '%paraclet%' only when exactly ONE
organization matches; never guess).

Additive and idempotent: upsert of one settings row per target company.
Downgrade: back to "v2" (what 0495 set; "v2_materials" reads as "v2"), only for
rows that still hold "api", so a later manual change is left alone.

Revision ID: 0497
Revises: 0496
Create Date: 2026-11-01
"""

from __future__ import annotations

from alembic import op

revision = "0497"
down_revision = "0496"
branch_labels = None
depends_on = None

_TARGETS = """
    SELECT o.id FROM organizations o WHERE o.name = 'Mesiri Test Builders'
    UNION
    SELECT o.id FROM organizations o
    WHERE o.name ILIKE '%paraclet%'
      AND (SELECT count(*) FROM organizations p WHERE p.name ILIKE '%paraclet%') = 1
"""


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO organization_settings (id, organization_id, key, value)
        SELECT gen_random_uuid(), t.id, 'assistant_mode', '"api"'::jsonb
        FROM ({_TARGETS}) t
        ON CONFLICT (organization_id, key) DO UPDATE SET value = EXCLUDED.value
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE organization_settings SET value = '"v2"'::jsonb
        WHERE key = 'assistant_mode' AND value = '"api"'::jsonb
          AND organization_id IN ({_TARGETS})
        """
    )
