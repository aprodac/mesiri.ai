"""Vendors get a phone, GSTIN and address; a delivery points at its vendor (PRC-04).

Comparing shops and asking "who sent the cement?" needs each delivery to name a real
vendor, not free text: `material_receipts.supplier` is kept as said, and the new
`material_receipts.vendor_id` points at the vendor row. Deliveries already on record are
linked where their supplier text is exactly an active vendor's name (case and outer
spaces aside); nothing else is guessed, and no existing column is rewritten.

Additive only: nullable columns and an index.

Revision ID: 0505
Revises: 0504
Create Date: 2026-11-05
"""

from __future__ import annotations

from alembic import op

revision = "0505"
down_revision = "0504"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE vendors ADD COLUMN phone text, ADD COLUMN gstin text, ADD COLUMN address text")
    op.execute(
        "ALTER TABLE material_receipts ADD COLUMN vendor_id uuid REFERENCES vendors(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX ix_material_receipts_vendor_id ON material_receipts (vendor_id)")
    op.execute(
        """
        WITH one AS (
            SELECT organization_id, lower(btrim(name)) AS key, min(id::text)::uuid AS id
              FROM vendors
             WHERE status = 'active'
             GROUP BY organization_id, lower(btrim(name))
            HAVING count(*) = 1
        )
        UPDATE material_receipts r
           SET vendor_id = one.id
          FROM one
         WHERE r.vendor_id IS NULL
           AND r.supplier IS NOT NULL
           AND one.organization_id = r.organization_id
           AND one.key = lower(btrim(r.supplier))
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_material_receipts_vendor_id")
    op.execute("ALTER TABLE material_receipts DROP COLUMN IF EXISTS vendor_id")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS phone, DROP COLUMN IF EXISTS gstin, DROP COLUMN IF EXISTS address")
