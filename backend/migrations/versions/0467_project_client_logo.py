"""Client logo per project, for that project's DPRs (BE-33).

A project's DPR can carry the client's logo next to the company's own
(decided 13 Oct 2026). `projects.client` already holds the client's name;
this adds where the uploaded logo file is kept in object storage. The company
logo is not a column: it lives in the `branding` organization setting (BE-20).

Expand-only: one nullable column that older code neither reads nor writes.

Revision ID: 0467
Revises: 0466
Create Date: 2026-10-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0467"
down_revision = "0466"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("client_logo_object_key", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "client_logo_object_key")
