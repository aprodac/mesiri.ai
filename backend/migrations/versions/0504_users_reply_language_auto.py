"""users.reply_language may be "auto" (WA-207).

5 Nov 2026 (set in session): every person gets Manglish replies unless they choose otherwise, so no
choice (NULL) now means Manglish. "Reply in my language again" (follow each message) needs its own
value: "auto", which the check did not allow.

Additive: the check is widened by one value; no row is changed. Downgrade turns "auto" back into
NULL (what it meant before this) and restores the old check.

Revision ID: 0504
Revises: 0503
Create Date: 2026-11-05
"""

from __future__ import annotations

from alembic import op

revision = "0504"
down_revision = "0503"
branch_labels = None
depends_on = None

_OLD = ("english", "manglish", "malayalam", "hindi", "hinglish")
_NEW = (*_OLD, "auto")


def _check(values: tuple[str, ...]) -> str:
    return "reply_language IS NULL OR reply_language IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_users_reply_language", "users", type_="check")
    op.create_check_constraint("ck_users_reply_language", "users", _check(_NEW))


def downgrade() -> None:
    op.execute("UPDATE users SET reply_language = NULL WHERE reply_language = 'auto'")
    op.drop_constraint("ck_users_reply_language", "users", type_="check")
    op.create_check_constraint("ck_users_reply_language", "users", _check(_OLD))
