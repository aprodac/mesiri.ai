"""BE-05: audit log of superadmin actions.

One append-only row per change a Mesiri operator makes -- a company
created, deleted or suspended, a person added or locked out, a setting or
the AI configuration changed -- with who did it, when, to which company,
and the before/after values (secrets replaced with "[changed]").

`organization_id` deliberately has NO foreign key. Every other
organization-scoped table cascades on company delete
(tests/integration/test_organizations_cascade_delete_schema.py), but the
"company deleted" entry is the one that must outlive the company. The same
goes for `actor_user_id`: the entry outlives the person, and `actor_label`
keeps their name as it was.

Expand-only: a new table nothing older reads or writes.

Revision ID: 0475
Revises: 0474
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0475"
down_revision = "0474"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("actor_kind", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_label", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("organization_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("target_type", sa.String(), nullable=True),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("details", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index(
        "ix_admin_audit_log_org_occurred",
        "admin_audit_log",
        ["organization_id", sa.text("occurred_at DESC")],
    )
    op.create_index(
        "ix_admin_audit_log_occurred", "admin_audit_log", [sa.text("occurred_at DESC")]
    )


def downgrade() -> None:
    op.drop_index("ix_admin_audit_log_occurred", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_org_occurred", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")
