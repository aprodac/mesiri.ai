"""material_unit_conversions (migration 0486, WA-41): how many of a reported
unit make one stock unit of a material, per company."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class PostgresMaterialUnitConversionRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(
        self, *, organization_id: uuid.UUID, material_id: uuid.UUID, from_unit_id: uuid.UUID
    ) -> Decimal | None:
        row = (
            await self._conn.execute(
                text(
                    "SELECT per_stock_unit FROM material_unit_conversions"
                    " WHERE organization_id = :o AND material_id = :m AND from_unit_id = :u"
                ),
                {"o": organization_id, "m": material_id, "u": from_unit_id},
            )
        ).first()
        return Decimal(row[0]) if row else None

    async def upsert(
        self,
        *,
        organization_id: uuid.UUID,
        material_id: uuid.UUID,
        from_unit_id: uuid.UUID,
        per_stock_unit: Decimal,
        user_id: uuid.UUID | None,
    ) -> None:
        """Set (or replace) the company's conversion; the latest answer wins."""
        await self._conn.execute(
            text(
                "INSERT INTO material_unit_conversions"
                " (organization_id, material_id, from_unit_id, per_stock_unit, created_by)"
                " VALUES (:o, :m, :u, :p, :by)"
                " ON CONFLICT (organization_id, material_id, from_unit_id)"
                " DO UPDATE SET per_stock_unit = EXCLUDED.per_stock_unit, updated_at = now()"
            ),
            {"o": organization_id, "m": material_id, "u": from_unit_id, "p": per_stock_unit, "by": user_id},
        )
