"""sandbox_played: what a learning sample company's planned simulation has played (SS-74c, guided demo).

docs/plans/guided-demo-plan.md section 18: the plan (application/learn/sample_plan.py) is played day by day as each
role's sandbox user. This table remembers, per sample company, what became of each plan entry, so a later entry finds
the real record it needs (a delivery its order line, a payment its bills) and the person's own entries can be ticked.

    organization_id   the sample company (cascades: removing it removes this)
    entry_id          the plan entry (``d07-order-tower_a``)
    day               the plan day it belongs to
    status            played (by the cast) | done (by the person) | failed
    by_role           who made it
    record            the ids it made, for the entries that need them
    error             why it failed (failed only)

Also ``organizations.sandbox_day0``: the date of the plan's day 0 for that sample (NULL for every real company, and
for a sample made before this: those can't play days until they start over).

Additive: a new table (row-level security like every company table) and one nullable column.

Revision ID: 0559
Revises: 0558
Create Date: 2026-11-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0559"
down_revision = "0558"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.add_column("organizations", sa.Column("sandbox_day0", sa.Date(), nullable=True))
    op.create_table(
        "sandbox_played",
        sa.Column("organization_id", sa.UUID(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_id", sa.Text(), nullable=False),
        sa.Column("day", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("by_role", sa.Text(), nullable=True),
        sa.Column("record", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "entry_id"),
        sa.CheckConstraint("status IN ('played', 'done', 'failed')", name="ck_sandbox_played_status"),
    )
    op.execute("ALTER TABLE sandbox_played ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON sandbox_played USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.drop_table("sandbox_played")
    op.drop_column("organizations", "sandbox_day0")
