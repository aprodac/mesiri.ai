"""Places on site (LP-01): an order and an archive for ``location_nodes``.

See docs/plans/location-progress-plan.md. Additive only:

- ``sort_order``: floors are listed Basement, Ground, First ... and rooms in the order they were set up, not by name.
- ``archived_at``: a place with work recorded on it is archived (hidden from pickers, kept on its work), never
  deleted; a place nothing points at is deleted.

Revision ID: 0526
Revises: 0525
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "0526"
down_revision = "0525"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE location_nodes ADD COLUMN IF NOT EXISTS sort_order integer NOT NULL DEFAULT 0, "
               "ADD COLUMN IF NOT EXISTS archived_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE location_nodes DROP COLUMN IF EXISTS archived_at, DROP COLUMN IF EXISTS sort_order")
