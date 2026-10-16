"""Row-level security on every company table (BE-03 step 2).

A transaction that has `mesiri.organization_id` set (postgres/tenant.py,
BE-03 step 1: every dashboard request and WhatsApp message once its company
is known) sees and writes only that company's rows. A transaction with
nothing set -- the automation runner, the webhook finding a sender by phone,
login, the control panel, workers, migrations -- is unchanged. Making
"nothing set" mean "nothing visible" is a later item.

Takes effect only for a login that is neither superuser nor table owner:
the app's `mesiri_app` login (BE-03 step 3). Until then this changes
nothing in production.

- `mesiri_tenant()`: the company set on the transaction, or NULL.
- One policy per table, for reads and writes alike. Writes are checked too
  (WITH CHECK), so a row can't be inserted into, or moved to, another
  company.
- `admin_audit_log`, `inbound_messages`, `provider_executions` and `users`
  allow organization_id to be empty (platform rows, unknown senders): such
  rows are hidden from a company, but a company-scoped transaction may still
  write one.
- `organizations` is the company itself: its own row only.
- Child tables without organization_id (attendance lines, report versions,
  photos, project members...) are reached through their parent rows; they
  get no policy here.
- Indexes on organization_id for the six company tables that had none, as
  every scoped query now filters on it.

Revision ID: 0484
Revises: 0483
Create Date: 2026-10-16
"""

from __future__ import annotations

from alembic import op

revision = "0484"
down_revision = "0483"
branch_labels = None
depends_on = None

POLICY = "tenant_isolation"

TABLES = (
    "activities",
    "automations",
    "budgets",
    "daily_reports",
    "equipment_events",
    "escalations",
    "expense_categories",
    "expense_payments",
    "expenses",
    "extractions",
    "fact_reviews",
    "labour_attendance",
    "labour_attendance_reports",
    "late_entries",
    "location_nodes",
    "material_invoices",
    "material_movements",
    "material_receipts",
    "material_usage",
    "materials_catalog",
    "money_accounts",
    "money_transactions",
    "notifications",
    "organization_settings",
    "projects",
    "report_recipients",
    "site_issues",
    "sites",
    "timeline_entries",
    "vendors",
    "whatsapp_opt_ins",
    "work_packages",
    "workflow_instances",
    "workforce_workers",
)

# organization_id may be empty: hidden from a company, still writable.
NULLABLE_TABLES = ("admin_audit_log", "inbound_messages", "provider_executions", "users")

UNINDEXED = (
    "daily_reports",
    "extractions",
    "location_nodes",
    "report_recipients",
    "work_packages",
    "workflow_instances",
)

_TENANT = "mesiri_tenant()"
_UNSET = f"{_TENANT} IS NULL"


def _policy(table: str, using: str, check: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {POLICY} ON {table} USING ({using}) WITH CHECK ({check})")


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION mesiri_tenant() RETURNS uuid
        LANGUAGE sql STABLE PARALLEL SAFE AS $$
            SELECT NULLIF(current_setting('mesiri.organization_id', true), '')::uuid
        $$
        """
    )
    for table in TABLES:
        rule = f"{_UNSET} OR organization_id = {_TENANT}"
        _policy(table, rule, rule)
    for table in NULLABLE_TABLES:
        _policy(
            table,
            f"{_UNSET} OR organization_id = {_TENANT}",
            f"{_UNSET} OR organization_id IS NULL OR organization_id = {_TENANT}",
        )
    rule = f"{_UNSET} OR id = {_TENANT}"
    _policy("organizations", rule, rule)
    for table in UNINDEXED:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_organization_id ON {table} (organization_id)"
        )


def downgrade() -> None:
    for table in UNINDEXED:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_organization_id")
    for table in (*TABLES, *NULLABLE_TABLES, "organizations"):
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS mesiri_tenant()")
