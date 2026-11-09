"""GST on deliveries and order lines (PRC-34, procurement phase 2 step 0).

A delivery's rate was stored as the person said it, with or without GST nobody knew, so Rates compared a rate with
GST against one without. Two nullable columns on each priced row say which it is:

- ``gst_percent``: the GST rate (0-100; 0 = no GST charged). NULL: not known.
- ``rate_includes_gst``: true when ``unit_cost`` / ``rate`` already has the GST in it, false when GST is on top.
  NULL: not said.

On ``material_receipts`` (deliveries) and ``purchase_order_lines`` (an order's agreed rate, copied to the delivery
that fills it). Additive only; old rows stay NULL and read as "as entered" (the rule is in
``domains/procurement/gst.py``).

Revision ID: 0539
Revises: 0538
Create Date: 2026-11-09
"""

from __future__ import annotations

from alembic import op

revision = "0539"
down_revision = "0538"
branch_labels = None
depends_on = None

_TABLES = ("material_receipts", "purchase_order_lines")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN gst_percent numeric(5, 2), ADD COLUMN rate_includes_gst boolean, "
            f"ADD CONSTRAINT ck_{table}_gst_percent CHECK (gst_percent IS NULL OR gst_percent BETWEEN 0 AND 100)"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_gst_percent, "
            "DROP COLUMN IF EXISTS gst_percent, DROP COLUMN IF EXISTS rate_includes_gst"
        )
