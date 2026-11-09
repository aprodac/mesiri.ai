"""Morning brief switch (GM-08, with TSK-05): each person may turn their 8 am WhatsApp brief off.

``users.morning_brief`` (boolean, on by default): the person's own switch, read by the reminder pass and set through
``PUT /me/morning-brief`` (and the assistant). Additive; existing people get the default. Downgrade drops it.

Revision ID: 0538
Revises: 0537
Create Date: 2026-11-09
"""

from __future__ import annotations

from alembic import op

revision = "0538"
down_revision = "0537"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN morning_brief boolean NOT NULL DEFAULT true")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS morning_brief")
