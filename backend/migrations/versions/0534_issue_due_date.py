"""Issue due date (GM-06): by when the person on an issue said it would be sorted.

``site_issues.due_on`` (nullable date). The owner is the existing ``assigned_user_id``. Additive; nothing existing is
rewritten. Downgrade drops the column.

Revision ID: 0534
Revises: 0533
Create Date: 2026-11-09
"""

from __future__ import annotations

from alembic import op

revision = "0534"
down_revision = "0533"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE site_issues ADD COLUMN due_on date")


def downgrade() -> None:
    op.execute("ALTER TABLE site_issues DROP COLUMN IF EXISTS due_on")
