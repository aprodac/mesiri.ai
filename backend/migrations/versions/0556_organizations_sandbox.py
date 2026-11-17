"""organizations: a person's learning sandbox (SS-66, guided demo).

Learn Mesiri's sample company (docs/plans/guided-demo-plan.md sections 5 and 16): a private copy of "Green Villa" per
person, made on demand, kept until they reset it or leave it unused for 30 days.

    sandbox_of           the real company of the person it was made for; NULL for every real company
    sandbox_user_id      that person (users.id in the real company): one sandbox per person
    sandbox_expires_at   when it is removed if not opened again (moved forward each time it is opened)

No foreign keys on purpose: removing a real company or person must never be blocked by their sandbox; a sandbox
whose company or person is gone is removed by the next cleanup. Its status is ``sandbox`` (lifecycle.SANDBOX), so no
scheduled job, report or WhatsApp send reaches it.

Additive: three nullable columns and two indexes; no existing row changes. Downgrade drops them (any sandbox left
would become a plain company with status 'sandbox': remove sandboxes first).

Revision ID: 0556
Revises: 0555
Create Date: 2026-11-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0556"
down_revision = "0555"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("sandbox_of", sa.UUID(), nullable=True))
    op.add_column("organizations", sa.Column("sandbox_user_id", sa.UUID(), nullable=True))
    op.add_column("organizations", sa.Column("sandbox_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ux_organizations_sandbox_user", "organizations", ["sandbox_user_id"], unique=True,
        postgresql_where=sa.text("sandbox_user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_organizations_sandbox_expires", "organizations", ["sandbox_expires_at"],
        postgresql_where=sa.text("sandbox_of IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_organizations_sandbox_expires", table_name="organizations")
    op.drop_index("ux_organizations_sandbox_user", table_name="organizations")
    op.drop_column("organizations", "sandbox_expires_at")
    op.drop_column("organizations", "sandbox_user_id")
    op.drop_column("organizations", "sandbox_of")
