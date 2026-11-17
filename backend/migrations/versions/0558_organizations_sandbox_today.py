"""organizations.sandbox_today: a learning sample company's own date (SS-74a, guided demo).

docs/plans/guided-demo-plan.md section 18.5: a sample company lives on the day its planned simulation is at, which
moves only when the person presses Next day or goes back; every real company lives on the real date. The date reaches
the code through the sample company's token (domains/shared/clock.py); this column is where it is kept.

    sandbox_today   the sample company's date; NULL for every real company (and the real date is used)

Additive: one nullable column; no existing row changes. Downgrade drops it (sample companies then use the real date).

Revision ID: 0558
Revises: 0557
Create Date: 2026-11-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0558"
down_revision = "0557"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("sandbox_today", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "sandbox_today")
