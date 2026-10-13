"""Company lifecycle (trials) and platform-wide settings (SS-02).

Self-serve signup (V1 tracker, section SS) gives anyone a company on a free
trial. That needs two things the schema didn't have:

**Trial fields on `organizations`.** `status` gains the values `trial` and
`expired` next to `active` and `suspended` (it is a plain VARCHAR, so no
type change). A trial's end is stored, not derived from a fixed number of
days, because the length is a superadmin setting and can be extended per
company. `signup_source` records how the company was created
(`superadmin`, `whatsapp`, `web`, `api`) for the trials funnel;
`converted_at` records when a trial became a paying customer.

**`platform_settings`**: one row per Mesiri-wide setting (trial length,
data retention after expiry, whether self-serve signup is switched on).
Per-company settings already live in `organization_settings` (0365); these
are not per company, so they get their own small key/value table rather
than a magic "platform" organization row.

Expand-only: every new column is nullable or has a default, and older code
neither reads nor writes any of them.

Revision ID: 0464
Revises: 0463
Create Date: 2026-10-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0464"
down_revision = "0463"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations", sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "organizations",
        sa.Column(
            "signup_source", sa.String(), nullable=False, server_default=sa.text("'superadmin'")
        ),
    )
    op.add_column(
        "organizations", sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", sa.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
    op.drop_column("organizations", "converted_at")
    op.drop_column("organizations", "signup_source")
    op.drop_column("organizations", "trial_ends_at")
    op.drop_column("organizations", "trial_started_at")
