"""Late entries: updates that reach a site day after it was confirmed (BE-13).

A confirmed (APPROVED/PUBLISHED) site day is frozen (P7): its DPR version is
what the engineer confirmed and may already be with the client. An entry for
that day created afterwards is not in it. Until now it was saved silently,
could not be removed (a frozen day refuses rejections) and only showed up as
an unexplained difference in the next day's stock.

One row per such entry, written by the scheduler's late-entry check
(application/dpr/late_entries.py):

    source_table/source_id  the row that arrived late (unique: recorded once)
    fact_type/fact_id       the reviewable item it belongs to (fact_reviews
                            vocabulary; a late quantity belongs to its activity)
    outcome                 'reopened' (the day's report had not gone out, so
                            it went back for confirmation) or 'revised' (it had
                            been sent; a revised version was recorded, status
                            unchanged, nothing re-sent)
    shown_in_report_id      the later site report that listed it under "Late
                            entries for earlier days" and confirmed it

New table only; nothing existing changes.

Revision ID: 0481
Revises: 0480
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0481"
down_revision = "0480"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "late_entries",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column(
            "daily_report_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("daily_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_table", sa.String(), nullable=False),
        sa.Column("source_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("fact_type", sa.String(), nullable=False),
        sa.Column("fact_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("entry_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column(
            "shown_in_report_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("daily_reports.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("source_table", "source_id", name="uq_late_entries_source"),
        sa.CheckConstraint("outcome IN ('reopened', 'revised')", name="ck_late_entries_outcome"),
    )
    op.create_index(
        "ix_late_entries_site_unshown",
        "late_entries",
        ["organization_id", "site_id", "report_date"],
        postgresql_where=sa.text("shown_in_report_id IS NULL"),
    )
    op.create_index("ix_late_entries_fact", "late_entries", ["fact_type", "fact_id"])


def downgrade() -> None:
    op.drop_index("ix_late_entries_fact", table_name="late_entries")
    op.drop_index("ix_late_entries_site_unshown", table_name="late_entries")
    op.drop_table("late_entries")
