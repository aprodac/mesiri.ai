"""Record where the main tables and the WhatsApp context copy disagree (BE-01).

BE-01 retires the `context_*` copy that the WhatsApp assistant reads people,
companies, projects and sites from. Before the main tables become the only
source, both are asked every question side by side (MESIRI_IDENTITY_SOURCE =
shadow) and every difference lands here: one row per distinct question, with a
hit count, so the table stays small however much traffic repeats it.

Expand-only: a new table nothing else reads. Dropped together with the
`context_*` tables in BE-01's last step.

Revision ID: 0465
Revises: 0464
Create Date: 2026-10-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0465"
down_revision = "0464"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_shadow_mismatches",
        sa.Column("fingerprint", sa.String(64), primary_key=True),
        sa.Column("port", sa.String(64), nullable=False),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("args", JSONB, nullable=False),
        sa.Column("context_result", JSONB),
        sa.Column("main_result", JSONB),
        sa.Column("hits", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("identity_shadow_mismatches")
