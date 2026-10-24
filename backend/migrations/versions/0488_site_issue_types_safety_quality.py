"""Request 104: two more site issue types -- SAFETY and QUALITY.

"Worker fell from scaffolding, minor injury" and "Water leakage in the 2nd floor
bathroom" were filed as OTHER (audit ISS-11). The WhatsApp assistant now files
them as SAFETY ("Safety / accident") and QUALITY ("Leakage / quality").

Additive only: two enum values are added; no row is touched. Enum values are
added but not used in this transaction (PG 12+ allows that; same posture as
0460 and 0466).

Revision ID: 0488
Revises: 0487
"""

from __future__ import annotations

from alembic import op

revision = "0488"
down_revision = "0487"
branch_labels = None
depends_on = None

_ENUM = "site_issue_type"


def upgrade() -> None:
    op.execute(f"ALTER TYPE {_ENUM} ADD VALUE IF NOT EXISTS 'SAFETY'")
    op.execute(f"ALTER TYPE {_ENUM} ADD VALUE IF NOT EXISTS 'QUALITY'")


def downgrade() -> None:
    # Postgres cannot drop an enum value, so the type is rebuilt (0460's
    # pattern). Issues filed under the two new types fold back into OTHER.
    prior = (
        "WEATHER",
        "MATERIAL_SHORTAGE",
        "LABOUR_SHORTAGE",
        "DRAWING_PENDING",
        "EQUIPMENT_BREAKDOWN",
        "INSPECTION_WAITING",
        "ACCESS",
        "OTHER",
    )
    op.execute(f"ALTER TYPE {_ENUM} RENAME TO {_ENUM}_old")
    values = ", ".join(f"'{v}'" for v in prior)
    op.execute(f"CREATE TYPE {_ENUM} AS ENUM ({values})")
    op.execute("UPDATE site_issues SET issue_type = 'OTHER' WHERE issue_type IN ('SAFETY', 'QUALITY')")
    op.execute(
        f"ALTER TABLE site_issues ALTER COLUMN issue_type TYPE {_ENUM} "
        f"USING issue_type::text::{_ENUM}"
    )
    op.execute(f"DROP TYPE {_ENUM}_old")
