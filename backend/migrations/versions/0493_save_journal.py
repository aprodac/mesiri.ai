"""The save journal: one row per Save tap (request 142, B).

Every Save of a message draft writes ONE row in the same transaction as the
records: company, sender, time, site, day, and a reference to each fact written
(``facts``: fact type and id, the tool and arguments that made it, its card
line). "Undo" and "change" of any saved entry read this journal, so they work
the same for every kind of record. See docs/architecture/ADR-draft-per-message.md.

Additive only: a new table, nothing existing changes. Row-level security as
every company table has it (0484). Written only for companies with the
`draft_v2` setting on; for everyone else the table stays empty.

Revision ID: 0493
Revises: 0492
Create Date: 2026-10-29
"""

from __future__ import annotations

from alembic import op

revision = "0493"
down_revision = "0492"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE save_journal (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            draft_id uuid,
            site_id uuid,
            site_name text,
            day date,
            facts jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            undone_at timestamptz
        )
        """
    )
    op.execute("CREATE INDEX ix_save_journal_sender ON save_journal (organization_id, user_id, created_at DESC)")
    op.execute("ALTER TABLE save_journal ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON save_journal USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS save_journal")
