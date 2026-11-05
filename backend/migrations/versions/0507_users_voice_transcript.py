"""users.voice_transcript: show what was heard above a voice note's reply, for this person (WA-246).

Ilan, 5 Nov 2026: the "🎤 _what was heard_" line on top of every voice note's reply (WA-209) should be a
switch in the control panel, per company or per person, off by default for everyone. The company's switch is
the organization setting ``voice_transcript`` (default off, no row needed); this column is the per-person
override. NULL = follow the company.

Additive: one nullable column. Downgrade drops it (per-person choices made since are lost; everyone follows
their company's switch).

Revision ID: 0507
Revises: 0506
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0507"
down_revision = "0506"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("voice_transcript", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "voice_transcript")
