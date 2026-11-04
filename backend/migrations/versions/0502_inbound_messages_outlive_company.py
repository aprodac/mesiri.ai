"""A deleted company's WhatsApp messages stay, so the control panel still shows them (SS-24).

Before, Delete Tenant took every message the company's people sent with it
(`inbound_messages.organization_id` cascaded, and the project / site links made
the delete clear those rows first), while its AI and WhatsApp costs
(`provider_executions`, no foreign key) stayed behind with no company to show.
The team then couldn't see what a deleted trial had done or what it had cost.

Now a message keeps its `organization_id` when the company goes, like
`provider_executions` and `journey_traces` already do, and its project / site
are emptied instead of the message being deleted. The control panel names the
company from the `company.deleted` audit entry ("Deleted: AD GROUPS").

No data is changed: two links become ON DELETE SET NULL and one link is removed.
Row-level security is unchanged (`inbound_messages` keeps its policy, with
rows of no company visible to none).

Downgrade puts the links back. It first deletes the messages of companies that
no longer exist (they would break the restored link): those are lost.

Revision ID: 0502
Revises: 0501
Create Date: 2026-11-04
"""

from __future__ import annotations

from alembic import op

revision = "0502"
down_revision = "0501"
branch_labels = None
depends_on = None

_TABLE = "inbound_messages"


def upgrade() -> None:
    op.drop_constraint("fk_inbound_messages_organization_id", _TABLE, type_="foreignkey")
    for column, parent in (("project_id", "projects"), ("site_id", "sites")):
        name = f"fk_inbound_messages_{column}"
        op.drop_constraint(name, _TABLE, type_="foreignkey")
        op.create_foreign_key(name, _TABLE, parent, [column], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.execute(
        "DELETE FROM inbound_messages m WHERE m.organization_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM organizations o WHERE o.id = m.organization_id)"
    )
    for column, parent in (("project_id", "projects"), ("site_id", "sites")):
        name = f"fk_inbound_messages_{column}"
        op.drop_constraint(name, _TABLE, type_="foreignkey")
        op.create_foreign_key(name, _TABLE, parent, [column], ["id"])
    op.create_foreign_key(
        "fk_inbound_messages_organization_id",
        _TABLE,
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
