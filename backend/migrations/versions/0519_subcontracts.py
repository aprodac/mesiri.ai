"""Subcontracts (NXT-05/06/07, CC-04): work orders, measurement, bills checked against both, retention / advance / TDS.

See docs/plans/subcontractors-plan.md (S1-S4). Additive only:

- ``work_orders`` (WO-0001...): a subcontractor (vendor), project, optional site, dates, retention %, defect days,
  advance agreed and its recovery %, TDS %, their reference, terms; status draft / issued / completed / closed /
  cancelled. ``work_order_lines``: a BOQ line (``planned_item_id``) or free text, unit, quantity, agreed rate.
  ``work_order_events``: history.
- ``work_order_measurements``: work done on a line (measured, reported on site, or proposed by the subcontractor and
  confirmed by staff). ``activity_quantities.work_order_line_id`` / ``planned_item_id``: a work update counted on a line.
- ``work_order_bills`` (one per subcontractor bill, its expense) with ``work_order_bill_lines``: what was billed per
  line, the check (status, flags), and the deductions (retention, advance recovered, TDS, net payable).
- ``expense_payments.work_order_id``: an advance given against a work order. ``vendors.tds_pct``: the subcontractor's
  TDS rate. ``labour_attendance_lines.vendor_id``: the subcontractor whose team it was (Labour, additive).

Every new table has row-level security like 0511. Downgrade refuses while work orders exist.

Revision ID: 0519
Revises: 0518
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "0519"
down_revision = "0518"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"
_TABLES = ("work_orders", "work_order_lines", "work_order_events", "work_order_measurements", "work_order_bills",
           "work_order_bill_lines")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE work_orders (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            number integer NOT NULL,
            vendor_id uuid NOT NULL REFERENCES vendors(id),
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            site_id uuid REFERENCES sites(id) ON DELETE SET NULL,
            title text,
            status text NOT NULL DEFAULT 'draft',
            start_date date,
            end_date date,
            retention_pct numeric(5,2) NOT NULL DEFAULT 5,
            defect_days integer NOT NULL DEFAULT 0,
            advance_agreed numeric(14,2),
            advance_recovery_pct numeric(5,2),
            tds_pct numeric(5,2),
            their_ref text,
            terms text,
            notes text,
            status_note text,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            issued_at timestamptz,
            completed_on date,
            CONSTRAINT uq_work_orders_number UNIQUE (organization_id, number),
            CONSTRAINT ck_work_orders_status CHECK (status IN ('draft', 'issued', 'completed', 'closed', 'cancelled')),
            CONSTRAINT ck_work_orders_pct CHECK (retention_pct BETWEEN 0 AND 50
                AND (advance_recovery_pct IS NULL OR advance_recovery_pct BETWEEN 0 AND 100)
                AND (tds_pct IS NULL OR tds_pct BETWEEN 0 AND 20))
        )""")
    op.execute("CREATE INDEX ix_work_orders_vendor ON work_orders (organization_id, vendor_id)")
    op.execute("CREATE INDEX ix_work_orders_project ON work_orders (organization_id, project_id, status)")
    op.execute("""
        CREATE TABLE work_order_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            work_order_id uuid NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
            planned_item_id uuid REFERENCES work_package_planned_items(id) ON DELETE SET NULL,
            description text NOT NULL,
            unit text NOT NULL,
            quantity numeric(14,3) NOT NULL,
            rate numeric(14,2) NOT NULL,
            position integer NOT NULL DEFAULT 0,
            CONSTRAINT ck_work_order_lines CHECK (quantity > 0 AND rate >= 0)
        )""")
    op.execute("CREATE INDEX ix_work_order_lines_wo ON work_order_lines (work_order_id)")
    op.execute("""
        CREATE TABLE work_order_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            work_order_id uuid NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
            kind text NOT NULL,
            what text NOT NULL,
            by_user uuid REFERENCES users(id) ON DELETE SET NULL,
            by_name text,
            at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX ix_work_order_events_wo ON work_order_events (work_order_id, at)")
    op.execute("""
        CREATE TABLE work_order_measurements (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            work_order_id uuid NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
            line_id uuid NOT NULL REFERENCES work_order_lines(id) ON DELETE CASCADE,
            measured_on date NOT NULL,
            quantity numeric(14,3) NOT NULL,
            notes text,
            photo_key text,
            status text NOT NULL DEFAULT 'confirmed',
            source text NOT NULL DEFAULT 'web',
            activity_quantity_id uuid REFERENCES activity_quantities(id) ON DELETE SET NULL,
            recorded_by uuid REFERENCES users(id) ON DELETE SET NULL,
            recorded_by_name text,
            decided_by uuid REFERENCES users(id) ON DELETE SET NULL,
            decided_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_wo_measure CHECK (quantity > 0 AND status IN ('confirmed', 'proposed', 'rejected', 'removed'))
        )""")
    op.execute("CREATE INDEX ix_wo_measure_line ON work_order_measurements (line_id, status)")
    op.execute("CREATE UNIQUE INDEX uq_wo_measure_activity ON work_order_measurements (activity_quantity_id) "
               "WHERE activity_quantity_id IS NOT NULL AND status <> 'removed'")
    op.execute("""
        CREATE TABLE work_order_bills (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            work_order_id uuid NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
            expense_id uuid NOT NULL UNIQUE REFERENCES expenses(id),
            number integer NOT NULL,
            their_bill_no text,
            bill_date date NOT NULL,
            gross numeric(14,2) NOT NULL,
            check_status text NOT NULL DEFAULT 'waiting',
            flags jsonb NOT NULL DEFAULT '[]'::jsonb,
            retention_amount numeric(14,2) NOT NULL DEFAULT 0,
            retention_released numeric(14,2) NOT NULL DEFAULT 0,
            advance_recovered numeric(14,2) NOT NULL DEFAULT 0,
            tds_pct numeric(5,2),
            tds_amount numeric(14,2) NOT NULL DEFAULT 0,
            net_payable numeric(14,2),
            decided_by uuid REFERENCES users(id) ON DELETE SET NULL,
            decided_at timestamptz,
            decision_reason text,
            submitted_by uuid REFERENCES users(id) ON DELETE SET NULL,
            submitted_by_contact uuid,
            source text NOT NULL DEFAULT 'web',
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_wo_bill_number UNIQUE (work_order_id, number),
            CONSTRAINT ck_wo_bill_status CHECK (check_status IN ('waiting', 'passed', 'flagged', 'approved', 'rejected'))
        )""")
    op.execute("CREATE INDEX ix_wo_bills_wo ON work_order_bills (work_order_id)")
    op.execute("""
        CREATE TABLE work_order_bill_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            bill_id uuid NOT NULL REFERENCES work_order_bills(id) ON DELETE CASCADE,
            line_id uuid NOT NULL REFERENCES work_order_lines(id) ON DELETE CASCADE,
            quantity numeric(14,3) NOT NULL,
            rate numeric(14,2) NOT NULL,
            CONSTRAINT ck_wo_bill_line CHECK (quantity > 0 AND rate >= 0)
        )""")
    op.execute("CREATE INDEX ix_wo_bill_lines_bill ON work_order_bill_lines (bill_id)")
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")
    op.execute("ALTER TABLE expense_payments ADD COLUMN work_order_id uuid REFERENCES work_orders(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE vendors ADD COLUMN tds_pct numeric(5,2)")
    op.execute("ALTER TABLE activity_quantities ADD COLUMN planned_item_id uuid REFERENCES work_package_planned_items(id) "
               "ON DELETE SET NULL, ADD COLUMN work_order_line_id uuid REFERENCES work_order_lines(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE labour_attendance_lines ADD COLUMN vendor_id uuid REFERENCES vendors(id) ON DELETE SET NULL")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM work_orders) THEN "
               "RAISE EXCEPTION 'work orders exist; downgrading would lose them'; END IF; END $$")
    op.execute("ALTER TABLE labour_attendance_lines DROP COLUMN IF EXISTS vendor_id")
    op.execute("ALTER TABLE activity_quantities DROP COLUMN IF EXISTS work_order_line_id, DROP COLUMN IF EXISTS planned_item_id")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS tds_pct")
    op.execute("ALTER TABLE expense_payments DROP COLUMN IF EXISTS work_order_id")
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
