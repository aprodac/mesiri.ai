"""WhatsApp groups: a site's group with Mesiri's number in it (WA-87).

`whatsapp_groups` is one group Mesiri created through Meta's Groups API for one
site. It is `creating` from the create call until Meta's `group_lifecycle_update`
webhook gives the group id and invite link (`active`); `closed` when it is
deleted or Mesiri leaves; `failed` when Meta refuses to create it. At most one
`creating`/`active` group per site (partial unique index).

`whatsapp_group_join_requests` is a tap on the invite link that someone outside
the site's team made: held `pending` until the owner taps Allow or Don't allow.
Team members' requests are approved at once and are recorded here too.

Additive only: two new tables, nothing existing changes. Row-level security as
every company table has it (0484).

Revision ID: 0492
Revises: 0491
Create Date: 2026-10-28
"""

from __future__ import annotations

from alembic import op

revision = "0492"
down_revision = "0491"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE whatsapp_groups (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid REFERENCES projects(id) ON DELETE CASCADE,
            site_id uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
            wa_group_id text UNIQUE,
            create_request_id text,
            subject text NOT NULL,
            invite_link text,
            status text NOT NULL DEFAULT 'creating'
                CHECK (status IN ('creating', 'active', 'closed', 'failed')),
            created_by_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_whatsapp_groups_one_live_per_site ON whatsapp_groups (site_id) "
        "WHERE status IN ('creating', 'active')"
    )
    op.execute("CREATE INDEX ix_whatsapp_groups_request ON whatsapp_groups (create_request_id)")
    op.execute("CREATE INDEX ix_whatsapp_groups_project ON whatsapp_groups (project_id, status)")
    op.execute("ALTER TABLE whatsapp_groups ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON whatsapp_groups USING ({_RULE}) WITH CHECK ({_RULE})")

    op.execute(
        """
        CREATE TABLE whatsapp_group_join_requests (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            group_id uuid NOT NULL REFERENCES whatsapp_groups(id) ON DELETE CASCADE,
            join_request_id text NOT NULL,
            wa_id text NOT NULL,
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected')),
            decided_by_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            decided_at timestamptz,
            UNIQUE (group_id, join_request_id)
        )
        """
    )
    op.execute("ALTER TABLE whatsapp_group_join_requests ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON whatsapp_group_join_requests USING ({_RULE}) WITH CHECK ({_RULE})"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS whatsapp_group_join_requests")
    op.execute("DROP TABLE IF EXISTS whatsapp_groups")
