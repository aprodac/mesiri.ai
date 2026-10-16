"""One WhatsApp number = one person, enforced on the number's digits (BE-04).

ix_users_whatsapp_number (0020) only blocks identical text, so "+91 98765
43210" and "919876543210" could be saved as two people. Inbound messages find
their sender by digits, and report recording took whichever row came first.

Adds ux_users_whatsapp_digits: unique on the digits, ignoring rows with no
number or no digits. ix_users_whatsapp_digits (0482) stays: its predicate
matches the sender lookup exactly, so the planner keeps using it.

Stops with the clashing numbers listed (no names) if any already exist: they
need a person to decide which row keeps the number.

Revision ID: 0483
Revises: 0482
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0483"
down_revision = "0482"
branch_labels = None
depends_on = None

_DIGITS = "regexp_replace(whatsapp_number, '\\D', '', 'g')"


def upgrade() -> None:
    clashes = (
        op.get_bind()
        .execute(
            sa.text(
                f"SELECT {_DIGITS} AS digits, count(*) AS n FROM users "
                f"WHERE whatsapp_number IS NOT NULL AND {_DIGITS} <> '' "
                f"GROUP BY 1 HAVING count(*) > 1 ORDER BY 1"
            )
        )
        .all()
    )
    if clashes:
        listed = ", ".join(f"{r.digits} ({r.n} users)" for r in clashes)
        raise RuntimeError(
            "BE-04: these WhatsApp numbers belong to more than one user; "
            f"clear the number on all but one of each, then re-run: {listed}"
        )
    op.execute(
        f"CREATE UNIQUE INDEX ux_users_whatsapp_digits ON users ({_DIGITS}) "
        f"WHERE whatsapp_number IS NOT NULL AND {_DIGITS} <> ''"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_users_whatsapp_digits")
