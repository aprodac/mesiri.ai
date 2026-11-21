"""Project setup terms (PS-01, 02, 03, 04, 05): what a company agrees and decides before day 1.

- ``projects``: ``project_type`` (villa / apartment / commercial / ...), ``built_up_area_sqft`` and ``floors``, so a
  project has a size (cost per sq ft) and its kind.
- ``project_contracts``: ``client_payment_days`` (the client pays a bill in so many days: cash flow and overdue use it
  instead of an assumed 30), ``contract_type`` (``item_rate`` / ``lump_sum`` / ``cost_plus``), the delay penalty
  (``ld_pct_per_week`` of the contract value, capped at ``ld_cap_pct``), and the escalation clause
  (``escalation_applies``, ``escalation_terms``).

Additive: nullable columns with CHECKs like the existing ones; no row is rewritten. Downgrade drops the columns.

Revision ID: 0563
Revises: 0562
Create Date: 2026-11-20
"""

from __future__ import annotations

from alembic import op

revision = "0563"
down_revision = "0562"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE projects
            ADD COLUMN project_type text,
            ADD COLUMN built_up_area_sqft numeric(12,2),
            ADD COLUMN floors integer,
            ADD CONSTRAINT ck_projects_size CHECK (
                (built_up_area_sqft IS NULL OR built_up_area_sqft > 0)
                AND (floors IS NULL OR floors BETWEEN 1 AND 200))
    """)
    op.execute("""
        ALTER TABLE project_contracts
            ADD COLUMN client_payment_days integer,
            ADD COLUMN contract_type text,
            ADD COLUMN ld_pct_per_week numeric(5,2),
            ADD COLUMN ld_cap_pct numeric(5,2),
            ADD COLUMN escalation_applies boolean,
            ADD COLUMN escalation_terms text,
            ADD CONSTRAINT ck_project_contract_setup CHECK (
                (client_payment_days IS NULL OR client_payment_days BETWEEN 0 AND 365)
                AND (contract_type IS NULL OR contract_type IN ('item_rate', 'lump_sum', 'cost_plus'))
                AND (ld_pct_per_week IS NULL OR ld_pct_per_week BETWEEN 0 AND 100)
                AND (ld_cap_pct IS NULL OR ld_cap_pct BETWEEN 0 AND 100))
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE project_contracts
            DROP CONSTRAINT IF EXISTS ck_project_contract_setup,
            DROP COLUMN escalation_terms,
            DROP COLUMN escalation_applies,
            DROP COLUMN ld_cap_pct,
            DROP COLUMN ld_pct_per_week,
            DROP COLUMN contract_type,
            DROP COLUMN client_payment_days
    """)
    op.execute("""
        ALTER TABLE projects
            DROP CONSTRAINT IF EXISTS ck_projects_size,
            DROP COLUMN floors,
            DROP COLUMN built_up_area_sqft,
            DROP COLUMN project_type
    """)
