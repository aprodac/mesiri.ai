"""BE-16: when a project's DPR is sent.

V1 rule (decided 13 Oct 2026): the project DPR goes to the owner/PM once
every site's engineer has confirmed, or at the send deadline -- whichever
comes first -- with any unconfirmed site shown as "Not reported". The cutoff
(`reporting_cutoff_time`, 0260) only builds the drafts now.

- `dpr_send_deadline`  "HH:MM" in the project's reporting timezone; same
  string shape as `reporting_cutoff_time`. Default 21:00 (approved 13 Oct).
- `dpr_last_sent_on`   the local date the DPR was last sent, so it goes once
  a day.
- `dpr_send_requested_on`  set by "Send now" in the dashboard; the sender
  picks it up on its next tick (the backend does not talk to WhatsApp).

Revision ID: 0469
Revises: 0468
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0469"
down_revision = "0468"
branch_labels = None
depends_on = None


def _columns() -> list[sa.Column]:
    return [
        sa.Column("dpr_send_deadline", sa.String(), nullable=False, server_default="21:00"),
        sa.Column("dpr_last_sent_on", sa.Date(), nullable=True),
        sa.Column("dpr_send_requested_on", sa.Date(), nullable=True),
    ]


def upgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("projects")}
    for column in _columns():
        if column.name not in existing:
            op.add_column("projects", column)


def downgrade() -> None:
    for column in reversed(_columns()):
        op.drop_column("projects", column.name)
