"""Give a company the builder's standard material categories, and place the materials that fit (PRC-03).

Called by the create-company step (so every new company starts sorted) and by
``POST /materials/categories/standard`` (an existing company's one tap). Safe to run
again: a category the company already has (same name under the same parent, any
case) is reused, never duplicated or renamed back, and a material that already has
a category is never moved. Takes the caller's connection and never commits.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mesiri.domains.materials.categories import STANDARD_CATEGORIES, standard_path_for
from mesiri.infrastructure.postgres.repositories.material_categories import (
    PostgresMaterialCategoryRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True, slots=True)
class StandardCategoriesResult:
    categories_added: int
    materials_placed: int


async def apply_standard_categories(
    conn: AsyncConnection, organization_id: uuid.UUID, created_by: uuid.UUID | None
) -> StandardCategoriesResult:
    repo = PostgresMaterialCategoryRepository(conn)
    added = 0
    ids: dict[tuple[str, str | None], uuid.UUID] = {}
    for main_order, (main, subs) in enumerate(STANDARD_CATEGORIES, start=1):
        main_row = await repo.find(organization_id, None, main)
        if main_row is None:
            main_row = await repo.create(
                organization_id, name=main, parent_id=None, sort_order=main_order * 10, created_by=created_by
            )
            added += 1
        ids[(main, None)] = main_row["id"]
        for sub_order, sub in enumerate(subs, start=1):
            sub_row = await repo.find(organization_id, main_row["id"], sub)
            if sub_row is None:
                sub_row = await repo.create(
                    organization_id,
                    name=sub,
                    parent_id=main_row["id"],
                    sort_order=sub_order * 10,
                    created_by=created_by,
                )
                added += 1
            ids[(main, sub)] = sub_row["id"]

    placed = 0
    for material in await repo.uncategorised_materials(organization_id):
        path = standard_path_for(material["name"], material.get("category"))
        if path is None or path not in ids:
            continue
        await repo.set_material_category(organization_id, material["id"], ids[path])
        placed += 1
    return StandardCategoriesResult(categories_added=added, materials_placed=placed)
