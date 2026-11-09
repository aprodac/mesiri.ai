"""Accounts settings (ACC-23): how head-office costs are shared over projects, per company.

``accounting_settings``: one row per company. ``overhead_basis``: NULL (off, the default, D-ACC11), ``cost`` (each
project's share of the month's head-office costs by its cost that month) or ``billing`` (by what it billed).
``head_office_project_id``: the project the office's own costs are recorded on (every expense has a project), shared
out with whatever has no project. Additive;
tenant row-level security like 0531. Downgrade drops the table (a setting only; the allocation journals are derived
and taken back by the next posting once the setting is gone).

Revision ID: 0532
Revises: 0531
Create Date: 2026-11-09
"""

from __future__ import annotations

from alembic import op

revision = "0532"
down_revision = "0531"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE accounting_settings (
            organization_id uuid PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
            overhead_basis text,
            head_office_project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
            updated_by uuid REFERENCES users(id) ON DELETE SET NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_accounting_settings_basis CHECK (overhead_basis IS NULL OR overhead_basis IN ('cost', 'billing'))
        )""")
    op.execute("ALTER TABLE accounting_settings ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON accounting_settings USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS accounting_settings")
