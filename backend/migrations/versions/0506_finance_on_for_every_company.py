"""Finance is on for every company (Ilan, 5 Nov 2026: "by default turn finance on for everyone").

The code default (`settings.DEFAULT_ENABLED_MODULES`) now includes finance, so a company whose modules were
never set gets it. This migration adds finance to every company whose module list is already stored without it.
The companies it changes are written to `finance_switched_on_0506`, so a downgrade takes finance away from
exactly those and from no one else. A company can still be switched off afterwards from the control panel.

Rewrites stored settings for the changed companies only (approved in session by Ilan, 5 Nov 2026); additive
otherwise.

Revision ID: 0506
Revises: 0505
Create Date: 2026-11-05
"""

from __future__ import annotations

from alembic import op

revision = "0506"
down_revision = "0505"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE finance_switched_on_0506 (
            organization_id uuid PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
            switched_on_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE finance_switched_on_0506 ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON finance_switched_on_0506 USING ({_RULE}) WITH CHECK ({_RULE})")
    op.execute(
        """
        INSERT INTO finance_switched_on_0506 (organization_id)
        SELECT organization_id FROM organization_settings
         WHERE key = 'enabled_modules'
           AND jsonb_typeof(value) = 'array'
           AND NOT value @> '["finance"]'::jsonb
        """
    )
    op.execute(
        """
        UPDATE organization_settings s
           SET value = s.value || '["finance"]'::jsonb, updated_at = now()
          FROM finance_switched_on_0506 f
         WHERE s.organization_id = f.organization_id AND s.key = 'enabled_modules'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE organization_settings s
           SET value = COALESCE(
                   (SELECT jsonb_agg(m) FROM jsonb_array_elements(s.value) m WHERE m <> '"finance"'::jsonb),
                   '[]'::jsonb),
               updated_at = now()
          FROM finance_switched_on_0506 f
         WHERE s.organization_id = f.organization_id AND s.key = 'enabled_modules'
        """
    )
    op.execute("DROP TABLE IF EXISTS finance_switched_on_0506")
