"""users.start_mode: allow ``new_to_construction`` (UX-22).

A fifth answer to "How would you like to start?": new to construction too, so the dashboard's help and page tours
explain the site itself (what a BOQ line, a cum, a margin is), not only where things are.

Additive: the check constraint gets one more allowed value; no row is rewritten. Downgrade moves anyone who chose it
back to ``guided`` (the nearest answer) before putting the old check back.

Revision ID: 0555
Revises: 0554
Create Date: 2026-11-17
"""

from __future__ import annotations

from alembic import op

revision = "0555"
down_revision = "0554"
branch_labels = None
depends_on = None

#: Kept in step with mesiri.domains.identity.preferences_router.START_MODES.
_VALUES = ("new_to_construction", "guided", "bring_data", "switching", "free")
_OLD = ("guided", "bring_data", "switching", "free")


def _check(values: tuple[str, ...]) -> str:
    return "start_mode IS NULL OR start_mode IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.drop_constraint("ck_users_start_mode", "users", type_="check")
    op.create_check_constraint("ck_users_start_mode", "users", _check(_VALUES))


def downgrade() -> None:
    op.execute("UPDATE users SET start_mode = 'guided' WHERE start_mode = 'new_to_construction'")
    op.drop_constraint("ck_users_start_mode", "users", type_="check")
    op.create_check_constraint("ck_users_start_mode", "users", _check(_OLD))
