"""Labour, wages and advances (LW-01, LW-03, LW-04, LW-05; plan docs/plans/wages-and-labour-plan.md, approved by Ilan
in session 9 Nov 2026 with defaults D-W1..D-W7).

Additive only:

- ``workforce_workers`` + phone, home project and site, team (``vendor_id``: a labour contractor is a vendor),
  wage basis (day / month), joined and left dates.
- ``vendors.kind`` may be ``labour`` (a labour contractor's team).
- ``labour_advances``: money given ahead of wages to a worker, a team or a named person, out of a money account.
- ``wage_sheets`` / ``wage_sheet_rows``: a site's (or project's) pay period: one row per payee with the days from
  attendance, gross, overtime, advances recovered, deductions and net; draft -> approved.
- ``wage_payments``: what was paid against a row, from which money account.

Tenant row-level security like 0527. Downgrade refuses while any of these hold data.

Revision ID: 0535
Revises: 0534
Create Date: 2026-11-09
"""

from __future__ import annotations

from alembic import op

revision = "0535"
down_revision = "0534"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")


def upgrade() -> None:
    op.execute("""
        ALTER TABLE workforce_workers
            ADD COLUMN phone text,
            ADD COLUMN project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
            ADD COLUMN site_id uuid REFERENCES sites(id) ON DELETE SET NULL,
            ADD COLUMN vendor_id uuid REFERENCES vendors(id) ON DELETE SET NULL,
            ADD COLUMN wage_basis text NOT NULL DEFAULT 'day',
            ADD COLUMN joined_on date,
            ADD COLUMN left_on date,
            ADD CONSTRAINT ck_workforce_workers_wage_basis CHECK (wage_basis IN ('day', 'month'))""")
    op.execute("CREATE INDEX ix_workforce_workers_vendor ON workforce_workers (vendor_id) WHERE vendor_id IS NOT NULL")

    op.execute("ALTER TABLE vendors DROP CONSTRAINT IF EXISTS ck_vendors_kind")
    op.execute("ALTER TABLE vendors ADD CONSTRAINT ck_vendors_kind "
               "CHECK (kind IN ('supplier', 'subcontractor', 'hire', 'service', 'labour'))")

    op.execute("""
        CREATE TABLE labour_advances (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            site_id uuid REFERENCES sites(id) ON DELETE SET NULL,
            worker_id uuid REFERENCES workforce_workers(id) ON DELETE SET NULL,
            vendor_id uuid REFERENCES vendors(id) ON DELETE SET NULL,
            payee_name text NOT NULL,
            amount numeric(14, 2) NOT NULL,
            given_on date NOT NULL,
            account_id uuid REFERENCES money_accounts(id) ON DELETE SET NULL,
            note text,
            source text NOT NULL DEFAULT 'web',
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            voided_at timestamptz,
            voided_by uuid REFERENCES users(id) ON DELETE SET NULL,
            void_reason text,
            CONSTRAINT ck_labour_advances_amount CHECK (amount > 0),
            CONSTRAINT ck_labour_advances_source CHECK (source IN ('web', 'whatsapp')),
            CONSTRAINT ck_labour_advances_one_payee CHECK (worker_id IS NULL OR vendor_id IS NULL)
        )""")
    op.execute("CREATE INDEX ix_labour_advances_org_project ON labour_advances (organization_id, project_id, given_on)")
    _rls("labour_advances")

    op.execute("""
        CREATE TABLE wage_sheets (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            site_id uuid REFERENCES sites(id) ON DELETE CASCADE,
            period_from date NOT NULL,
            period_to date NOT NULL,
            status text NOT NULL DEFAULT 'draft',
            approved_by uuid REFERENCES users(id) ON DELETE SET NULL,
            approved_at timestamptz,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_wage_sheets_period CHECK (period_to >= period_from),
            CONSTRAINT ck_wage_sheets_status CHECK (status IN ('draft', 'approved'))
        )""")
    op.execute("CREATE UNIQUE INDEX uq_wage_sheets_period ON wage_sheets "
               "(project_id, COALESCE(site_id, '00000000-0000-0000-0000-000000000000'::uuid), period_from, period_to)")
    _rls("wage_sheets")

    op.execute("""
        CREATE TABLE wage_sheet_rows (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            sheet_id uuid NOT NULL REFERENCES wage_sheets(id) ON DELETE CASCADE,
            payee_key text NOT NULL,
            worker_id uuid REFERENCES workforce_workers(id) ON DELETE SET NULL,
            vendor_id uuid REFERENCES vendors(id) ON DELETE SET NULL,
            payee_name text NOT NULL,
            trades text,
            days numeric(10, 2) NOT NULL DEFAULT 0,
            man_days numeric(10, 2) NOT NULL DEFAULT 0,
            unpriced_man_days numeric(10, 2) NOT NULL DEFAULT 0,
            overtime_hours numeric(10, 2) NOT NULL DEFAULT 0,
            gross numeric(14, 2) NOT NULL DEFAULT 0,
            overtime_amount numeric(14, 2) NOT NULL DEFAULT 0,
            advances_recovered numeric(14, 2) NOT NULL DEFAULT 0,
            recovery_set boolean NOT NULL DEFAULT false,
            deductions jsonb NOT NULL DEFAULT '[]'::jsonb,
            net numeric(14, 2) NOT NULL DEFAULT 0,
            paid numeric(14, 2) NOT NULL DEFAULT 0,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_wage_sheet_rows_payee UNIQUE (sheet_id, payee_key)
        )""")
    _rls("wage_sheet_rows")

    op.execute("""
        CREATE TABLE wage_payments (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            sheet_id uuid NOT NULL REFERENCES wage_sheets(id) ON DELETE CASCADE,
            row_id uuid NOT NULL REFERENCES wage_sheet_rows(id) ON DELETE CASCADE,
            amount numeric(14, 2) NOT NULL,
            paid_on date NOT NULL,
            account_id uuid REFERENCES money_accounts(id) ON DELETE SET NULL,
            note text,
            source text NOT NULL DEFAULT 'web',
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_wage_payments_amount CHECK (amount > 0),
            CONSTRAINT ck_wage_payments_source CHECK (source IN ('web', 'whatsapp'))
        )""")
    op.execute("CREATE INDEX ix_wage_payments_row ON wage_payments (row_id)")
    _rls("wage_payments")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM labour_advances) OR EXISTS (SELECT 1 FROM wage_sheets) "
               "OR EXISTS (SELECT 1 FROM vendors WHERE kind = 'labour') THEN "
               "RAISE EXCEPTION 'Wages, advances or labour teams exist; downgrading would lose them'; END IF; END $$")
    op.execute("DROP TABLE IF EXISTS wage_payments")
    op.execute("DROP TABLE IF EXISTS wage_sheet_rows")
    op.execute("DROP TABLE IF EXISTS wage_sheets")
    op.execute("DROP TABLE IF EXISTS labour_advances")
    op.execute("ALTER TABLE vendors DROP CONSTRAINT IF EXISTS ck_vendors_kind")
    op.execute("ALTER TABLE vendors ADD CONSTRAINT ck_vendors_kind "
               "CHECK (kind IN ('supplier', 'subcontractor', 'hire', 'service'))")
    op.execute("DROP INDEX IF EXISTS ix_workforce_workers_vendor")
    op.execute("ALTER TABLE workforce_workers DROP CONSTRAINT IF EXISTS ck_workforce_workers_wage_basis, "
               "DROP COLUMN IF EXISTS phone, DROP COLUMN IF EXISTS project_id, DROP COLUMN IF EXISTS site_id, "
               "DROP COLUMN IF EXISTS vendor_id, DROP COLUMN IF EXISTS wage_basis, DROP COLUMN IF EXISTS joined_on, "
               "DROP COLUMN IF EXISTS left_on")
