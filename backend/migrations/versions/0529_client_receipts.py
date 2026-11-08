"""Money received from clients (NXT-03).

See docs/plans/next-modules-plan.md (NXT-03). Additive only:

- ``client_receipts``: one row per amount a client paid, into a company account (``money_accounts``), on a day.
  ``kind``: ``bill`` (against one RA bill, ``ra_bill_id``), ``on_account`` (a part payment not tied to a bill: it
  settles the client's oldest open bills first), or ``advance`` (a mobilisation advance: never applied to bills,
  because each bill recovers it through its own advance-recovery deduction). ``status`` ``cancelled`` takes a
  receipt back without deleting it (who and when kept). A bill with receipts cannot be deleted (RESTRICT): only
  drafts are deleted, and a draft cannot be paid.

Tenant row-level security like 0528. Downgrade refuses while receipts exist.

Revision ID: 0529
Revises: 0528
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "0529"
down_revision = "0528"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE client_receipts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            client_id uuid REFERENCES clients(id) ON DELETE SET NULL,
            ra_bill_id uuid REFERENCES ra_bills(id) ON DELETE RESTRICT,
            kind text NOT NULL DEFAULT 'bill',
            amount numeric(16, 2) NOT NULL,
            received_on date NOT NULL,
            account_id uuid NOT NULL REFERENCES money_accounts(id),
            method text,
            reference text,
            notes text,
            status text NOT NULL DEFAULT 'confirmed',
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            cancelled_by uuid REFERENCES users(id) ON DELETE SET NULL,
            cancelled_at timestamptz,
            CONSTRAINT ck_client_receipts_amount CHECK (amount > 0),
            CONSTRAINT ck_client_receipts_kind CHECK (kind IN ('bill', 'on_account', 'advance')),
            CONSTRAINT ck_client_receipts_bill CHECK ((kind = 'bill') = (ra_bill_id IS NOT NULL)),
            CONSTRAINT ck_client_receipts_status CHECK (status IN ('confirmed', 'cancelled'))
        )""")
    op.execute("CREATE INDEX ix_client_receipts_org_project ON client_receipts (organization_id, project_id, received_on)")
    op.execute("CREATE INDEX ix_client_receipts_bill ON client_receipts (ra_bill_id) WHERE ra_bill_id IS NOT NULL")
    op.execute("ALTER TABLE client_receipts ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON client_receipts USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM client_receipts) THEN "
               "RAISE EXCEPTION 'Client receipts exist; downgrading would lose them'; END IF; END $$")
    op.execute("DROP TABLE IF EXISTS client_receipts")
