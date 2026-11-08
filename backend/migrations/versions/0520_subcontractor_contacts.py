"""Subcontractors on Mesiri's WhatsApp (NXT-16, option B, approved by Alan 8 Nov 2026).

``vendor_contacts``: a subcontractor's people who may message Mesiri (name, phone, language, status), added by the
company. Never rows in ``users``: they are not company staff. ``partner_audit``: every request they make.

Additive, RLS like 0511. Plan: docs/plans/subcontractors-plan.md S6.

Revision ID: 0520
Revises: 0519
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "0520"
down_revision = "0519"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE vendor_contacts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            vendor_id uuid NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
            name text NOT NULL,
            phone text NOT NULL,
            language text,
            status text NOT NULL DEFAULT 'active',
            invited_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at timestamptz,
            CONSTRAINT ck_vendor_contacts_status CHECK (status IN ('active', 'inactive'))
        )""")
    op.execute("CREATE UNIQUE INDEX uq_vendor_contacts_phone ON vendor_contacts (organization_id, phone) WHERE status = 'active'")
    op.execute("CREATE INDEX ix_vendor_contacts_phone ON vendor_contacts (phone) WHERE status = 'active'")
    op.execute("""
        CREATE TABLE partner_audit (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            contact_id uuid NOT NULL REFERENCES vendor_contacts(id) ON DELETE CASCADE,
            method text NOT NULL,
            path text NOT NULL,
            status integer,
            at timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX ix_partner_audit_contact ON partner_audit (contact_id, at)")
    op.execute("ALTER TABLE work_order_bills ADD CONSTRAINT fk_wo_bills_contact FOREIGN KEY (submitted_by_contact) "
               "REFERENCES vendor_contacts(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE work_order_measurements ADD COLUMN reported_by_contact uuid REFERENCES vendor_contacts(id) ON DELETE SET NULL")
    for table in ("vendor_contacts", "partner_audit"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("ALTER TABLE work_order_measurements DROP COLUMN IF EXISTS reported_by_contact")
    op.execute("ALTER TABLE work_order_bills DROP CONSTRAINT IF EXISTS fk_wo_bills_contact")
    op.execute("DROP TABLE IF EXISTS partner_audit")
    op.execute("DROP TABLE IF EXISTS vendor_contacts")
