"""BE-14: the site day's conditions -- weather, hours lost, whether the site
worked, and tomorrow's plan.

Stored on the SITE-level `daily_reports` row (the site's working day, BE-08)
while the day is open, and copied into each version's payload when one is
built, so a confirmed DPR keeps the values it was confirmed with (P7).

All nullable: "not set" is a real state the DPR shows ("Weather not set"),
not something to default away. `weather` and `site_working` are plain
strings checked by the API rather than Postgres enums -- the list of
weather words is a product choice likely to grow, and an enum would need a
migration (and a type rebuild to shrink) every time.

Revision ID: 0468
Revises: 0467
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0468"
down_revision = "0467"
branch_labels = None
depends_on = None

def _columns() -> list[sa.Column]:
    return [
        sa.Column("weather", sa.String(), nullable=True),
        sa.Column("hours_lost", sa.Numeric(4, 1), nullable=True),
        # full | half | none
        sa.Column("site_working", sa.String(), nullable=True),
        sa.Column("tomorrow_plan", sa.Text(), nullable=True),
    ]


def upgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("daily_reports")}
    for column in _columns():
        if column.name not in existing:
            op.add_column("daily_reports", column)


def downgrade() -> None:
    for column in reversed(_columns()):
        op.drop_column("daily_reports", column.name)
