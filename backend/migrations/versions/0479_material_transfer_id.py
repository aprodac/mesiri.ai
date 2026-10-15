"""BE-32: link the two halves of a material transfer between sites.

A transfer is a TRANSFER_OUT outflow at the sending site and a TRANSFER_IN
inflow at the receiving one -- both reasons exist since 0270, but were
entered separately and nothing tied them together, so a transfer could be
half-recorded, could not be listed as one movement, and could not be
corrected as one. `transfer_id` is the shared id both rows carry, set only
by POST /materials/transfers, which writes both in one transaction.

No new table: the two rows already hold everything a transfer is
(material, unit, quantity, date, who, which sites). Nullable, since every
row before this and every non-transfer row has none.

Revision ID: 0479
Revises: 0478
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0479"
down_revision = "0478"
branch_labels = None
depends_on = None

_TABLES = ("material_receipts", "material_usage")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("transfer_id", sa.UUID(as_uuid=True), nullable=True))
        op.create_index(
            f"ix_{table}_transfer_id",
            table,
            ["transfer_id"],
            postgresql_where=sa.text("transfer_id IS NOT NULL"),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"ix_{table}_transfer_id", table_name=table)
        op.drop_column(table, "transfer_id")
