"""Payment stages (FB-01): the client's payment schedule, tied to the schedule's milestones, and lump-sum contracts.

Asked by a contractor in the product discovery session (Nov 2026): "when the supervisor marks Lintel completed, check
that the ₹4 lakh for that stage came in; if only ₹20,000 did, alert someone to follow up", and "lump sum contracts
are billed by stage, not by measurement".

Additive only, no existing row changes:

- ``project_contracts.contract_type``: ``measured`` (today's re-measurable RA bills from the BOQ, the default for
  every existing contract) or ``lump_sum`` (bills are made from the payment stages reached).
- ``payment_stages``: one row per stage of the client's payment schedule: its name, the amount the client pays at it,
  the schedule activity (a ``work_packages`` row, usually a milestone) whose completion reaches it, or a date it was
  marked reached by hand.
- ``ra_bill_lines.payment_stage_id``: a lump-sum bill's line is a stage, not a BOQ line, so ``planned_item_id`` may
  be empty when the stage is set (one or the other, checked). Existing lines all have a BOQ line, so nothing moves.

Revision ID: 0564
Revises: 0563
Create Date: 2026-11-21
"""

from __future__ import annotations

from alembic import op

revision = "0564"
down_revision = "0563"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("ALTER TABLE project_contracts ADD COLUMN contract_type text NOT NULL DEFAULT 'measured'")
    op.execute("ALTER TABLE project_contracts ADD CONSTRAINT ck_project_contracts_type "
               "CHECK (contract_type IN ('measured', 'lump_sum'))")
    op.execute("""
        CREATE TABLE payment_stages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name text NOT NULL,
            amount numeric(16,2) NOT NULL,
            work_package_id uuid REFERENCES work_packages(id) ON DELETE SET NULL,
            reached_on date,
            sort_order integer NOT NULL DEFAULT 0,
            notes text,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_payment_stages_amount CHECK (amount >= 0),
            CONSTRAINT ck_payment_stages_name CHECK (btrim(name) <> '')
        )""")
    op.execute("CREATE INDEX ix_payment_stages_org_project ON payment_stages (organization_id, project_id, sort_order)")
    op.execute("ALTER TABLE payment_stages ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON payment_stages USING ({_RULE}) WITH CHECK ({_RULE})")

    op.execute("ALTER TABLE ra_bill_lines ADD COLUMN payment_stage_id uuid REFERENCES payment_stages(id) "
               "ON DELETE RESTRICT")
    op.execute("ALTER TABLE ra_bill_lines ALTER COLUMN planned_item_id DROP NOT NULL")
    op.execute("ALTER TABLE ra_bill_lines ADD CONSTRAINT ck_ra_bill_lines_source "
               "CHECK ((planned_item_id IS NULL) <> (payment_stage_id IS NULL))")
    op.execute("ALTER TABLE ra_bill_lines ADD CONSTRAINT uq_ra_bill_lines_stage UNIQUE (ra_bill_id, payment_stage_id)")
    op.execute("CREATE INDEX ix_ra_bill_lines_stage ON ra_bill_lines (payment_stage_id) "
               "WHERE payment_stage_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM ra_bill_lines WHERE payment_stage_id IS NOT NULL) THEN "
               "RAISE EXCEPTION 'Stage bills exist; downgrading would lose them'; END IF; END $$")
    op.execute("ALTER TABLE ra_bill_lines DROP CONSTRAINT IF EXISTS uq_ra_bill_lines_stage")
    op.execute("ALTER TABLE ra_bill_lines DROP CONSTRAINT IF EXISTS ck_ra_bill_lines_source")
    op.execute("ALTER TABLE ra_bill_lines ALTER COLUMN planned_item_id SET NOT NULL")
    op.execute("ALTER TABLE ra_bill_lines DROP COLUMN IF EXISTS payment_stage_id")
    op.execute("DROP TABLE IF EXISTS payment_stages")
    op.execute("ALTER TABLE project_contracts DROP CONSTRAINT IF EXISTS ck_project_contracts_type")
    op.execute("ALTER TABLE project_contracts DROP COLUMN IF EXISTS contract_type")
