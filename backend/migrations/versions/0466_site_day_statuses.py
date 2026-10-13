"""BE-08: the site's working day -- NEEDS_DETAILS and READY statuses, plus
`daily_reports.missing_sections`.

A SITE-level `daily_reports` row already is "one working-day record per
site per date" (0440, `uq_daily_report_scope_date`), so V1's site day is
that row, not a new table. V1's evening flow (decided 13 Oct 2026) needs
two states the original enum does not have:

    collecting     -> DRAFT          (unchanged: the day is still filling)
    needs details  -> NEEDS_DETAILS  (new: past cutoff, something required is missing)
    ready          -> READY          (new: past cutoff, complete enough to confirm)
    with engineer  -> IN_REVIEW      (unchanged)
    confirmed      -> APPROVED       (unchanged: frozen, P7)
    sent           -> PUBLISHED      (unchanged)

`missing_sections` (JSONB, nullable) is what the readiness check found
missing -- `{"blocking": [...], "optional": [...]}` -- so the evening
gap-check (WA-04) can ask for exactly those parts. NULL until a day has
been checked at least once.

Enum values are added but not used in this transaction (PG 12+ allows
that; same posture as 0460). Existing rows are untouched.

Revision ID: 0466
Revises: 0465
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0466"
down_revision = "0465"
branch_labels = None
depends_on = None

_ENUM = "daily_report_status"
_PRIOR_VALUES = ("DRAFT", "IN_REVIEW", "APPROVED", "PUBLISHED", "NOT_REPORTED")


def upgrade() -> None:
    op.execute(f"ALTER TYPE {_ENUM} ADD VALUE IF NOT EXISTS 'NEEDS_DETAILS'")
    op.execute(f"ALTER TYPE {_ENUM} ADD VALUE IF NOT EXISTS 'READY'")

    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("daily_reports")}
    if "missing_sections" not in columns:
        op.add_column("daily_reports", sa.Column("missing_sections", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("daily_reports", "missing_sections")

    # Postgres cannot drop an enum value, so the type is rebuilt (0460's
    # pattern). Both new states are pre-confirmation, so they fold back
    # into DRAFT -- the day is unconfirmed either way, nothing is lost but
    # the readiness label, which the next generation run recomputes.
    op.execute("ALTER TABLE daily_reports ALTER COLUMN status DROP DEFAULT")
    op.execute(f"ALTER TYPE {_ENUM} RENAME TO {_ENUM}_old")
    values = ", ".join(f"'{v}'" for v in _PRIOR_VALUES)
    op.execute(f"CREATE TYPE {_ENUM} AS ENUM ({values})")
    # Runs while the column is still the old type, which accepts all values.
    op.execute(
        "UPDATE daily_reports SET status = 'DRAFT' WHERE status IN ('NEEDS_DETAILS', 'READY')"
    )
    op.execute(
        f"ALTER TABLE daily_reports ALTER COLUMN status TYPE {_ENUM} "
        f"USING status::text::{_ENUM}"
    )
    op.execute("ALTER TABLE daily_reports ALTER COLUMN status SET DEFAULT 'DRAFT'")
    op.execute(f"DROP TYPE {_ENUM}_old")
