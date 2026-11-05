"""PostgreSQL access to a company's material categories (PRC-01).

Two levels: a row with no parent is a main category, a row whose parent is a main
category is a sub-category. Every method takes the caller's connection and never
commits; the request (or the create-company step) owns the transaction.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

_COLUMNS = "id, organization_id, parent_id, name, sort_order, is_active, created_at, updated_at"


class PostgresMaterialCategoryRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def list_all(self, organization_id: uuid.UUID) -> list[dict]:
        """Every category of the company, with how many materials sit directly in each."""
        res = await self.conn.execute(
            text(
                f"""
                SELECT {", ".join("c." + c.strip() for c in _COLUMNS.split(","))},
                       (SELECT count(*) FROM materials_catalog m
                         WHERE m.organization_id = c.organization_id AND m.category_id = c.id) AS material_count
                  FROM material_categories c
                 WHERE c.organization_id = :org
                 ORDER BY c.sort_order, lower(c.name)
                """
            ),
            {"org": organization_id},
        )
        return [dict(r) for r in res.mappings().all()]

    async def count_uncategorised(self, organization_id: uuid.UUID) -> int:
        res = await self.conn.execute(
            text("SELECT count(*) FROM materials_catalog WHERE organization_id = :org AND category_id IS NULL"),
            {"org": organization_id},
        )
        return int(res.scalar_one())

    async def get(self, organization_id: uuid.UUID, category_id: uuid.UUID) -> dict | None:
        res = await self.conn.execute(
            text(f"SELECT {_COLUMNS} FROM material_categories WHERE organization_id = :org AND id = :id"),
            {"org": organization_id, "id": category_id},
        )
        row = res.mappings().first()
        return dict(row) if row else None

    async def find(
        self,
        organization_id: uuid.UUID,
        parent_id: uuid.UUID | None,
        name: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> dict | None:
        """The category with this name under this parent (case- and space-insensitive), as the unique index sees it."""
        res = await self.conn.execute(
            text(
                f"""
                SELECT {_COLUMNS} FROM material_categories
                 WHERE organization_id = :org
                   AND parent_id IS NOT DISTINCT FROM CAST(:parent AS uuid)
                   AND lower(btrim(name)) = lower(btrim(:name))
                   AND (CAST(:exclude AS uuid) IS NULL OR id <> CAST(:exclude AS uuid))
                """
            ),
            {"org": organization_id, "parent": parent_id, "name": name, "exclude": exclude_id},
        )
        row = res.mappings().first()
        return dict(row) if row else None

    async def next_sort_order(self, organization_id: uuid.UUID, parent_id: uuid.UUID | None) -> int:
        res = await self.conn.execute(
            text(
                "SELECT COALESCE(max(sort_order), 0) + 10 FROM material_categories "
                "WHERE organization_id = :org AND parent_id IS NOT DISTINCT FROM CAST(:parent AS uuid)"
            ),
            {"org": organization_id, "parent": parent_id},
        )
        return int(res.scalar_one())

    async def create(
        self,
        organization_id: uuid.UUID,
        *,
        name: str,
        parent_id: uuid.UUID | None,
        sort_order: int,
        created_by: uuid.UUID | None,
    ) -> dict:
        res = await self.conn.execute(
            text(
                f"""
                INSERT INTO material_categories (organization_id, parent_id, name, sort_order, created_by, updated_by)
                VALUES (:org, CAST(:parent AS uuid), :name, :sort, :by, :by)
                RETURNING {_COLUMNS}
                """
            ),
            {"org": organization_id, "parent": parent_id, "name": name, "sort": sort_order, "by": created_by},
        )
        return dict(res.mappings().one())

    async def update(
        self,
        organization_id: uuid.UUID,
        category_id: uuid.UUID,
        *,
        name: str | None,
        sort_order: int | None,
        is_active: bool | None,
        updated_by: uuid.UUID | None,
    ) -> dict | None:
        res = await self.conn.execute(
            text(
                f"""
                UPDATE material_categories
                   SET name = COALESCE(:name, name),
                       sort_order = COALESCE(:sort, sort_order),
                       is_active = COALESCE(:active, is_active),
                       updated_by = :by, updated_at = now()
                 WHERE organization_id = :org AND id = :id
                RETURNING {_COLUMNS}
                """
            ),
            {
                "org": organization_id,
                "id": category_id,
                "name": name,
                "sort": sort_order,
                "active": is_active,
                "by": updated_by,
            },
        )
        row = res.mappings().first()
        return dict(row) if row else None

    async def is_in_use(self, organization_id: uuid.UUID, category_id: uuid.UUID) -> bool:
        """True if a material or a sub-category sits in it: such a category is switched off, never deleted."""
        res = await self.conn.execute(
            text(
                """
                SELECT EXISTS (SELECT 1 FROM materials_catalog WHERE organization_id = :org AND category_id = :id)
                    OR EXISTS (SELECT 1 FROM material_categories WHERE organization_id = :org AND parent_id = :id)
                """
            ),
            {"org": organization_id, "id": category_id},
        )
        return bool(res.scalar_one())

    async def delete(self, organization_id: uuid.UUID, category_id: uuid.UUID) -> bool:
        res = await self.conn.execute(
            text("DELETE FROM material_categories WHERE organization_id = :org AND id = :id"),
            {"org": organization_id, "id": category_id},
        )
        return (res.rowcount or 0) > 0

    async def uncategorised_materials(self, organization_id: uuid.UUID) -> list[dict]:
        res = await self.conn.execute(
            text(
                "SELECT id, name, category FROM materials_catalog "
                "WHERE organization_id = :org AND category_id IS NULL"
            ),
            {"org": organization_id},
        )
        return [dict(r) for r in res.mappings().all()]

    async def set_material_category(
        self, organization_id: uuid.UUID, material_id: uuid.UUID, category_id: uuid.UUID
    ) -> None:
        """Place a material that has no category yet (never moves one someone already placed)."""
        await self.conn.execute(
            text(
                "UPDATE materials_catalog SET category_id = :cat "
                "WHERE organization_id = :org AND id = :id AND category_id IS NULL"
            ),
            {"org": organization_id, "id": material_id, "cat": category_id},
        )
