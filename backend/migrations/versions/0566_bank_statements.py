"""ACC-13 / FB-03: bank statements imported and matched to the books.

Asked in the contractor session (21 Nov 2026): "bank sync, so the accountant only enters the small petty-cash ones".
A live bank feed needs a bank partner; this is the statement import (CSV from net banking) and the matching.

Additive only:

- ``bank_statement_imports``: one per file imported into a money account (who, when, the dates it covers).
- ``bank_statement_lines``: each line of the statement: date, the bank's words, reference, amount (+ money in,
  - money out), the balance after it when the bank gives one. ``line_key`` (date, amount, words, reference, balance)
  is unique per account, so importing an overlapping statement again adds only the new lines.
  A line is ``unmatched``, ``matched`` to a book entry, or ``ignored`` (with a reason). A match names the book entry
  by its source (``source_kind``, ``source_id``, ``source_part``: what the sweep keys an entry on, so a re-post keeps
  the match) and by ``entry_id`` (a manual voucher, which is never re-posted).

Revision ID: 0566
Revises: 0565
Create Date: 2026-11-21
"""

from __future__ import annotations

from alembic import op

revision = "0566"
down_revision = "0565"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"
_TABLES = ("bank_statement_imports", "bank_statement_lines")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE bank_statement_imports (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            account_id uuid NOT NULL REFERENCES money_accounts(id) ON DELETE CASCADE,
            file_name text,
            from_date date,
            to_date date,
            lines_added integer NOT NULL DEFAULT 0,
            lines_repeated integer NOT NULL DEFAULT 0,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE bank_statement_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            account_id uuid NOT NULL REFERENCES money_accounts(id) ON DELETE CASCADE,
            import_id uuid NOT NULL REFERENCES bank_statement_imports(id) ON DELETE CASCADE,
            txn_date date NOT NULL,
            description text NOT NULL DEFAULT '',
            reference text,
            amount numeric(16,2) NOT NULL,
            balance numeric(16,2),
            line_key text NOT NULL,
            status text NOT NULL DEFAULT 'unmatched',
            source_kind text,
            source_id uuid,
            source_part text,
            entry_id uuid,
            matched_how text,
            note text,
            decided_by uuid REFERENCES users(id) ON DELETE SET NULL,
            decided_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_bank_lines_amount CHECK (amount <> 0),
            CONSTRAINT ck_bank_lines_status CHECK (status IN ('unmatched', 'matched', 'ignored')),
            CONSTRAINT ck_bank_lines_how CHECK (matched_how IS NULL OR matched_how IN ('auto', 'manual', 'booked')),
            CONSTRAINT ck_bank_lines_match CHECK (status <> 'matched' OR entry_id IS NOT NULL),
            CONSTRAINT uq_bank_lines_key UNIQUE (account_id, line_key)
        )""")
    op.execute("CREATE INDEX ix_bank_lines_account_date ON bank_statement_lines (organization_id, account_id, txn_date)")
    op.execute("CREATE INDEX ix_bank_lines_source ON bank_statement_lines (source_kind, source_id) "
               "WHERE status = 'matched'")
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
