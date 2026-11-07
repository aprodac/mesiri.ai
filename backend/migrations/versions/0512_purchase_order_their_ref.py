"""Purchase orders: their own reference (PRC-30).

The number the order also goes by outside Mesiri: the company's paper PO, the supplier's quote or proforma number,
a Tally voucher. Kept beside Mesiri's PO-0001, searchable, never replacing it (DECISIONS 7 Nov: both ways, never
locked in).

Additive only: one nullable column.

Revision ID: 0512
Revises: 0511
Create Date: 2026-11-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0512"
down_revision = "0511"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_orders", sa.Column("their_ref", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("purchase_orders", "their_ref")
