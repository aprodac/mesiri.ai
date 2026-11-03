"""users.reply_language: the language a person always gets WhatsApp replies in (WA-169).

A person who says "always reply in Manglish" gets Manglish whatever they write in next (English,
Malayalam script, a site name). Before this, the choice lived only in Redis (classic) and v3
decided the language from every message. NULL = follow each message (as before).

Additive: one nullable column with a check on its values. Downgrade drops it (the choices made
since are lost; replies go back to following each message).

Revision ID: 0501
Revises: 0500
Create Date: 2026-11-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0501"
down_revision = "0500"
branch_labels = None
depends_on = None

#: Kept in step with mesiri.domains.identity.preferences_router.REPLY_LANGUAGES.
_VALUES = ("english", "manglish", "malayalam", "hindi", "hinglish")


def upgrade() -> None:
    op.add_column("users", sa.Column("reply_language", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        "ck_users_reply_language",
        "users",
        "reply_language IS NULL OR reply_language IN (" + ", ".join(f"'{v}'" for v in _VALUES) + ")",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_reply_language", "users", type_="check")
    op.drop_column("users", "reply_language")
