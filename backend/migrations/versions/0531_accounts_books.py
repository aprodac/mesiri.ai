"""Accounts, Phase A (ACC-01..ACC-05): chart of accounts, months, journals.

See docs/plans/accounts-plan.md. Additive only; no existing table changes.

- ``ledger_groups``: the chart's tree (Tally's primary groups, seeded per company on first use by
  ``domains/accounts/chart.py``), each with its ``nature`` (asset, liability, equity, income, expense). ``code`` is
  the system key of a seeded group (stable however the company renames it).
- ``ledgers``: an account in a group. ``code``: the system key of a seeded ledger (Contract revenue, Input GST ...).
  ``link_kind`` + ``link_id``: the record a ledger stands for (a supplier, client, money account, expense category,
  or a member of staff owed what they paid), made by the posting sweep, never typed. One ledger per link.
- ``accounting_periods``: months, ``open`` or ``closed`` (who, when, and the reason a month was reopened).
- ``journal_entries`` / ``journal_lines``: the books. An entry is made from a source record (``source_kind`` +
  ``source_id``, with the ``fingerprint`` of what was posted) by the posting sweep; ``after_close`` marks the
  difference posted on the first open day when a record changed after its month was closed (D-ACC2). A line is a
  debit or a credit (never both, never negative) on a ledger, with the project, site and cost centre it belongs to.
  **Every entry balances**: a deferred constraint trigger checks debits = credits per entry at commit.

Tenant row-level security like 0529. Downgrade refuses while journals exist (they can be re-posted from the source
records, but a closed month's history would be lost).

Revision ID: 0531
Revises: 0530
Create Date: 2026-11-09
"""

from __future__ import annotations

from alembic import op

revision = "0531"
down_revision = "0530"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"
_TABLES = ("ledger_groups", "ledgers", "accounting_periods", "journal_entries", "journal_lines")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ledger_groups (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            parent_id uuid REFERENCES ledger_groups(id),  -- NO ACTION: a company deleted takes its chart with it
            name text NOT NULL,
            nature text NOT NULL,
            code text,
            sort integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_ledger_groups_nature CHECK (nature IN ('asset', 'liability', 'equity', 'income', 'expense')),
            CONSTRAINT ck_ledger_groups_name CHECK (btrim(name) <> '')
        )""")
    op.execute("CREATE UNIQUE INDEX uq_ledger_groups_name ON ledger_groups (organization_id, lower(btrim(name)))")
    op.execute("CREATE UNIQUE INDEX uq_ledger_groups_code ON ledger_groups (organization_id, code) WHERE code IS NOT NULL")

    op.execute("""
        CREATE TABLE ledgers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            group_id uuid NOT NULL REFERENCES ledger_groups(id),
            name text NOT NULL,
            code text,
            link_kind text,
            link_id uuid,
            notes text,
            is_active boolean NOT NULL DEFAULT true,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_ledgers_name CHECK (btrim(name) <> ''),
            CONSTRAINT ck_ledgers_link CHECK ((link_kind IS NULL) = (link_id IS NULL)),
            CONSTRAINT ck_ledgers_link_kind CHECK (link_kind IS NULL OR link_kind IN
                ('vendor', 'client', 'money_account', 'expense_category', 'staff'))
        )""")
    op.execute("CREATE UNIQUE INDEX uq_ledgers_code ON ledgers (organization_id, code) WHERE code IS NOT NULL")
    op.execute("CREATE UNIQUE INDEX uq_ledgers_link ON ledgers (organization_id, link_kind, link_id) WHERE link_kind IS NOT NULL")
    op.execute("CREATE INDEX ix_ledgers_group ON ledgers (group_id)")

    op.execute("""
        CREATE TABLE accounting_periods (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            starts_on date NOT NULL,
            ends_on date NOT NULL,
            status text NOT NULL DEFAULT 'open',
            closed_by uuid REFERENCES users(id) ON DELETE SET NULL,
            closed_at timestamptz,
            reopened_by uuid REFERENCES users(id) ON DELETE SET NULL,
            reopened_at timestamptz,
            reopen_reason text,
            CONSTRAINT ck_accounting_periods_status CHECK (status IN ('open', 'closed')),
            CONSTRAINT ck_accounting_periods_dates CHECK (ends_on >= starts_on),
            CONSTRAINT uq_accounting_periods_month UNIQUE (organization_id, starts_on)
        )""")

    op.execute("""
        CREATE TABLE journal_entries (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            entry_date date NOT NULL,
            voucher_type text NOT NULL,
            financial_year text NOT NULL,
            number integer NOT NULL,
            narration text,
            source_kind text NOT NULL,
            source_id uuid,
            source_part text NOT NULL DEFAULT 'main',
            fingerprint text,
            after_close boolean NOT NULL DEFAULT false,
            project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_journal_entries_type CHECK (voucher_type IN
                ('journal', 'payment', 'receipt', 'contra', 'sales', 'purchase')),
            CONSTRAINT uq_journal_entries_number UNIQUE (organization_id, voucher_type, financial_year, number)
        )""")
    op.execute("CREATE INDEX ix_journal_entries_source ON journal_entries (organization_id, source_kind, source_id)")
    op.execute("CREATE INDEX ix_journal_entries_date ON journal_entries (organization_id, entry_date)")

    op.execute("""
        CREATE TABLE journal_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            entry_id uuid NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
            line_no integer NOT NULL,
            entry_date date NOT NULL,
            ledger_id uuid NOT NULL REFERENCES ledgers(id),
            debit numeric(16, 2) NOT NULL DEFAULT 0,
            credit numeric(16, 2) NOT NULL DEFAULT 0,
            project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
            site_id uuid REFERENCES sites(id) ON DELETE SET NULL,
            cost_centre text,
            CONSTRAINT ck_journal_lines_side CHECK (debit >= 0 AND credit >= 0 AND (debit = 0) <> (credit = 0))
        )""")
    op.execute("CREATE INDEX ix_journal_lines_entry ON journal_lines (entry_id)")
    op.execute("CREATE INDEX ix_journal_lines_ledger ON journal_lines (organization_id, ledger_id, entry_date)")
    op.execute("CREATE INDEX ix_journal_lines_project ON journal_lines (organization_id, project_id, entry_date)")

    # Every entry balances, checked at commit (lines are written one by one inside the transaction).
    op.execute("""
        CREATE FUNCTION journal_entry_balances() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE e uuid := COALESCE(NEW.entry_id, OLD.entry_id); d numeric; c numeric; n integer;
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM journal_entries WHERE id = e) THEN RETURN NULL; END IF;
            SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0), COUNT(*) INTO d, c, n
              FROM journal_lines WHERE entry_id = e;
            IF n = 0 THEN RETURN NULL; END IF;
            IF d <> c THEN
                RAISE EXCEPTION 'journal entry % does not balance: debit % credit %', e, d, c
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END $$""")
    op.execute("""
        CREATE CONSTRAINT TRIGGER tr_journal_entry_balances AFTER INSERT OR UPDATE OR DELETE ON journal_lines
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION journal_entry_balances()""")

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM journal_entries) THEN "
               "RAISE EXCEPTION 'Journals exist; downgrading would lose the books'; END IF; END $$")
    op.execute("DROP TRIGGER IF EXISTS tr_journal_entry_balances ON journal_lines")
    op.execute("DROP FUNCTION IF EXISTS journal_entry_balances()")
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
