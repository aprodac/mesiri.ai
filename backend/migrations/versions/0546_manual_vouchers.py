"""Manual vouchers (ACC-12): the link from a reversal to the voucher it reverses.

See docs/plans/accounts-plan.md §5.2 and §8. Additive only: a manual voucher is a ``journal_entries`` row with
``source_kind = 'manual'`` (the posting sweep never reads, re-posts or deletes those), numbered and balanced like
every other entry. Two nullable columns:

- ``reverses_id``: the voucher this one reverses (a mirror of its lines); one reversal per voucher (unique index).
- ``reversal_reason``: why it was reversed, as the accountant said.

Revision ID: 0546
Revises: 0545
Create Date: 2026-11-11
"""

from __future__ import annotations

from alembic import op

revision = "0546"
down_revision = "0545"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE journal_entries ADD COLUMN reverses_id uuid REFERENCES journal_entries(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE journal_entries ADD COLUMN reversal_reason text")
    op.execute("CREATE UNIQUE INDEX uq_journal_entries_reverses ON journal_entries (reverses_id) "
               "WHERE reverses_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM journal_entries WHERE source_kind = 'manual') THEN "
               "RAISE EXCEPTION 'Manual vouchers exist; downgrading would lose their reversal links'; END IF; END $$")
    op.execute("DROP INDEX IF EXISTS uq_journal_entries_reverses")
    op.execute("ALTER TABLE journal_entries DROP COLUMN IF EXISTS reversal_reason")
    op.execute("ALTER TABLE journal_entries DROP COLUMN IF EXISTS reverses_id")
