"""Manual supplier ratings after an order is finished (PRC-50).

See docs/plans/procurement-phase2-plan.md §5.7. Additive only (one new table with tenant row-level security):

- ``vendor_ratings``: one answer per order to "How was this supplier?": 1-5 stars and an optional note, or skipped
  (``stars`` empty), so the order sheet never asks twice. Shown beside the computed score, never mixed into it.

Revision ID: 0544
Revises: 0543
Create Date: 2026-11-11
"""

from __future__ import annotations

from alembic import op

revision = "0544"
down_revision = "0543"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE vendor_ratings (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            vendor_id uuid NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
            purchase_order_id uuid NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
            stars smallint,
            note text,
            rated_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_vendor_ratings_order UNIQUE (purchase_order_id),
            CONSTRAINT ck_vendor_ratings_stars CHECK (stars IS NULL OR stars BETWEEN 1 AND 5)
        )
        """
    )
    op.execute("CREATE INDEX ix_vendor_ratings_vendor ON vendor_ratings (organization_id, vendor_id)")
    op.execute("ALTER TABLE vendor_ratings ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON vendor_ratings USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vendor_ratings")
