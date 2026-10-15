"""SS-09: self-serve signup attempts, and a lookup of past trials by number.

`signup_attempts` -- one row per self-serve signup check (web code request,
web signup, WhatsApp signup): the number, the door, the IP address when
there is one, allowed or refused (and why), and the flags it earned
(shared IP, an earlier trial, a signup burst). It is what the per-IP limit
counts and where the control panel reads a signup's flags. No foreign keys:
an attempt exists before (or instead of) any company or user.

The "one trial per number" rule reads past trials from `admin_audit_log`
(BE-05), whose company.created rows outlive deleted companies; the partial
expression index makes that lookup by owner number cheap.

Expand-only.

Revision ID: 0480
Revises: 0479
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0480"
down_revision = "0479"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signup_attempts",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("signup_source", sa.String(), nullable=False),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column(
            "flags", ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.CheckConstraint("outcome IN ('allowed', 'refused')", name="ck_signup_attempts_outcome"),
    )
    op.create_index("ix_signup_attempts_phone_created", "signup_attempts", ["phone", "created_at"])
    op.create_index(
        "ix_signup_attempts_ip_created",
        "signup_attempts",
        ["ip_address", "created_at"],
        postgresql_where=sa.text("ip_address IS NOT NULL"),
    )
    op.create_index(
        "ix_admin_audit_log_created_owner_phone",
        "admin_audit_log",
        [sa.text("(details->>'owner_whatsapp_number')")],
        postgresql_where=sa.text("action = 'company.created'"),
    )


def downgrade() -> None:
    op.drop_index("ix_admin_audit_log_created_owner_phone", table_name="admin_audit_log")
    op.drop_index("ix_signup_attempts_ip_created", table_name="signup_attempts")
    op.drop_index("ix_signup_attempts_phone_created", table_name="signup_attempts")
    op.drop_table("signup_attempts")
