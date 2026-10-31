"""Switch the v2 materials agent on for the two test companies (request [176], Phase C of [174]).

`assistant_mode` is a company setting (classic | v2_shadow | v2_materials). Only
"Mesiri Test Builders" and the Paraclette test company move to "v2_materials";
every other company stays classic. The control panel has no button for this
setting, so it is set here.

Paraclette is matched by name ILIKE '%paraclet%' and is touched only when that
matches exactly ONE organization (never guess). Test Builders is matched by its
exact name.

Additive and idempotent: upsert of one settings row per target company.
Downgrade: Test Builders goes back to "agent" (the 0485 value, which reads as
classic); Paraclette's row is removed (unset reads as classic). Only rows that
still hold "v2_materials" are changed, so a later manual change is left alone.

Revision ID: 0495
Revises: 0494
Create Date: 2026-10-31
"""

from __future__ import annotations

from alembic import op

revision = "0495"
down_revision = "0494"
branch_labels = None
depends_on = None

_TARGETS = """
    SELECT o.id FROM organizations o WHERE o.name = 'Mesiri Test Builders'
    UNION ALL
    SELECT o.id FROM organizations o
    WHERE o.name ILIKE '%paraclet%'
      AND (SELECT count(*) FROM organizations p WHERE p.name ILIKE '%paraclet%') = 1
"""


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO organization_settings (id, organization_id, key, value)
        SELECT gen_random_uuid(), t.id, 'assistant_mode', '"v2_materials"'::jsonb
        FROM ({_TARGETS}) t
        ON CONFLICT (organization_id, key) DO UPDATE SET value = EXCLUDED.value
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE organization_settings s SET value = '"agent"'::jsonb
        FROM organizations o
        WHERE s.organization_id = o.id AND o.name = 'Mesiri Test Builders'
          AND s.key = 'assistant_mode' AND s.value = '"v2_materials"'::jsonb
        """
    )
    op.execute(
        """
        DELETE FROM organization_settings s
        USING organizations o
        WHERE s.organization_id = o.id AND o.name ILIKE '%paraclet%'
          AND o.name <> 'Mesiri Test Builders'
          AND (SELECT count(*) FROM organizations p WHERE p.name ILIKE '%paraclet%') = 1
          AND s.key = 'assistant_mode' AND s.value = '"v2_materials"'::jsonb
        """
    )
