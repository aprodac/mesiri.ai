"""Supplier lead time (MP-03): days from order to delivery, for the material plan's order-by date.

See docs/plans/material-plan-plan.md. Additive only: ``vendors.lead_time_days`` (nullable, 0-120). The plan uses the
lead time of the supplier who last delivered the material, and 3 days when none is set.

Revision ID: 0524
Revises: 0523
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "0524"
down_revision = "0523"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE vendors ADD COLUMN lead_time_days integer, "
               "ADD CONSTRAINT ck_vendors_lead_time CHECK (lead_time_days IS NULL OR lead_time_days BETWEEN 0 AND 120)")


def downgrade() -> None:
    op.execute("ALTER TABLE vendors DROP CONSTRAINT IF EXISTS ck_vendors_lead_time, DROP COLUMN IF EXISTS lead_time_days")
