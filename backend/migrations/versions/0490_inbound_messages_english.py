"""WEB-37: keep a voice note's English next to its words.

The speech step returns a voice note's words, their language and an English
translation in one call; the words were kept (inbound_messages.body_text)
and the English was thrown away. The Live report shows a message being read
-- the Malayalam, then the English, then what was taken from it -- so the
English is kept now, in a new nullable column. Additive: nothing is
rewritten, existing rows stay NULL; the downgrade drops the column.

Revision ID: 0490
Revises: 0489
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0490"
down_revision = "0489"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inbound_messages", sa.Column("body_text_en", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("inbound_messages", "body_text_en")
