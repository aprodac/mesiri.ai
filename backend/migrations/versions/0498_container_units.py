"""Container units: drum, tin, bucket, bundle (WA-167; approved by Alan, 3 Nov 2026).

Sites count paint and thinner in drums and tins, putty and water-proofing in buckets, steel and
binding wire in bundles; the units list had none of them, so "2 drum thinner" had no unit to be
recorded in. Added to the global list; a company sets how much one is of each material once
(material_unit_conversions). "Trip", "lorry" and "tipper" are words for the existing Loads
(runtime/unit_words.py), not a new unit.

Additive and idempotent (ON CONFLICT on the unique code). Downgrade removes a unit only while
nothing refers to it; one in use is deactivated instead, so no recorded quantity loses its unit.

Revision ID: 0498
Revises: 0497
Create Date: 2026-11-03
"""

from __future__ import annotations

from alembic import op

revision = "0498"
down_revision = "0497"
branch_labels = None
depends_on = None

_UNITS = (("drum", "Drums"), ("tin", "Tins"), ("bucket", "Buckets"), ("bundle", "Bundles"))
_CODES = ", ".join(f"'{code}'" for code, _ in _UNITS)
_USES = (
    "material_receipts.unit_id", "material_usage.unit_id", "material_movements.unit_id",
    "material_unit_conversions.from_unit_id", "materials_catalog.default_unit_id",
)


def upgrade() -> None:
    for code, name in _UNITS:
        op.execute(
            "INSERT INTO units_of_measure (id, code, display_name) "
            f"VALUES (gen_random_uuid(), '{code}', '{name}') ON CONFLICT (code) DO NOTHING"
        )


def downgrade() -> None:
    used = " OR ".join(
        f"EXISTS (SELECT 1 FROM {ref.split('.')[0]} x WHERE x.{ref.split('.')[1]} = u.id)" for ref in _USES
    )
    op.execute(f"UPDATE units_of_measure u SET is_active = false WHERE u.code IN ({_CODES}) AND ({used})")
    op.execute(f"DELETE FROM units_of_measure u WHERE u.code IN ({_CODES}) AND NOT ({used})")
