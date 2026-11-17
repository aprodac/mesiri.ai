"""sandbox_days: save points of a learning sample company, one per game day (SS-74d, guided demo).

docs/plans/guided-demo-plan.md sections 18.5 and 18.12: the person can go back to the start of any of the last 30 days
of their sample company (and "try today again"). Each save point is every row the sample company has, per table, as
JSON, gzip-compressed (application/learn/sandbox_days.py).

    organization_id   the sample company (cascades: removing it removes its save points)
    day               the plan day the save point starts
    on_date           the sample company's date on that day
    data              gzip of {table: [rows]}
    saved_at          when it was saved

Additive: a new table, with row-level security like every company table.

Revision ID: 0560
Revises: 0559
Create Date: 2026-11-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0560"
down_revision = "0559"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.create_table(
        "sandbox_days",
        sa.Column("organization_id", sa.UUID(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Integer(), nullable=False),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "day"),
    )
    op.execute("ALTER TABLE sandbox_days ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON sandbox_days USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.drop_table("sandbox_days")
