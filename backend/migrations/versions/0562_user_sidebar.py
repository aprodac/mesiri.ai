"""users.sidebar: the person's own sidebar (UX-65).

Pinned pages ("Your pages") in their order, the order of the sidebar's sections and the sections they hid. NULL means
they never changed it: the dashboard shows their role's default. Only the person reads or writes it
(``/me/preferences``, ``PUT /me/sidebar``); it changes what the sidebar shows, never what they may open.

Additive: one nullable column, no row is rewritten. Downgrade drops the column (a person's choices go back to their
role's default).

Revision ID: 0562
Revises: 0561
Create Date: 2026-11-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0562"
down_revision = "0561"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("sidebar", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "sidebar")
