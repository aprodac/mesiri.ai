"""RA bills (NXT-02): the running-account bills a contractor sends the client, from the BOQ and measured work.

See docs/plans/next-modules-plan.md (client billing) and docs/plans/V1_TRACKER.md NXT-02. Additive only:

- ``ra_bills``: one per bill, numbered per project (RA-01, RA-02 ...), draft -> submitted -> certified (or
  cancelled). The contract's percentages (retention, advance recovery, GST, TDS) are copied onto the bill when it is
  made, so a later change to the contract never changes a bill already sent. Totals are stored when the bill is
  submitted; a draft's are worked out each time it is read.
- ``ra_bill_lines``: one per BOQ line on the bill: quantity measured to date and on earlier bills when the bill was
  made, this bill's quantity (suggested = measured − earlier; the office may change it before submitting, and the
  suggested quantity is kept to show the change), the client rate, the amount.

Tenant row-level security like 0522. Downgrade refuses while bills exist.

Revision ID: 0525
Revises: 0524
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "0525"
down_revision = "0524"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"
_TABLES = ("ra_bills", "ra_bill_lines")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ra_bills (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            number integer NOT NULL,
            status text NOT NULL DEFAULT 'draft',
            bill_date date NOT NULL,
            period_to date,
            client_id uuid REFERENCES clients(id) ON DELETE SET NULL,
            retention_pct numeric(5,2) NOT NULL DEFAULT 0,
            advance_recovery_pct numeric(5,2) NOT NULL DEFAULT 0,
            gst_pct numeric(5,2) NOT NULL DEFAULT 0,
            tds_pct numeric(5,2) NOT NULL DEFAULT 0,
            gross numeric(16,2),
            retention numeric(16,2),
            advance_recovery numeric(16,2),
            gst numeric(16,2),
            tds numeric(16,2),
            net numeric(16,2),
            certified_amount numeric(16,2),
            certified_on date,
            notes text,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            submitted_by uuid REFERENCES users(id) ON DELETE SET NULL,
            submitted_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_ra_bills_project_number UNIQUE (project_id, number),
            CONSTRAINT ck_ra_bills_status CHECK (status IN ('draft', 'submitted', 'certified', 'cancelled')),
            CONSTRAINT ck_ra_bills_pcts CHECK (retention_pct BETWEEN 0 AND 100 AND advance_recovery_pct BETWEEN 0 AND 100
                                               AND gst_pct BETWEEN 0 AND 100 AND tds_pct BETWEEN 0 AND 100),
            CONSTRAINT ck_ra_bills_certified CHECK (certified_amount IS NULL OR certified_amount >= 0)
        )""")
    # One draft per project at a time: the next bill's "earlier bills" must not depend on an unsent one.
    op.execute("CREATE UNIQUE INDEX uq_ra_bills_one_draft ON ra_bills (project_id) WHERE status = 'draft'")
    op.execute("""
        CREATE TABLE ra_bill_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            ra_bill_id uuid NOT NULL REFERENCES ra_bills(id) ON DELETE CASCADE,
            planned_item_id uuid NOT NULL REFERENCES work_package_planned_items(id) ON DELETE RESTRICT,
            boq_code text,
            work text NOT NULL,
            unit text NOT NULL,
            client_rate numeric(14,2) NOT NULL,
            measured_to_date numeric(14,3) NOT NULL DEFAULT 0,
            previous_quantity numeric(14,3) NOT NULL DEFAULT 0,
            suggested_quantity numeric(14,3) NOT NULL DEFAULT 0,
            quantity numeric(14,3) NOT NULL DEFAULT 0,
            sort_order integer NOT NULL DEFAULT 0,
            CONSTRAINT uq_ra_bill_lines_item UNIQUE (ra_bill_id, planned_item_id),
            CONSTRAINT ck_ra_bill_lines_qty CHECK (quantity >= 0 AND client_rate >= 0)
        )""")
    op.execute("CREATE INDEX ix_ra_bill_lines_item ON ra_bill_lines (planned_item_id)")
    op.execute("CREATE INDEX ix_ra_bills_org_project ON ra_bills (organization_id, project_id)")
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM ra_bills) THEN "
               "RAISE EXCEPTION 'RA bills exist; downgrading would lose them'; END IF; END $$")
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
