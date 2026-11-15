"""users.start_mode and users.guide_seen: how Mesiri guides a person (SS-27, guided onboarding).

``start_mode`` is the person's answer to "How would you like to start?": ``guided`` (step by step),
``bring_data`` (help me bring my Excel in), ``switching`` (I've used other construction software) or
``free`` (no tips). NULL = not answered yet; the code reads that as ``guided`` for a new person and
``free`` for someone who was already using Mesiri (docs/plans/guided-onboarding-plan.md section 6.1).

``guide_seen`` holds, per dashboard page, the version of its guide the person closed
(``{"/today": 1}``), so a first-visit strip shows once and comes back once when the page changes.

Additive: two columns, no existing row rewritten. Downgrade drops them (answers and closed strips are
lost; everyone is treated as not asked again).

Revision ID: 0553
Revises: 0552
Create Date: 2026-11-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0553"
down_revision = "0552"
branch_labels = None
depends_on = None

#: Kept in step with mesiri.domains.identity.preferences_router.START_MODES.
_VALUES = ("guided", "bring_data", "switching", "free")


def upgrade() -> None:
    op.add_column("users", sa.Column("start_mode", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        "ck_users_start_mode",
        "users",
        "start_mode IS NULL OR start_mode IN (" + ", ".join(f"'{v}'" for v in _VALUES) + ")",
    )
    op.add_column(
        "users",
        sa.Column("guide_seen", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("users", "guide_seen")
    op.drop_constraint("ck_users_start_mode", "users", type_="check")
    op.drop_column("users", "start_mode")
