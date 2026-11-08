"""Supplier ledger (CC-09, CC-10): what we owe each supplier, and paying them on account.

The ledger is a read model over what already exists (cost-control-plan D-CC3): priced deliveries not yet billed,
bills (expenses with the vendor), and payments (``expense_payments``). No ledger table. This migration adds only:

``vendors``
  - ``opening_balance`` / ``opening_balance_date``: what was owed (or, negative, paid ahead) before Mesiri.
  - ``credit_days``: days the supplier gives to pay; a bill's due date is its date plus these.
  - ``kind``: supplier / subcontractor / hire / service (NXT-05 and NXT-11 read it later).
  - ``contact_person``, ``notes``.

``expense_payments`` -- a payment can now be made to a supplier without a bill (an advance, or a payment against the
running balance), then applied to bills when they come:
  - ``expense_id`` may be null when ``vendor_id`` is set (an on-account payment: money left the account).
  - ``vendor_id``: the supplier an on-account payment went to.
  - ``project_id``: the project an on-account payment was for (optional; scopes it like an expense).
  - ``advance_id``: this row is part of an on-account payment applied to a bill. It moves no money (the advance
    already did): it only marks the bill paid by that much. Undoing it frees that part of the advance again.

Additive: new nullable columns, one NOT NULL relaxed, one check. Nothing existing is rewritten. Downgrade refuses
while on-account payments exist (dropping them would lose money movements).

Revision ID: 0516
Revises: 0515
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "0516"
down_revision = "0515"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE vendors "
        "ADD COLUMN opening_balance numeric(14,2), "
        "ADD COLUMN opening_balance_date date, "
        "ADD COLUMN credit_days integer, "
        "ADD COLUMN kind text NOT NULL DEFAULT 'supplier', "
        "ADD COLUMN contact_person text, "
        "ADD COLUMN notes text"
    )
    op.execute(
        "ALTER TABLE vendors ADD CONSTRAINT ck_vendors_kind "
        "CHECK (kind IN ('supplier', 'subcontractor', 'hire', 'service'))"
    )
    op.execute(
        "ALTER TABLE vendors ADD CONSTRAINT ck_vendors_credit_days CHECK (credit_days IS NULL OR credit_days BETWEEN 0 AND 365)"
    )

    op.execute("ALTER TABLE expense_payments ALTER COLUMN expense_id DROP NOT NULL")
    op.execute(
        "ALTER TABLE expense_payments "
        "ADD COLUMN vendor_id uuid REFERENCES vendors(id), "
        "ADD COLUMN project_id uuid REFERENCES projects(id), "
        "ADD COLUMN advance_id uuid REFERENCES expense_payments(id)"
    )
    op.execute(
        "ALTER TABLE expense_payments ADD CONSTRAINT ck_expense_payments_target "
        "CHECK (expense_id IS NOT NULL OR (vendor_id IS NOT NULL AND advance_id IS NULL))"
    )
    op.execute("CREATE INDEX ix_expense_payments_vendor_id ON expense_payments (vendor_id) WHERE vendor_id IS NOT NULL")
    op.execute("CREATE INDEX ix_expense_payments_advance_id ON expense_payments (advance_id) WHERE advance_id IS NOT NULL")


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM expense_payments WHERE expense_id IS NULL OR advance_id IS NOT NULL) "
        "THEN RAISE EXCEPTION 'on-account supplier payments exist; downgrading would lose them'; END IF; END $$"
    )
    op.execute("DROP INDEX IF EXISTS ix_expense_payments_advance_id")
    op.execute("DROP INDEX IF EXISTS ix_expense_payments_vendor_id")
    op.execute("ALTER TABLE expense_payments DROP CONSTRAINT IF EXISTS ck_expense_payments_target")
    op.execute(
        "ALTER TABLE expense_payments DROP COLUMN IF EXISTS advance_id, DROP COLUMN IF EXISTS project_id, "
        "DROP COLUMN IF EXISTS vendor_id"
    )
    op.execute("ALTER TABLE expense_payments ALTER COLUMN expense_id SET NOT NULL")
    op.execute("ALTER TABLE vendors DROP CONSTRAINT IF EXISTS ck_vendors_credit_days")
    op.execute("ALTER TABLE vendors DROP CONSTRAINT IF EXISTS ck_vendors_kind")
    op.execute(
        "ALTER TABLE vendors DROP COLUMN IF EXISTS notes, DROP COLUMN IF EXISTS contact_person, "
        "DROP COLUMN IF EXISTS kind, DROP COLUMN IF EXISTS credit_days, DROP COLUMN IF EXISTS opening_balance_date, "
        "DROP COLUMN IF EXISTS opening_balance"
    )
