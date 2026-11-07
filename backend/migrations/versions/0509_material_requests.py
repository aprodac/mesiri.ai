"""Material requests: what a site asks for, before anyone orders it (PRC-22).

The first step of procurement: an engineer says "200 bags cement by Friday for the slab" (on the
dashboard or on WhatsApp); the office orders it, sends it from another site, or says no, and the
engineer is told. Today the only trace is a chat message (`runtime/open_needs.py` reads it back out
of chat text). One request holds one or more lines (material, quantity in the material's stock unit,
what was said when it was said in another unit).

Statuses: waiting -> ordered | sent (from another site) | rejected | cancelled; ordered | sent -> done.
Orders themselves (purchase orders, PRC-06) come later and will point at the request.

Additive only: two new tables with row-level security as every company table has it (0484).

Revision ID: 0509
Revises: 0508
Create Date: 2026-11-07
"""

from __future__ import annotations

from alembic import op

revision = "0509"
down_revision = "0508"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE material_requests (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            number integer NOT NULL,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            site_id uuid NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
            requested_by uuid REFERENCES users(id) ON DELETE SET NULL,
            source text NOT NULL DEFAULT 'dashboard',
            needed_by date,
            purpose text,
            status text NOT NULL DEFAULT 'waiting',
            raised_over_duplicate boolean NOT NULL DEFAULT false,
            decision_note text,
            decided_by uuid REFERENCES users(id) ON DELETE SET NULL,
            decided_at timestamptz,
            done_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_material_requests_number UNIQUE (organization_id, number),
            CONSTRAINT ck_material_requests_status CHECK (
                status IN ('waiting', 'ordered', 'sent', 'done', 'rejected', 'cancelled')),
            CONSTRAINT ck_material_requests_source CHECK (source IN ('dashboard', 'whatsapp'))
        )
        """
    )
    op.execute("CREATE INDEX ix_material_requests_org_status ON material_requests (organization_id, status)")
    op.execute("CREATE INDEX ix_material_requests_project ON material_requests (organization_id, project_id)")
    op.execute(
        """
        CREATE TABLE material_request_lines (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            request_id uuid NOT NULL REFERENCES material_requests(id) ON DELETE CASCADE,
            material_id uuid NOT NULL REFERENCES materials_catalog(id),
            unit_id uuid NOT NULL REFERENCES units_of_measure(id),
            quantity numeric(14, 3) NOT NULL,
            said text,
            position integer NOT NULL DEFAULT 0,
            CONSTRAINT ck_material_request_lines_quantity CHECK (quantity > 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_material_request_lines_request ON material_request_lines (request_id)")
    op.execute(
        "CREATE INDEX ix_material_request_lines_material ON material_request_lines (organization_id, material_id)"
    )
    for table in ("material_requests", "material_request_lines"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS material_request_lines")
    op.execute("DROP TABLE IF EXISTS material_requests")
