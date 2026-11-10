"""Accounts, Phases D and E (ACC-12, ACC-13, ACC-16, ACC-17): manual vouchers, bank statements, fixed assets, years.

See docs/plans/accounts-plan.md and docs/architecture/accounts-posting.md. Additive only: new tables, and one new
column with a default on ``accounting_settings`` (an Accounts table, 0532). No existing row is rewritten.

Every new table is a **source record** the posting sweep turns into journals, like an expense or a money movement,
never a journal itself: the books stay derived (they can be deleted and re-posted from the records), closed months
stay as they are (D-ACC2), and the bank and cash ledgers keep tying to Finance › Money by construction.

- ``account_vouchers`` / ``account_voucher_lines`` (ACC-12): a journal the accountant types (depreciation corrections,
  provisions, reclassifications). Posted or cancelled (with a reason); a cancelled voucher is taken out of the books
  by the sweep (after close: the difference on the first open day). No line may be a bank or cash ledger: money that
  moved is a movement in Finance › Money, so the books keep agreeing with it.
- ``bank_statements`` / ``bank_statement_lines`` (ACC-13): a bank statement imported for one money account, the
  column mapping it was read with (reused for that account's next statement), and each line: matched to a money
  movement already recorded, booked (a new movement made for it, e.g. bank charges, on the ledger chosen), ignored,
  or open. ``dedupe_key`` keeps a line imported twice (overlapping statements) from being counted twice.
  ``bank_bookings``: the ledger each booked movement was posted to, kept with the movement (not the line), so undoing
  a booking (a reversal in Finance) and booking the line again never relabels what was posted before. Its ``id`` is
  the movement's ``source_id`` (Finance allows one movement per source record, and a line may be booked twice).
- ``fixed_assets`` (ACC-16): the register. Cost (from an expense marked as a purchase of the asset, or an asset
  owned before the books start, at its written-down value), the method (WDV at Income-tax rates by default, D-ACC9;
  or SLM over a useful life), disposal. Depreciation is worked out by the sweep each year.
- ``accounting_years`` (ACC-17): a financial year closed (all its months closed, locked against reopening a month
  until the year is reopened, by the owner or an admin with a reason) and the balances it carried forward.
- ``accounting_settings.depreciation_method``: the company's default (``wdv`` or ``slm``).

Tenant row-level security like 0531. Downgrade refuses while any of these holds data.

Revision ID: 0544
Revises: 0543
Create Date: 2026-11-10
"""

from __future__ import annotations

from alembic import op

revision = "0544"
down_revision = "0543"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"
_TABLES = ("account_vouchers", "account_voucher_lines", "bank_statements", "bank_statement_lines", "bank_bookings",
           "fixed_assets", "accounting_years")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE account_vouchers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            voucher_date date NOT NULL,
            narration text NOT NULL,
            status text NOT NULL DEFAULT 'posted',
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_by uuid REFERENCES users(id) ON DELETE SET NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            cancelled_by uuid REFERENCES users(id) ON DELETE SET NULL,
            cancelled_at timestamptz,
            cancel_reason text,
            CONSTRAINT ck_account_vouchers_status CHECK (status IN ('posted', 'cancelled')),
            CONSTRAINT ck_account_vouchers_narration CHECK (btrim(narration) <> '')
        )""")
    op.execute("CREATE INDEX ix_account_vouchers_date ON account_vouchers (organization_id, voucher_date)")
    op.execute("""
        CREATE TABLE account_voucher_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            voucher_id uuid NOT NULL REFERENCES account_vouchers(id) ON DELETE CASCADE,
            line_no integer NOT NULL,
            ledger_id uuid NOT NULL REFERENCES ledgers(id),
            debit numeric(16, 2) NOT NULL DEFAULT 0,
            credit numeric(16, 2) NOT NULL DEFAULT 0,
            project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
            site_id uuid REFERENCES sites(id) ON DELETE SET NULL,
            cost_centre text,
            CONSTRAINT ck_account_voucher_lines_side CHECK (debit >= 0 AND credit >= 0 AND (debit = 0) <> (credit = 0))
        )""")
    op.execute("CREATE INDEX ix_account_voucher_lines_voucher ON account_voucher_lines (voucher_id)")

    op.execute("""
        CREATE TABLE bank_statements (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            money_account_id uuid NOT NULL REFERENCES money_accounts(id) ON DELETE CASCADE,
            file_name text,
            period_from date,
            period_to date,
            closing_balance numeric(16, 2),
            mapping jsonb NOT NULL DEFAULT '{}'::jsonb,
            lines integer NOT NULL DEFAULT 0,
            skipped integer NOT NULL DEFAULT 0,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX ix_bank_statements_account ON bank_statements (organization_id, money_account_id)")
    op.execute("""
        CREATE TABLE bank_statement_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            statement_id uuid NOT NULL REFERENCES bank_statements(id) ON DELETE CASCADE,
            money_account_id uuid NOT NULL REFERENCES money_accounts(id) ON DELETE CASCADE,
            line_no integer NOT NULL,
            line_date date NOT NULL,
            description text,
            reference text,
            amount numeric(16, 2) NOT NULL,
            balance numeric(16, 2),
            dedupe_key text NOT NULL,
            status text NOT NULL DEFAULT 'open',
            money_transaction_id uuid REFERENCES money_transactions(id) ON DELETE SET NULL,
            booked_ledger_id uuid REFERENCES ledgers(id),
            project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
            matched_by uuid REFERENCES users(id) ON DELETE SET NULL,
            matched_at timestamptz,
            CONSTRAINT ck_bank_statement_lines_status CHECK (status IN ('open', 'matched', 'booked', 'ignored')),
            CONSTRAINT ck_bank_statement_lines_amount CHECK (amount <> 0)
        )""")
    op.execute("CREATE UNIQUE INDEX uq_bank_statement_lines_dedupe ON bank_statement_lines "
               "(organization_id, money_account_id, dedupe_key)")
    op.execute("CREATE INDEX ix_bank_statement_lines_account ON bank_statement_lines "
               "(organization_id, money_account_id, line_date)")
    op.execute("CREATE UNIQUE INDEX uq_bank_statement_lines_money ON bank_statement_lines (money_transaction_id) "
               "WHERE money_transaction_id IS NOT NULL")

    op.execute("""
        CREATE TABLE bank_bookings (
            id uuid NOT NULL UNIQUE,
            money_transaction_id uuid PRIMARY KEY REFERENCES money_transactions(id) ON DELETE CASCADE,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            line_id uuid REFERENCES bank_statement_lines(id) ON DELETE SET NULL,
            ledger_id uuid NOT NULL REFERENCES ledgers(id),
            project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )""")

    op.execute("""
        CREATE TABLE fixed_assets (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name text NOT NULL,
            asset_class text NOT NULL,
            cost numeric(16, 2) NOT NULL,
            acquired_on date NOT NULL,
            put_to_use_on date,
            method text NOT NULL DEFAULT 'wdv',
            rate numeric(6, 2),
            useful_life_years numeric(6, 2),
            salvage_value numeric(16, 2) NOT NULL DEFAULT 0,
            opening_depreciation numeric(16, 2) NOT NULL DEFAULT 0,
            books_from date,
            expense_id uuid REFERENCES expenses(id) ON DELETE SET NULL,
            project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
            site_id uuid REFERENCES sites(id) ON DELETE SET NULL,
            disposed_on date,
            disposal_value numeric(16, 2),
            notes text,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_fixed_assets_name CHECK (btrim(name) <> ''),
            CONSTRAINT ck_fixed_assets_cost CHECK (cost > 0 AND opening_depreciation >= 0 AND opening_depreciation < cost
                AND salvage_value >= 0),
            CONSTRAINT ck_fixed_assets_method CHECK (method IN ('wdv', 'slm')),
            CONSTRAINT ck_fixed_assets_rate CHECK ((method = 'wdv' AND rate > 0 AND rate <= 100)
                OR (method = 'slm' AND useful_life_years > 0)),
            CONSTRAINT ck_fixed_assets_disposal CHECK ((disposed_on IS NULL) = (disposal_value IS NULL)
                AND (disposal_value IS NULL OR disposal_value >= 0))
        )""")
    op.execute("CREATE INDEX ix_fixed_assets_org ON fixed_assets (organization_id)")
    op.execute("CREATE UNIQUE INDEX uq_fixed_assets_expense ON fixed_assets (expense_id) WHERE expense_id IS NOT NULL")

    op.execute("""
        CREATE TABLE accounting_years (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            financial_year text NOT NULL,
            starts_on date NOT NULL,
            ends_on date NOT NULL,
            status text NOT NULL DEFAULT 'closed',
            closed_by uuid REFERENCES users(id) ON DELETE SET NULL,
            closed_at timestamptz,
            reopened_by uuid REFERENCES users(id) ON DELETE SET NULL,
            reopened_at timestamptz,
            reopen_reason text,
            snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_accounting_years_status CHECK (status IN ('open', 'closed')),
            CONSTRAINT uq_accounting_years UNIQUE (organization_id, financial_year)
        )""")

    op.execute("ALTER TABLE accounting_settings ADD COLUMN depreciation_method text NOT NULL DEFAULT 'wdv' "
               "CONSTRAINT ck_accounting_settings_depreciation CHECK (depreciation_method IN ('wdv', 'slm'))")

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM account_vouchers) OR EXISTS (SELECT 1 FROM bank_statements) "
               "OR EXISTS (SELECT 1 FROM fixed_assets) OR EXISTS (SELECT 1 FROM bank_bookings) OR EXISTS (SELECT 1 FROM accounting_years) THEN "
               "RAISE EXCEPTION 'Accounts records exist; downgrading would lose them'; END IF; END $$")
    op.execute("ALTER TABLE accounting_settings DROP COLUMN IF EXISTS depreciation_method")
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
