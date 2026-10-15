"""SS-06 / WEB-12: one-time codes sent on WhatsApp to log in or sign up.

`login_codes` -- one row per code sent. The code itself is never stored, only
an HMAC of it (application/identity/login_codes.py). A code is good for one
use, for a few minutes, and a few wrong tries; `attempts` and `consumed_at`
are what enforce that, which is why this is a table and not a signed token.
Rows are also the per-number send log the resend limits are counted from.

`phone` is digits with the country code (the WhatsApp id form), `purpose`
is `login` or `signup`. Nothing references a user: a signup code exists
before its user does, and a login code is logged even for a number nobody
has, so the limits look the same either way.

Revision ID: 0476
Revises: 0475
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0476"
down_revision = "0475"
branch_labels = None
depends_on = None

_PURPOSES = ("login", "signup")


def upgrade() -> None:
    if "login_codes" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "login_codes",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose IN (" + ", ".join(f"'{p}'" for p in _PURPOSES) + ")",
            name="ck_login_codes_purpose",
        ),
    )
    op.create_index(
        "ix_login_codes_phone_purpose_created",
        "login_codes",
        ["phone", "purpose", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_login_codes_phone_purpose_created", table_name="login_codes")
    op.drop_table("login_codes")
