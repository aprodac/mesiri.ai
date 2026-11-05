"""Material categories: a company's main categories and sub-categories (PRC-01).

A builder sorts every material under a main category (Structural, Electrical,
Plumbing & CP, ...) and a sub-category under it (Switches & sockets, Pipes, ...),
and wants totals per category, per project and for the company. Sizes and types
(1-module, 2-way, 20 mm) stay separate materials, as today; the tree only groups
them. Two levels: a category with no parent is a main category; a sub-category's
parent is a main category (the API enforces the depth).

Additive only: a new table and a nullable `materials_catalog.category_id`. The old
free-text `materials_catalog.category` is kept and not rewritten. Row-level
security as every company table has it (0484).

Revision ID: 0503
Revises: 0502
Create Date: 2026-11-05
"""

from __future__ import annotations

from alembic import op

revision = "0503"
down_revision = "0502"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE material_categories (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            parent_id uuid REFERENCES material_categories(id) ON DELETE CASCADE,
            name text NOT NULL,
            sort_order integer NOT NULL DEFAULT 0,
            is_active boolean NOT NULL DEFAULT true,
            created_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_by uuid,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_material_categories_name CHECK (btrim(name) <> '')
        )
        """
    )
    # One "Pipes" under Plumbing and one under Fire protection is fine; two under the same parent is not.
    op.execute(
        "CREATE UNIQUE INDEX uq_material_categories_org_parent_name ON material_categories "
        "(organization_id, COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(btrim(name)))"
    )
    op.execute("CREATE INDEX ix_material_categories_parent ON material_categories (organization_id, parent_id)")
    op.execute("ALTER TABLE material_categories ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON material_categories USING ({_RULE}) WITH CHECK ({_RULE})")
    op.execute(
        "ALTER TABLE materials_catalog ADD COLUMN category_id uuid "
        "REFERENCES material_categories(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX ix_materials_catalog_category_id ON materials_catalog (category_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_materials_catalog_category_id")
    op.execute("ALTER TABLE materials_catalog DROP COLUMN IF EXISTS category_id")
    op.execute("DROP TABLE IF EXISTS material_categories")
