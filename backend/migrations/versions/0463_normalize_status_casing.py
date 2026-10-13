"""Store organization and user statuses in lowercase (BE-07).

Organizations were written "Active" (provisioning) while users and every
other table use lowercase "active". Readers had to remember which convention
applied where, and two forgot:

- `application/projects/auto_dpr.py` selected `o.status = 'active'`, which a
  case-sensitive Postgres comparison never matches against "Active", so the
  automatic DPR found no company to run for.
- The control panel once wrote a user back as "Active", which the
  assistant's `u.status = 'active'` lookup read as inactive and locked that
  person out of WhatsApp (see tests/unit/test_user_status_case.py).

From here on statuses are lowercase everywhere. This migration lowercases
the rows already stored; the code now writes lowercase and every reader
compares case-insensitively, so a rollback to older code (which writes
"Active") still reads correctly.

Expand-only: data change, no schema change, no constraint (a CHECK would
reject the "Active" an older build writes during a rollback).

Revision ID: 0463
Revises: 0462
Create Date: 2026-10-13
"""

from __future__ import annotations

from alembic import op

revision = "0463"
down_revision = "0462"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE organizations SET status = lower(trim(status)) WHERE status <> lower(trim(status))"
    )
    op.execute("UPDATE users SET status = lower(trim(status)) WHERE status <> lower(trim(status))")


def downgrade() -> None:
    # Lowercase is a valid value for every reader, old and new, so there is
    # nothing to undo. Restoring the old "Active" spelling would re-break
    # the automatic DPR query.
    pass
