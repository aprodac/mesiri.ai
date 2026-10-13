"""BE-09: save first, confirm later -- `extractions` and `fact_reviews`.

Decided 13 Oct 2026: what the AI reads from a message is saved straight away
as a DRAFT and confirmed later by the site engineer; only confirmed facts go
into a confirmed DPR. (This replaces DAILY_REPORTING_PLAN rule P2.)

`extractions` -- what the AI read from one message: the message and its
correlation id, the AI call, the model, the structured output and how sure
it was (`ContextConfidence` values, P11). Nothing like it existed:
`provider_executions` logs only that a call happened.

`fact_reviews` -- an append-only log of a fact's review state: one row when
it is saved as a draft, one when it is confirmed or rejected. A fact's state
is its latest row; a fact with NO row is confirmed -- everything saved
before this table (the confirm-first flows) and every flow that still
confirms before saving. Kept beside the facts rather than as a column on
them (approved 13 Oct, option B) so the Labour and Materials tables are not
changed and stay insert-only: confirming is a new fact about a fact, never
an edit. Rejecting a draft also goes through the owning module's own undo
(void, reversal, cancel); this row is the audit of why.

`fact_type` is checked against the fact kinds the DPR shows. `project_id`,
`site_id` and `fact_date` are copied from the fact so a site's day can find
its drafts without joining five tables.

Revision ID: 0470
Revises: 0469
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0470"
down_revision = "0469"
branch_labels = None
depends_on = None

_FACT_TYPES = ("activity", "site_issue", "labour_report", "material_receipt", "material_usage")
_STATES = ("draft", "confirmed", "rejected")


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "extractions" not in existing:
        op.create_table(
            "extractions",
            sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("correlation_id", sa.String(), nullable=True),
            sa.Column(
                "inbound_message_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("inbound_messages.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "provider_execution_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("provider_executions.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("provider", sa.String(), nullable=True),
            sa.Column("model", sa.String(), nullable=True),
            # What the AI produced, as it produced it.
            sa.Column("extracted", JSONB, nullable=False),
            # ContextConfidence value (very_high .. unresolved), P11.
            sa.Column("confidence", sa.String(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
            ),
        )
        op.create_index("ix_extractions_correlation_id", "extractions", ["correlation_id"])

    if "fact_reviews" not in existing:
        op.create_table(
            "fact_reviews",
            sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("fact_type", sa.String(), nullable=False),
            # No FK: points into one of five tables, resolved by fact_type.
            sa.Column("fact_id", sa.UUID(as_uuid=True), nullable=False),
            sa.Column("project_id", sa.UUID(as_uuid=True), nullable=True),
            sa.Column("site_id", sa.UUID(as_uuid=True), nullable=True),
            sa.Column("fact_date", sa.Date(), nullable=True),
            sa.Column("state", sa.String(), nullable=False),
            sa.Column(
                "extraction_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("extractions.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("actor_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
            ),
            sa.CheckConstraint(
                "fact_type IN (" + ", ".join(f"'{t}'" for t in _FACT_TYPES) + ")",
                name="ck_fact_reviews_fact_type",
            ),
            sa.CheckConstraint(
                "state IN (" + ", ".join(f"'{s}'" for s in _STATES) + ")",
                name="ck_fact_reviews_state",
            ),
        )
        op.create_index(
            "ix_fact_reviews_fact", "fact_reviews", ["fact_type", "fact_id", "created_at"]
        )
        op.create_index(
            "ix_fact_reviews_site_day", "fact_reviews", ["organization_id", "site_id", "fact_date"]
        )


def downgrade() -> None:
    op.drop_index("ix_fact_reviews_site_day", table_name="fact_reviews")
    op.drop_index("ix_fact_reviews_fact", table_name="fact_reviews")
    op.drop_table("fact_reviews")
    op.drop_index("ix_extractions_correlation_id", table_name="extractions")
    op.drop_table("extractions")
