"""Supplier documents and delivery certificates (PRC-52).

See docs/plans/procurement-phase2-plan.md §5.9 and the reuse note in docs/plans/project-documents-plan.md. Additive only:

- ``project_documents.goods_receipt_id``: a delivery's quality papers (mill test, cement test, RMC batch / cube) are
  project documents in the test-reports folder, linked to the GRN they came with. Nothing else in the register changes.
- ``vendor_documents``: a supplier's own papers (GST certificate, PAN, cancelled cheque, agreement, ISO / BIS, other)
  belong to the company, not to a project, so they cannot sit in ``project_documents`` (project_id NOT NULL and its
  per-project access rules). One row per file; a new upload of the same kind supersedes the old one (kept, as history);
  archived instead of deleted. The upload checks, storage key pattern and short-lived link are the register's.

Revision ID: 0545
Revises: 0544
Create Date: 2026-11-11
"""

from __future__ import annotations

from alembic import op

revision = "0545"
down_revision = "0544"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("ALTER TABLE project_documents ADD COLUMN goods_receipt_id uuid "
               "REFERENCES goods_receipts(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX ix_project_documents_grn ON project_documents (goods_receipt_id) "
               "WHERE goods_receipt_id IS NOT NULL")
    op.execute(
        """
        CREATE TABLE vendor_documents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            vendor_id uuid NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
            kind text NOT NULL,
            number text,
            valid_until date,
            status text NOT NULL DEFAULT 'current',
            supersedes_id uuid REFERENCES vendor_documents(id) ON DELETE SET NULL,
            object_key text NOT NULL,
            file_name text NOT NULL,
            content_type text NOT NULL,
            size_bytes bigint NOT NULL,
            sha256 text NOT NULL,
            notes text,
            uploaded_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_vendor_documents_kind CHECK (kind IN ('gst', 'pan', 'cheque', 'agreement', 'iso_bis', 'other')),
            CONSTRAINT ck_vendor_documents_status CHECK (status IN ('current', 'superseded', 'archived')),
            CONSTRAINT ck_vendor_documents_size CHECK (size_bytes >= 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_vendor_documents_vendor ON vendor_documents (organization_id, vendor_id, status)")
    op.execute("CREATE INDEX ix_vendor_documents_expiry ON vendor_documents (valid_until) "
               "WHERE valid_until IS NOT NULL AND status = 'current'")
    op.execute("ALTER TABLE vendor_documents ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON vendor_documents USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM vendor_documents) THEN "
               "RAISE EXCEPTION 'Supplier documents exist; downgrading would lose them'; END IF; END $$")
    op.execute("DROP TABLE IF EXISTS vendor_documents")
    op.execute("DROP INDEX IF EXISTS ix_project_documents_grn")
    op.execute("ALTER TABLE project_documents DROP COLUMN IF EXISTS goods_receipt_id")
