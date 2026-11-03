"""Size requests: a size nobody on site knew, asked of the company's admin (WA-168; approved by Alan, 3 Nov 2026).

"1 load M-sand" when nobody knows how many bags a load is: the line is held here (its words and body,
as the person who reported it), everything else saves, and an admin or project manager is asked once
a day. When they answer, the size is set for the company and the held lines save, converted, as the
people who reported them. A site engineer's own size ("1 load = 60 bags") comes here as a proposal
the admin confirms with one tap. One open request per material and unit.

Additive: a new table. Downgrade drops it (held lines not yet saved are lost with it; none exist
before this migration).

Revision ID: 0500
Revises: 0499
Create Date: 2026-11-03
"""

from __future__ import annotations

from alembic import op

revision = "0500"
down_revision = "0499"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE material_size_requests (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            material_id uuid NOT NULL REFERENCES materials_catalog(id) ON DELETE CASCADE,
            from_unit_id uuid NOT NULL REFERENCES units_of_measure(id),
            proposed_one_unit_equals numeric,
            proposed_by uuid REFERENCES users(id) ON DELETE SET NULL,
            requested_by uuid REFERENCES users(id) ON DELETE SET NULL,
            held_lines jsonb NOT NULL DEFAULT '[]'::jsonb,
            status varchar(16) NOT NULL DEFAULT 'open',
            one_unit_equals numeric,
            answered_by uuid REFERENCES users(id) ON DELETE SET NULL,
            answered_at timestamptz,
            outcome jsonb,
            asked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_material_size_requests_status CHECK (status IN ('open', 'answered', 'dismissed'))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_material_size_requests_open ON material_size_requests "
        "(organization_id, material_id, from_unit_id) WHERE status = 'open'"
    )
    op.execute("CREATE INDEX ix_material_size_requests_org_status ON material_size_requests (organization_id, status)")
    # BE-03: the company's rows only, like every material table (same rule as 0494).
    op.execute("ALTER TABLE material_size_requests ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON material_size_requests USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS material_size_requests")
