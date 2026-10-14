"""BE-15: who gets a project's DPR, and WhatsApp opt-in records.

`report_recipients` -- the people a project's DPR goes to: company users
(by `user_id`) and outside contacts with no Mesiri login -- the client, the
architect, a consultant (by `phone`, digits with country code, the WhatsApp
id form). A project with no active rows keeps the default audience (its
admins and project managers), so nothing changes until someone sets a list.
Removing a recipient stamps `removed_at`; rows are never deleted, so the
history of who was getting the report stays.

`whatsapp_opt_ins` -- an append-only log of consent per company and phone
number: one row per opt-in or opt-out, the latest row is the current state.
Meta requires opt-in before a business starts a conversation. Company users
are covered by joining the company; an outside contact must have an
`opted_in` row before anything is sent to them, and an `opted_out` row stops
messages to anyone, user or contact. `method` says how consent was given:
recorded by an admin (offline, e.g. in the contract), a WhatsApp reply
(WA-09), or a web form.

Revision ID: 0471
Revises: 0470
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0471"
down_revision = "0470"
branch_labels = None
depends_on = None

_OPT_IN_STATES = ("opted_in", "opted_out")
_OPT_IN_METHODS = ("recorded_by_admin", "whatsapp_reply", "web_form")


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "report_recipients" not in existing:
        op.create_table(
            "report_recipients",
            sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column("phone", sa.String(), nullable=True),
            # Free text shown next to the name: "Client", "Architect".
            sa.Column("label", sa.String(), nullable=True),
            sa.Column("created_by_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
            ),
            sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("removed_by_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.CheckConstraint(
                "(user_id IS NOT NULL) <> (phone IS NOT NULL)",
                name="ck_report_recipients_user_or_phone",
            ),
        )
        op.create_index(
            "uq_report_recipients_project_user",
            "report_recipients",
            ["project_id", "user_id"],
            unique=True,
            postgresql_where=sa.text("removed_at IS NULL AND user_id IS NOT NULL"),
        )
        op.create_index(
            "uq_report_recipients_project_phone",
            "report_recipients",
            ["project_id", "phone"],
            unique=True,
            postgresql_where=sa.text("removed_at IS NULL AND phone IS NOT NULL"),
        )

    if "whatsapp_opt_ins" not in existing:
        op.create_table(
            "whatsapp_opt_ins",
            sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                sa.UUID(as_uuid=True),
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("phone", sa.String(), nullable=False),
            sa.Column("state", sa.String(), nullable=False),
            sa.Column("method", sa.String(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("recorded_by_user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
            ),
            sa.CheckConstraint(
                "state IN (" + ", ".join(f"'{s}'" for s in _OPT_IN_STATES) + ")",
                name="ck_whatsapp_opt_ins_state",
            ),
            sa.CheckConstraint(
                "method IN (" + ", ".join(f"'{m}'" for m in _OPT_IN_METHODS) + ")",
                name="ck_whatsapp_opt_ins_method",
            ),
        )
        op.create_index(
            "ix_whatsapp_opt_ins_org_phone",
            "whatsapp_opt_ins",
            ["organization_id", "phone", "created_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_whatsapp_opt_ins_org_phone", table_name="whatsapp_opt_ins")
    op.drop_table("whatsapp_opt_ins")
    op.drop_index("uq_report_recipients_project_phone", table_name="report_recipients")
    op.drop_index("uq_report_recipients_project_user", table_name="report_recipients")
    op.drop_table("report_recipients")
