"""BE-12: `OPENING_STOCK` inflow reason.

A site that starts using Mesiri mid-project already has material on it. Until
now the only way to record that was an ADJUSTMENT_IN, which reads as a
correction and cannot be told apart from one. OPENING_STOCK is its own
receipt reason: entered once per site+material by an ADMIN/PROJECT_MANAGER
(enforced in the materials router, like the adjustment reasons), and shown
in the DPR as an adjustment, never as a delivery.

Only the check constraint from 0270 changes. Downgrade turns any
OPENING_STOCK rows into ADJUSTMENT_IN (the reason they would have had
before) so the old constraint can be restored without losing stock.

Revision ID: 0477
Revises: 0476
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0477"
down_revision = "0476"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_material_receipts_movement_reason"
_OLD_REASONS = ("RECEIVED", "TRANSFER_IN", "RETURN_IN", "ADJUSTMENT_IN")
_NEW_REASONS = (*_OLD_REASONS, "OPENING_STOCK")


def _check(reasons: tuple[str, ...]) -> str:
    return "movement_reason IN ('" + "','".join(reasons) + "')"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "material_receipts", type_="check")
    op.create_check_constraint(_CONSTRAINT, "material_receipts", _check(_NEW_REASONS))


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE material_receipts SET movement_reason = 'ADJUSTMENT_IN' "
            "WHERE movement_reason = 'OPENING_STOCK'"
        )
    )
    op.drop_constraint(_CONSTRAINT, "material_receipts", type_="check")
    op.create_check_constraint(_CONSTRAINT, "material_receipts", _check(_OLD_REASONS))
