"""BOQ first entry (PS phase 2): machinery in a line's budget, and the project's overheads.

- ``work_package_planned_items.machinery_rate``: the budget per unit for machines (mixer, vibrator, JCB, crane hire),
  a fourth budget rate beside labour, material and subcontract (0508). The line's budget cost is the sum of the rates
  given, so a line without it is unchanged.
- ``projects.overhead_pct``: site and office overheads as a % of the BOQ's budget cost (supervision, site office,
  insurance, interest), so the BOQ shows the margin after overheads, not only the direct margin.

Additive: nullable columns with CHECKs like 0508's; no row is rewritten. Downgrade drops the columns.

Revision ID: 0565
Revises: 0564
Create Date: 2026-11-20
"""

from __future__ import annotations

from alembic import op

revision = "0565"
down_revision = "0564"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE work_package_planned_items
            ADD COLUMN machinery_rate numeric(14,2),
            ADD CONSTRAINT ck_planned_items_machinery_rate CHECK (machinery_rate IS NULL OR machinery_rate >= 0)
    """)
    op.execute("""
        ALTER TABLE projects
            ADD COLUMN overhead_pct numeric(5,2),
            ADD CONSTRAINT ck_projects_overhead_pct CHECK (overhead_pct IS NULL OR overhead_pct BETWEEN 0 AND 100)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP CONSTRAINT IF EXISTS ck_projects_overhead_pct, DROP COLUMN overhead_pct")
    op.execute("""
        ALTER TABLE work_package_planned_items
            DROP CONSTRAINT IF EXISTS ck_planned_items_machinery_rate,
            DROP COLUMN machinery_rate
    """)
