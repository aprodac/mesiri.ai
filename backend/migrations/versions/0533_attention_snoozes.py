"""Attention snoozes (GM-04): "not now" on one alert, per person, until a day.

``attention_snoozes``: one row per person and alert key (the key names the thing, e.g. ``issue:<id>``,
``late:<activity id>``). Snoozed until ``until`` (the company's date): after it, if the thing is still true, the
alert is back. Nothing else reads it. Additive; tenant row-level security like 0531. Downgrade drops the table
(snoozes only).

Revision ID: 0533
Revises: 0532
Create Date: 2026-11-09
"""

from __future__ import annotations

from alembic import op

revision = "0533"
down_revision = "0532"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE attention_snoozes (
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key text NOT NULL,
            until date NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, key)
        )""")
    op.execute("CREATE INDEX ix_attention_snoozes_org ON attention_snoozes (organization_id)")
    op.execute("ALTER TABLE attention_snoozes ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON attention_snoozes USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS attention_snoozes")
