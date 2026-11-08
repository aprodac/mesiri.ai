"""Project start (ST-01..ST-04): project stage and dates, clients and contracts, the schedule's milestones and links.

See docs/plans/project-start-plan.md. Additive only:

- ``projects.stage``: where the project is in its life (tender / won / running / handover / defects / closed).
  Default ``running`` so every existing project behaves as before. ``projects.status`` stays the health
  (on track / at risk), a different question. ``projects.start_date`` / ``planned_finish``: the contract dates.
- ``clients``: the people and companies a contractor builds for, per company.
- ``project_contracts``: one per project: client, contract number and value, retention, mobilisation advance and
  its recovery, GST, TDS, defect liability period, payment terms.
- ``work_packages.is_milestone``: a schedule point with no duration ("Slab cast", "Handover").
- ``work_package_links``: "starts after" between two schedule activities (``work_packages``), with lag days.

The schedule's own dates were already on ``work_packages`` (0420: planned / actual start and end, status,
manual %), never used until now. Every new table has row-level security like 0519. Downgrade refuses while
contracts exist.

Revision ID: 0522
Revises: 0521
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "0522"
down_revision = "0521"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"
_TABLES = ("clients", "project_contracts", "work_package_links")
STAGES = ("tender", "won", "running", "handover", "defects", "closed")


def upgrade() -> None:
    stages = ", ".join(f"'{s}'" for s in STAGES)
    op.execute(
        "ALTER TABLE projects ADD COLUMN stage text NOT NULL DEFAULT 'running', "
        "ADD COLUMN start_date date, ADD COLUMN planned_finish date, "
        f"ADD CONSTRAINT ck_projects_stage CHECK (stage IN ({stages}))"
    )
    op.execute("""
        CREATE TABLE clients (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name text NOT NULL,
            contact_person text,
            phone text,
            email text,
            gstin text,
            address text,
            notes text,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE UNIQUE INDEX uq_clients_org_name ON clients (organization_id, lower(name))")
    op.execute("""
        CREATE TABLE project_contracts (
            project_id uuid PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            client_id uuid REFERENCES clients(id) ON DELETE SET NULL,
            contract_no text,
            contract_value numeric(16,2),
            signed_on date,
            retention_pct numeric(5,2),
            mobilisation_advance numeric(16,2),
            advance_recovery_pct numeric(5,2),
            gst_pct numeric(5,2),
            tds_pct numeric(5,2),
            defect_liability_months integer,
            payment_terms text,
            notes text,
            updated_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_project_contract_numbers CHECK (
                (contract_value IS NULL OR contract_value >= 0)
                AND (mobilisation_advance IS NULL OR mobilisation_advance >= 0)
                AND (retention_pct IS NULL OR retention_pct BETWEEN 0 AND 100)
                AND (advance_recovery_pct IS NULL OR advance_recovery_pct BETWEEN 0 AND 100)
                AND (gst_pct IS NULL OR gst_pct BETWEEN 0 AND 100)
                AND (tds_pct IS NULL OR tds_pct BETWEEN 0 AND 100)
                AND (defect_liability_months IS NULL OR defect_liability_months BETWEEN 0 AND 120))
        )""")
    op.execute("CREATE INDEX ix_project_contracts_client ON project_contracts (client_id)")
    op.execute("ALTER TABLE work_packages ADD COLUMN is_milestone boolean NOT NULL DEFAULT false")
    op.execute("""
        CREATE TABLE work_package_links (
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            predecessor_id uuid NOT NULL REFERENCES work_packages(id) ON DELETE CASCADE,
            successor_id uuid NOT NULL REFERENCES work_packages(id) ON DELETE CASCADE,
            lag_days integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (predecessor_id, successor_id),
            CONSTRAINT ck_work_package_link_self CHECK (predecessor_id <> successor_id),
            CONSTRAINT ck_work_package_link_lag CHECK (lag_days BETWEEN -365 AND 365)
        )""")
    op.execute("CREATE INDEX ix_work_package_links_successor ON work_package_links (successor_id)")
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM project_contracts) THEN "
               "RAISE EXCEPTION 'project contracts exist; downgrading would lose them'; END IF; END $$")
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("ALTER TABLE work_packages DROP COLUMN IF EXISTS is_milestone")
    op.execute("ALTER TABLE projects DROP CONSTRAINT IF EXISTS ck_projects_stage, DROP COLUMN IF EXISTS stage, "
               "DROP COLUMN IF EXISTS start_date, DROP COLUMN IF EXISTS planned_finish")
