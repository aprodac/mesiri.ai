"""PRC-11: a supplier's bill matched to deliveries already recorded, and what the bill said about each.

When a bill comes for deliveries the site already recorded, the bill is linked to those deliveries instead of adding
them again (stock and money counted once). The bill may say a different quantity or rate than the site recorded: the
delivery keeps what the site counted, and the bill's figures are kept beside it so the difference is shown, never
silently overwritten.

``material_receipts``: ``billed_quantity``, ``billed_rate`` (nullable): what the bill said, set only when a bill was
matched to this delivery. Additive; nothing existing is rewritten.

Revision ID: 0517
Revises: 0516
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "0517"
down_revision = "0516"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE material_receipts ADD COLUMN billed_quantity numeric, ADD COLUMN billed_rate numeric")


def downgrade() -> None:
    op.execute("ALTER TABLE material_receipts DROP COLUMN IF EXISTS billed_rate, DROP COLUMN IF EXISTS billed_quantity")
