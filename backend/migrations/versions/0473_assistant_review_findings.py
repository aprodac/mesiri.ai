"""WA-15: problems the nightly assistant reviewer found, tracked across days.

The reviewer (docs/ops/assistant-review.md) reads the day's WhatsApp
conversations and records each problem it sees here. One row per *problem*,
not per sighting: `fingerprint` is a stable slug the reviewer chooses
("material-unit-asked-twice"), so seeing the same problem tomorrow updates
the row (`days_seen`, `occurrences`, `last_seen_on`) instead of adding one.
That is what makes a problem "recurring", the trigger for a fix in WA-16.

No customer content: `title`/`detail` are the reviewer's paraphrase, and
`examples` holds pseudonymous references (`u_xxxx @ 09:12`), never message
text or phone numbers. Not tenant-scoped -- it describes the product, read
only by platform admins.

Revision ID: 0473
Revises: 0472
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0473"
down_revision = "0472"
branch_labels = None
depends_on = None

_CATEGORIES = ("copy", "understanding", "routing", "flow", "speed", "error", "unmet")
_STATUSES = ("open", "fixing", "fixed", "wont_fix")


def upgrade() -> None:
    if "assistant_review_findings" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "assistant_review_findings",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("fingerprint", sa.String(120), nullable=False, unique=True),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        # Likely cause, e.g. "channel/replies.py:render_material_prompt".
        sa.Column("suspected_location", sa.String(300), nullable=True),
        sa.Column("workflow_key", sa.String(80), nullable=True),
        sa.Column("severity", sa.SmallInteger(), nullable=False, server_default="2"),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="0"),
        # The last day's count, so re-running the same night replaces it
        # instead of adding it twice.
        sa.Column("occurrences_last_day", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("days_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_on", sa.Date(), nullable=False),
        sa.Column("last_seen_on", sa.Date(), nullable=False),
        sa.Column(
            "examples",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # Replay case(s) that reproduce it: apps/whatsapp-assistant/tests/replay/cases/<id>.json
        sa.Column(
            "replay_cases",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("fix_commit", sa.String(40), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            f"category IN {_CATEGORIES}", name="ck_assistant_review_findings_category"
        ),
        sa.CheckConstraint(f"status IN {_STATUSES}", name="ck_assistant_review_findings_status"),
        sa.CheckConstraint(
            "severity BETWEEN 1 AND 3", name="ck_assistant_review_findings_severity"
        ),
    )
    op.create_index(
        "ix_assistant_review_findings_status_last_seen",
        "assistant_review_findings",
        ["status", "last_seen_on"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assistant_review_findings_status_last_seen", table_name="assistant_review_findings"
    )
    op.drop_table("assistant_review_findings")
