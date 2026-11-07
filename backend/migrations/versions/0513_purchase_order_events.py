"""Purchase order history: each change, who made it and when (PRC-28).

One row per change to an order: placed, expected date moved, supplier changed, items changed, their number,
notes, cancelled, closed short, opened again, a delivery put on or taken off. ``what`` is the line people read
("Expected date: Fri 13 Nov → Mon 16 Nov"); ``kind`` groups them. Orders placed before this have no rows: their
history is read from the order itself as before.

Additive only: one new table (row-level security, as every company table).

Revision ID: 0513
Revises: 0512
Create Date: 2026-11-07
"""

from __future__ import annotations

from alembic import op

revision = "0513"
down_revision = "0512"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE purchase_order_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            purchase_order_id uuid NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
            kind text NOT NULL,
            what text NOT NULL,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_purchase_order_events_order ON purchase_order_events (purchase_order_id, created_at)")
    op.execute("ALTER TABLE purchase_order_events ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON purchase_order_events USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS purchase_order_events")
