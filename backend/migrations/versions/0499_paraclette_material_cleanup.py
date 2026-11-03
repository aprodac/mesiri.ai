"""Paraclette's material list, cleaned up (WA-167; approved by Alan, 3 Nov 2026).

Found in WA-166 (21 unit dead ends in four days). Only what the data itself settles:

1. Two materials that were one, made twice because the name came in Malayalam script:
   "സിമൻറ്" (2 receipts, 1 use) into "Cement", and "എംസാന്റ്" (1 use) into "M sand". Both pairs are
   counted in bags. Their receipts, uses and stock movements move to the material that stays; the
   Malayalam name becomes an alias of it (so "സിമൻറ്" still finds Cement); the duplicate is switched
   off (kept, never deleted). Stock is summed by material, so Cement and M sand now show the whole.
2. Two sizes that cannot be right, deleted so the right one is asked next time: "1 load holobricks =
   0.33 nos" (the wrong way round) and "1 ton Fevi Stick = 1 nos".

Not here, because only Paraclette knows the facts (listed in docs/plans/V1_TRACKER.md, WA-167):
TMT Steel Bars counted in loads (bar size or kg per load needed), the 0.33-brick receipt of 23 Oct (bricks
per load needed), how many bags make a load of M-sand / P-sand.

Exact rows by id, each change only while the row is still as found on 3 Nov (same material, same
unit), so a later edit is never overwritten and the migration is a no-op anywhere else. Downgrade
moves the same rows back, switches the duplicates on, removes the two aliases and restores the sizes.

Revision ID: 0499
Revises: 0498
Create Date: 2026-11-03
"""

from __future__ import annotations

from alembic import op

revision = "0499"
down_revision = "0498"
branch_labels = None
depends_on = None

ORG = "abb47cc6-9304-4d66-9d93-d3eea129bb77"
BAGS = "03e5cbfa-43d6-4af5-b18a-61aa7f884af7"

#: (duplicate, the material that stays, its name, alias_key of the duplicate's name, receipts, uses, movements)
MERGES = (
    ("f1e6b68a-54d7-4b29-81eb-60a31216b600", "832b3a63-7724-498f-bfb8-ad275e3b4d81", "സിമൻറ്", "സിമന്റ്",
     ("26a8ae7c-bd27-49f2-977e-cb32656fc2ab", "eeb466ee-ce6c-4ce0-a665-b7328776a32a"),
     ("e6c59ce5-8142-4fd8-9795-baf4aef3813d",),
     ("2db076e5-9d3c-4d78-81fd-2888a085a53c", "8223abb5-d312-4557-8893-17ac1ac25b45",
      "65b06479-efc7-42d1-947d-72a8ee939244")),
    ("37788327-a0a6-47a5-823e-992c7afc072a", "c40abadd-8078-41f3-ab99-bc6b600d9d7a", "എംസാന്റ്", "എംസാന്റ്",
     (), ("55653e88-898d-4984-897c-b0c7ad70fbaa",), ("20f49025-7686-4f54-8d5a-0fb4ea07ac9c",)),
)

#: (id, material, from unit, per_stock_unit, created_by, created_at) -- as found, for the downgrade.
BAD_SIZES = (
    ("ac996cc4-268d-4f98-bd5f-4e447c449665", "b42fcc9b-26af-4446-84e4-e7c8b4d097c7",
     "a37f37ed-fc4b-4b13-80e8-72b1b69211d9", "3", "2af88322-e663-4a09-9f09-dffcbf4a449d",
     "2026-10-23T16:25:18.843919+00:00"),
    ("93dacac1-411a-4635-87a9-80a22b01ef93", "85785e37-ccf9-44cd-8ee0-7310394d3355",
     "ed8a7d76-54ff-4ecd-ba6f-7e62b46ffcd7", "1", "2af88322-e663-4a09-9f09-dffcbf4a449d",
     "2026-10-21T22:09:54.727568+00:00"),
)


def _ids(ids: tuple[str, ...]) -> str:
    return ", ".join(f"'{i}'" for i in ids) or "NULL"


def _both_in_bags(dup: str, keep: str) -> str:
    """Both materials are Paraclette's and counted in bags (else nothing moves)."""
    return (f"(SELECT count(*) FROM materials_catalog WHERE id IN ('{dup}', '{keep}') "
            f"AND organization_id = '{ORG}' AND default_unit_id = '{BAGS}') = 2")


def upgrade() -> None:
    for dup, keep, _name, key, receipts, uses, movements in MERGES:
        guard = _both_in_bags(dup, keep)
        stays = f"(SELECT name FROM materials_catalog WHERE id = '{keep}')"
        op.execute(f"UPDATE material_receipts SET material_id = '{keep}', material_name = {stays}, updated_at = now() "
                   f"WHERE id IN ({_ids(receipts)}) AND material_id = '{dup}' AND unit_id = '{BAGS}' AND {guard}")
        op.execute(f"UPDATE material_usage SET material_id = '{keep}', material_name = {stays}, updated_at = now() "
                   f"WHERE id IN ({_ids(uses)}) AND material_id = '{dup}' AND unit_id = '{BAGS}' AND {guard}")
        op.execute(f"UPDATE material_movements SET material_id = '{keep}' "
                   f"WHERE id IN ({_ids(movements)}) AND material_id = '{dup}' AND unit_id = '{BAGS}' AND {guard}")
        op.execute(
            "INSERT INTO material_aliases (id, organization_id, material_id, alias_key, alias_text, created_at) "
            f"SELECT gen_random_uuid(), '{ORG}', '{keep}', '{key}', name, now() FROM materials_catalog "
            f"WHERE id = '{dup}' AND {guard} ON CONFLICT (organization_id, alias_key) DO NOTHING"
        )
        # Switched off only once nothing refers to it any more.
        op.execute(
            f"UPDATE materials_catalog SET is_active = false, updated_at = now() WHERE id = '{dup}' AND {guard} "
            f"AND NOT EXISTS (SELECT 1 FROM material_receipts WHERE material_id = '{dup}') "
            f"AND NOT EXISTS (SELECT 1 FROM material_usage WHERE material_id = '{dup}') "
            f"AND NOT EXISTS (SELECT 1 FROM material_movements WHERE material_id = '{dup}')"
        )
    for size_id, material, unit, per, *_ in BAD_SIZES:
        op.execute(f"DELETE FROM material_unit_conversions WHERE id = '{size_id}' AND material_id = '{material}' "
                   f"AND from_unit_id = '{unit}' AND per_stock_unit = {per}")


def downgrade() -> None:
    for size_id, material, unit, per, by, at in BAD_SIZES:
        # Only where the material and unit still exist (the migration is a no-op on any other database).
        op.execute(
            "INSERT INTO material_unit_conversions "
            "(id, organization_id, material_id, from_unit_id, per_stock_unit, created_by, created_at, updated_at) "
            f"SELECT '{size_id}', '{ORG}', '{material}', '{unit}', {per}, "
            f"(SELECT id FROM users WHERE id = '{by}'), '{at}', '{at}' "
            f"WHERE EXISTS (SELECT 1 FROM materials_catalog WHERE id = '{material}' AND organization_id = '{ORG}') "
            f"AND EXISTS (SELECT 1 FROM units_of_measure WHERE id = '{unit}') "
            "ON CONFLICT DO NOTHING"
        )
    for dup, keep, name, key, receipts, uses, movements in MERGES:
        op.execute(f"UPDATE materials_catalog SET is_active = true, updated_at = now() WHERE id = '{dup}'")
        op.execute(f"DELETE FROM material_aliases WHERE material_id = '{keep}' AND alias_key = '{key}' "
                   "AND created_by IS NULL")
        op.execute(f"UPDATE material_receipts SET material_id = '{dup}', material_name = '{name}', updated_at = now() "
                   f"WHERE id IN ({_ids(receipts)}) AND material_id = '{keep}'")
        op.execute(f"UPDATE material_usage SET material_id = '{dup}', material_name = '{name}', updated_at = now() "
                   f"WHERE id IN ({_ids(uses)}) AND material_id = '{keep}'")
        op.execute(f"UPDATE material_movements SET material_id = '{dup}' WHERE id IN ({_ids(movements)}) "
                   f"AND material_id = '{keep}'")
