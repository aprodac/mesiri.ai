"""Project documents and drawings register (DOC-01, DR-07).

See docs/plans/project-documents-plan.md. Additive only:

- ``project_documents``: one row per file revision. Folder (contract, drawing, approval, boq, work_order,
  test_report, handover, other), discipline for drawings, number ("S-101"), title, revision ("C"), status (current,
  superseded, archived) with ``supersedes_id`` for the history, ``valid_until`` for permits and insurance,
  ``restricted`` for money and contract papers (D-DOC1), the stored object, its sha256 (a duplicate upload is
  refused), links to an activity / work order / vendor, and ``facts`` (DR-07): what the drawing reader read from a
  drawing PDF (sheets, levels, rooms, fixtures, checks), so it can be asked later without reading the file again.
- One current document per project and number (partial unique index).

Tenant row-level security like 0525. Downgrade refuses while documents exist.

Revision ID: 0527
Revises: 0526
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "0527"
down_revision = "0526"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE project_documents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            site_id uuid REFERENCES sites(id) ON DELETE SET NULL,
            folder text NOT NULL DEFAULT 'other',
            discipline text,
            number text,
            title text NOT NULL,
            revision text,
            revision_date date,
            status text NOT NULL DEFAULT 'current',
            supersedes_id uuid REFERENCES project_documents(id) ON DELETE SET NULL,
            valid_until date,
            restricted boolean NOT NULL DEFAULT false,
            object_key text NOT NULL,
            file_name text NOT NULL,
            content_type text NOT NULL,
            size_bytes bigint NOT NULL,
            sha256 text NOT NULL,
            pages integer,
            facts jsonb,
            source text NOT NULL DEFAULT 'web',
            work_package_id uuid REFERENCES work_packages(id) ON DELETE SET NULL,
            work_order_id uuid REFERENCES work_orders(id) ON DELETE SET NULL,
            vendor_id uuid REFERENCES vendors(id) ON DELETE SET NULL,
            notes text,
            uploaded_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_project_documents_folder CHECK (folder IN ('contract', 'drawing', 'approval', 'boq',
                'work_order', 'test_report', 'handover', 'other')),
            CONSTRAINT ck_project_documents_discipline CHECK (discipline IS NULL OR discipline IN ('architectural',
                'structural', 'mep', 'other')),
            CONSTRAINT ck_project_documents_status CHECK (status IN ('current', 'superseded', 'archived')),
            CONSTRAINT ck_project_documents_source CHECK (source IN ('web', 'whatsapp')),
            CONSTRAINT ck_project_documents_size CHECK (size_bytes >= 0)
        )""")
    op.execute("CREATE UNIQUE INDEX uq_project_documents_current_number ON project_documents "
               "(project_id, lower(number)) WHERE status = 'current' AND number IS NOT NULL")
    op.execute("CREATE INDEX ix_project_documents_org_project ON project_documents (organization_id, project_id, status)")
    op.execute("CREATE INDEX ix_project_documents_sha ON project_documents (project_id, sha256)")
    op.execute("CREATE INDEX ix_project_documents_expiry ON project_documents (valid_until) "
               "WHERE valid_until IS NOT NULL AND status = 'current'")
    op.execute("ALTER TABLE project_documents ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON project_documents USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM project_documents) THEN "
               "RAISE EXCEPTION 'Project documents exist; downgrading would lose them'; END IF; END $$")
    op.execute("DROP TABLE IF EXISTS project_documents")
