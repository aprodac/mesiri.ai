"""Project end (END-01..END-03): the snag list, payments received from the client, the handover day.

See docs/plans/project-end-plan.md. Additive only:

- ``projects.handed_over_on``: the day the work was handed to the client. With the contract's defect liability
  months (``project_contracts.defect_liability_months``, 0522) it gives the day the defect period ends, which is
  when the client's retention falls due.
- ``project_snags``: one defect to put right, numbered per project (SN-001 ...): where (a site, and the place in
  words: "Bedroom 2, near the door"), what, which trade or subcontractor fixes it, by when, who found it (our own
  walk-round or the client's). ``phase`` says whether it was raised before handover or in the defect period.
  open -> fixed (the site says it is done) -> closed (a manager checked it); a fix that is not good goes back to
  open with the reason.
- ``client_payments``: money in from the client: against an RA bill, as an advance, as retention released, or
  other; the day, amount, how (bank, cheque, UPI, cash) and the reference. What a client still owes is worked out
  from the bills and these, never stored.

Tenant row-level security like 0525. Downgrade refuses while snags or payments exist.

Revision ID: 0526
Revises: 0525
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "0526"
down_revision = "0525"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"
_TABLES = ("project_snags", "client_payments")


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN handed_over_on date")
    op.execute("""
        CREATE TABLE project_snags (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            site_id uuid REFERENCES sites(id) ON DELETE SET NULL,
            number integer NOT NULL,
            place text,
            description text NOT NULL,
            trade text,
            vendor_id uuid REFERENCES vendors(id) ON DELETE SET NULL,
            found_by text NOT NULL DEFAULT 'us',
            phase text NOT NULL DEFAULT 'before_handover',
            status text NOT NULL DEFAULT 'open',
            due_on date,
            fixed_note text,
            fixed_at timestamptz,
            fixed_by uuid REFERENCES users(id) ON DELETE SET NULL,
            closed_at timestamptz,
            closed_by uuid REFERENCES users(id) ON DELETE SET NULL,
            reopened_note text,
            raised_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_project_snags_number UNIQUE (project_id, number),
            CONSTRAINT ck_project_snags_status CHECK (status IN ('open', 'fixed', 'closed')),
            CONSTRAINT ck_project_snags_found_by CHECK (found_by IN ('us', 'client')),
            CONSTRAINT ck_project_snags_phase CHECK (phase IN ('before_handover', 'defects'))
        )""")
    op.execute("CREATE INDEX ix_project_snags_org_project ON project_snags (organization_id, project_id, status)")
    op.execute("""
        CREATE TABLE client_payments (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            client_id uuid REFERENCES clients(id) ON DELETE SET NULL,
            ra_bill_id uuid REFERENCES ra_bills(id) ON DELETE RESTRICT,
            kind text NOT NULL DEFAULT 'bill',
            received_on date NOT NULL,
            amount numeric(16,2) NOT NULL,
            mode text,
            reference text,
            notes text,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_client_payments_kind CHECK (kind IN ('bill', 'advance', 'retention', 'other')),
            CONSTRAINT ck_client_payments_amount CHECK (amount > 0),
            CONSTRAINT ck_client_payments_bill CHECK ((kind = 'bill') = (ra_bill_id IS NOT NULL))
        )""")
    op.execute("CREATE INDEX ix_client_payments_org_project ON client_payments (organization_id, project_id)")
    op.execute("CREATE INDEX ix_client_payments_bill ON client_payments (ra_bill_id)")
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM project_snags) OR EXISTS (SELECT 1 FROM client_payments) THEN "
               "RAISE EXCEPTION 'snags or client payments exist; downgrading would lose them'; END IF; END $$")
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS handed_over_on")
