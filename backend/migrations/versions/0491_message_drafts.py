"""Message drafts: what a worker sent, held until they tap Save (request 124, P1).

One row is the open card of one sender: an ordered list of typed items (labour,
work, materials, issues) that no domain table knows about yet. Save writes the
items through the existing services in one transaction and marks the row
`saved`; Cancel marks it `discarded`, so nothing was ever written. See
docs/architecture/ADR-draft-per-message.md.

Additive only: a new table, nothing existing changes. Row-level security as
every company table has it (0484). Used only by companies with the `draft_v2`
setting on; for everyone else the table stays empty.

Revision ID: 0491
Revises: 0490
Create Date: 2026-10-27
"""

from __future__ import annotations

from alembic import op

revision = "0491"
down_revision = "0490"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE message_drafts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            project_id uuid,
            site_id uuid,
            source_message_id text,
            status text NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'saved', 'discarded')),
            items jsonb NOT NULL DEFAULT '[]'::jsonb,
            reminded_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            saved_at timestamptz
        )
        """
    )
    # One open card per sender: the partial index is the hard guarantee.
    op.execute(
        "CREATE UNIQUE INDEX uq_message_drafts_one_open ON message_drafts (organization_id, user_id) "
        "WHERE status = 'open'"
    )
    op.execute("CREATE INDEX ix_message_drafts_org_status ON message_drafts (organization_id, status, updated_at)")
    op.execute("ALTER TABLE message_drafts ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON message_drafts USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS message_drafts")
