"""Accounts joins V1: on for every company (Ilan, 20 Nov 2026: "We are changing what V1 is, okay, let it be on for
everything. V1 is bigger now").

Data only, additive: ``accounts`` is added to ``organization_settings.enabled_modules`` where that list is stored and
lacks it, recorded in ``accounts_switched_on_0563`` so the downgrade takes it off exactly there (as 0518, 0521 and
0533 did). A company with no stored list gets V1, which now includes accounts (domains/organizations/settings.py).
Nothing else is needed: the books follow the records (domains/accounts/sweep.py builds the chart and posts on the first
read), so a company switched on today sees its books from its existing expenses, bills, payments and wages.

Revision ID: 0563
Revises: 0562
Create Date: 2026-11-20
"""

from __future__ import annotations

from alembic import op

revision = "0563"
down_revision = "0562"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE accounts_switched_on_0563 (
            organization_id uuid PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
            switched_on_at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("ALTER TABLE accounts_switched_on_0563 ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON accounts_switched_on_0563 USING ({_RULE}) WITH CHECK ({_RULE})")
    op.execute("""
        INSERT INTO accounts_switched_on_0563 (organization_id)
        SELECT organization_id FROM organization_settings
         WHERE key = 'enabled_modules'
           AND jsonb_typeof(value) = 'array'
           AND NOT value @> '["accounts"]'::jsonb""")
    op.execute("""
        UPDATE organization_settings s
           SET value = s.value || '["accounts"]'::jsonb, updated_at = now()
          FROM accounts_switched_on_0563 f
         WHERE s.organization_id = f.organization_id AND s.key = 'enabled_modules'""")


def downgrade() -> None:
    op.execute("""
        UPDATE organization_settings s
           SET value = COALESCE(
                   (SELECT jsonb_agg(m) FROM jsonb_array_elements(s.value) m WHERE m <> '"accounts"'::jsonb),
                   '[]'::jsonb),
               updated_at = now()
          FROM accounts_switched_on_0563 f
         WHERE s.organization_id = f.organization_id AND s.key = 'enabled_modules'""")
    op.execute("DROP TABLE IF EXISTS accounts_switched_on_0563")
