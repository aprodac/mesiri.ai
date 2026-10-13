"""Let a labour attendance report be withdrawn without deleting it.

Attendance is immutable (P5) and the sanctioned repair is supersession: a
supervisor who mis-reported re-sends the day and picks "Replace it", which
sets `corrects_report_id` and leaves both rows readable. That works, but it
only reaches within one project/site/day -- the duplicate-day gate is keyed
on (project_id, site_id, occurred_date), so a report filed against the
WRONG site is never offered as something to replace. Re-sending on the
correct site creates a second, independent report; the wrong-site one keeps
counting man-days and cost against a site nobody worked on, forever.

The only existing escape was `DELETE /workforce/attendance/{id}`, which is
double-gated behind MESIRI_ALLOW_LABOUR_DELETE + ADMIN precisely because it
destroys the audit trail and explicitly says it is for clearing test data,
"never for fixing a mistake."

So: a void, not a delete. `voided_at` stamps the row out of every total
while the row, its lines and its attachments all stand exactly as reported
-- the same shape `activities.deleted_at` already uses for ADR-D15's undo,
and consistent with site issues' CANCELLED (migration 0460): the record of
the mistake is itself worth keeping.

Nullable columns only: no backfill, no rewrite, and every existing report
reads as not-voided.

Revision ID: 0462
Revises: 0461
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0462"
down_revision = "0461"
branch_labels = None
depends_on = None

_TABLE = "labour_attendance_reports"
_INDEX = "ix_labour_attendance_reports_live"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        _TABLE,
        sa.Column(
            "voided_by",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    # Required by the write path, not by the schema: a void with no stated
    # reason is indistinguishable from data loss when someone reads this row
    # a year from now. Nullable here only because existing rows have none.
    op.add_column(_TABLE, sa.Column("void_reason", sa.Text(), nullable=True))

    # Partial index over the live rows only -- every total filters on
    # `voided_at IS NULL`, and the voided set is expected to stay tiny, so
    # indexing it would cost writes to serve nothing.
    op.create_index(
        _INDEX,
        _TABLE,
        ["organization_id", "project_id", "occurred_date"],
        postgresql_where=sa.text("voided_at IS NULL"),
    )


def downgrade() -> None:
    # Dropping these loses which reports were withdrawn, and they will start
    # counting again in every total. That is the honest consequence of
    # reverting the feature -- there is nowhere else to put the fact.
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_column(_TABLE, "void_reason")
    op.drop_column(_TABLE, "voided_by")
    op.drop_column(_TABLE, "voided_at")
