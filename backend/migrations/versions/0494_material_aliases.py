"""Material aliases: the word a person said, kept beside the English material (request 165).

A material's catalogue name is always English in Latin letters. "ചെങ്കല്ല്" or
"chenkallu" said on WhatsApp is stored here against "Laterite stone", so the next
message with that word finds the material without a question.

Additive only: a new table, nothing existing changes. Row-level security as
every company table has it (0484).

Revision ID: 0494
Revises: 0493
Create Date: 2026-10-31
"""

from __future__ import annotations

from alembic import op

revision = "0494"
down_revision = "0493"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE material_aliases (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            material_id uuid NOT NULL REFERENCES materials_catalog(id) ON DELETE CASCADE,
            alias_key text NOT NULL,
            alias_text text NOT NULL,
            created_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_material_aliases_org_key UNIQUE (organization_id, alias_key)
        )
        """
    )
    op.execute("CREATE INDEX ix_material_aliases_material ON material_aliases (material_id)")
    op.execute("ALTER TABLE material_aliases ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON material_aliases USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS material_aliases")
