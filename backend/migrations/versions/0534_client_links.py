"""Client view links (CV-01, asked in session by Ilan 9 Nov 2026; module 30 of the capability framework).

A client (the house owner) opens their project on the phone from a secret link the company sends on WhatsApp: no
login. See docs/plans/client-view-plan.md. Additive only:

- ``client_links``: one row per link. Only the SHA-256 of the token is kept (``token_hash``), so a database read
  never yields a working link; the token itself is shown once, when the link is made. ``revoked_at`` turns a link off
  at once; ``last_opened_at`` / ``open_count`` tell the company it is being used.

Tenant row-level security like 0533. The public read finds the link with no company set (the policy lets a
transaction with nothing set through, as login and the webhook do), then scopes the rest of the request to the
link's company. Downgrade refuses while links exist.

Revision ID: 0534
Revises: 0533
Create Date: 2026-11-09
"""

from __future__ import annotations

from alembic import op

revision = "0534"
down_revision = "0533"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE client_links (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            token_hash text NOT NULL,
            label text,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            revoked_at timestamptz,
            revoked_by uuid REFERENCES users(id) ON DELETE SET NULL,
            last_opened_at timestamptz,
            open_count integer NOT NULL DEFAULT 0,
            CONSTRAINT uq_client_links_token_hash UNIQUE (token_hash),
            CONSTRAINT ck_client_links_token_hash CHECK (char_length(token_hash) = 64)
        )""")
    op.execute("CREATE INDEX ix_client_links_org_project ON client_links (organization_id, project_id)")
    op.execute("ALTER TABLE client_links ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON client_links USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM client_links) THEN "
               "RAISE EXCEPTION 'Client links exist; downgrading would turn them off'; END IF; END $$")
    op.execute("DROP TABLE client_links")
