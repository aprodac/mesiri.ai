"""Cost control as a module (CC-01, asked in session 8 Nov 2026): a cost centre on every expense category, and
the ``cost`` module switched on for companies whose module list is already stored.

- ``expense_categories.cost_centre`` (nullable): materials, labour, subcontract, equipment, fuel, overhead or
  other. Set for the categories Mesiri seeds, from their code (MAT, LAB, EQUIP/EQP, FUEL, UTIL, ADM, MISC, UNC;
  a LAB category named "Subcontract..." is subcontract). A category a company made itself is left unset: the
  Cost centres page shows it as "Not set" until someone picks one, never a guess.
- ``cost`` added to ``organization_settings.enabled_modules`` where that list is stored, recorded in
  ``cost_switched_on_0521`` so the downgrade takes it off exactly there (as 0518 did for equipment).

Additive. Downgrade drops the column (centres picked by hand are lost) and the switch.

Revision ID: 0521
Revises: 0520
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "0521"
down_revision = "0520"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"
CENTRES = ("materials", "labour", "subcontract", "equipment", "fuel", "overhead", "other")


def upgrade() -> None:
    allowed = ", ".join(f"'{c}'" for c in CENTRES)
    op.execute(
        "ALTER TABLE expense_categories ADD COLUMN cost_centre text "
        f"CONSTRAINT ck_expense_categories_cost_centre CHECK (cost_centre IS NULL OR cost_centre IN ({allowed}))"
    )
    op.execute(
        """
        UPDATE expense_categories SET cost_centre = CASE
            WHEN code = 'MAT' THEN 'materials'
            WHEN code = 'LAB' AND name ILIKE '%subcontract%' THEN 'subcontract'
            WHEN code = 'LAB' THEN 'labour'
            WHEN code IN ('EQUIP', 'EQP') THEN 'equipment'
            WHEN code = 'FUEL' THEN 'fuel'
            WHEN code IN ('UTIL', 'ADM') THEN 'overhead'
            WHEN code IN ('MISC', 'UNC') THEN 'other'
        END
        WHERE cost_centre IS NULL AND code IN ('MAT', 'LAB', 'EQUIP', 'EQP', 'FUEL', 'UTIL', 'ADM', 'MISC', 'UNC')
        """
    )
    op.execute(
        """
        CREATE TABLE cost_switched_on_0521 (
            organization_id uuid PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
            switched_on_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE cost_switched_on_0521 ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON cost_switched_on_0521 USING ({_RULE}) WITH CHECK ({_RULE})")
    op.execute(
        """
        INSERT INTO cost_switched_on_0521 (organization_id)
        SELECT organization_id FROM organization_settings
         WHERE key = 'enabled_modules'
           AND jsonb_typeof(value) = 'array'
           AND NOT value @> '["cost"]'::jsonb
        """
    )
    op.execute(
        """
        UPDATE organization_settings s
           SET value = s.value || '["cost"]'::jsonb, updated_at = now()
          FROM cost_switched_on_0521 f
         WHERE s.organization_id = f.organization_id AND s.key = 'enabled_modules'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE organization_settings s
           SET value = COALESCE(
                   (SELECT jsonb_agg(m) FROM jsonb_array_elements(s.value) m WHERE m <> '"cost"'::jsonb),
                   '[]'::jsonb),
               updated_at = now()
          FROM cost_switched_on_0521 f
         WHERE s.organization_id = f.organization_id AND s.key = 'enabled_modules'
        """
    )
    op.execute("DROP TABLE IF EXISTS cost_switched_on_0521")
    op.execute("ALTER TABLE expense_categories DROP COLUMN IF EXISTS cost_centre")
