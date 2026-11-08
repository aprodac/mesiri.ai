"""PostgreSQL reads and writes for material norms per BOQ line (MP-01, migration 0523).

A norm says what one unit of a BOQ line consumes: "1 m³ of M20 in columns: 8 bags cement, 5% wastage". Norms hang off
the line's current revision (``PostgresBoqRepository.revise_quantity`` moves them to the new row).

Every function takes the request's connection and never commits.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_COLUMNS = (
    "n.id, n.planned_item_id AS line_id, n.material_id, m.name AS material, n.unit_id, u.code AS unit, "
    "n.quantity_per_unit, n.wastage_pct, n.note"
)


class MaterialNormRepository:
    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def for_project(self, organization_id: uuid.UUID, project_id: uuid.UUID) -> dict[uuid.UUID, list[dict]]:
        """Norms of every current BOQ line of the project, by line id, in material-name order."""
        rows = (await self.conn.execute(text(
            f"SELECT {_COLUMNS} FROM boq_material_norms n "
            "JOIN work_package_planned_items i ON i.id = n.planned_item_id "
            "JOIN work_packages w ON w.id = i.work_package_id "
            "JOIN materials_catalog m ON m.id = n.material_id JOIN units_of_measure u ON u.id = n.unit_id "
            "WHERE n.organization_id = :org AND w.project_id = :p AND i.superseded_by_id IS NULL "
            "ORDER BY lower(m.name)"), {"org": organization_id, "p": project_id})).mappings().all()
        out: dict[uuid.UUID, list[dict]] = defaultdict(list)
        for r in rows:
            out[r["line_id"]].append(dict(r))
        return dict(out)

    async def for_line(self, organization_id: uuid.UUID, line_id: uuid.UUID) -> list[dict]:
        rows = (await self.conn.execute(text(
            f"SELECT {_COLUMNS} FROM boq_material_norms n "
            "JOIN materials_catalog m ON m.id = n.material_id JOIN units_of_measure u ON u.id = n.unit_id "
            "WHERE n.organization_id = :org AND n.planned_item_id = :line ORDER BY lower(m.name)"),
            {"org": organization_id, "line": line_id})).mappings().all()
        return [dict(r) for r in rows]

    async def materials(self, organization_id: uuid.UUID, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
        """Catalog rows (id, name, active, default unit) for the given ids in this company."""
        if not ids:
            return {}
        rows = (await self.conn.execute(text(
            "SELECT id, name, is_active, default_unit_id FROM materials_catalog "
            "WHERE organization_id = :org AND id = ANY(:ids)"), {"org": organization_id, "ids": ids})).mappings().all()
        return {r["id"]: dict(r) for r in rows}

    async def replace(
        self, organization_id: uuid.UUID, line_id: uuid.UUID, norms: list[dict], user_id: uuid.UUID
    ) -> None:
        """The line's norms become exactly ``norms`` (material_id, unit_id, quantity_per_unit, wastage_pct, note)."""
        await self.conn.execute(text(
            "DELETE FROM boq_material_norms WHERE organization_id = :org AND planned_item_id = :line"),
            {"org": organization_id, "line": line_id})
        for n in norms:
            await self.conn.execute(text(
                "INSERT INTO boq_material_norms (organization_id, planned_item_id, material_id, unit_id, "
                "quantity_per_unit, wastage_pct, note, created_by) "
                "VALUES (:org, :line, :m, :u, :q, :w, :note, :by)"),
                {"org": organization_id, "line": line_id, "m": n["material_id"], "u": n["unit_id"],
                 "q": n["quantity_per_unit"], "w": n.get("wastage_pct") or Decimal(0), "note": n.get("note"),
                 "by": user_id})

    async def lines_like(
        self, organization_id: uuid.UUID, project_id: uuid.UUID, line: dict
    ) -> list[dict]:
        """Other current lines of the project with the same work (case and spacing ignored) and unit, and whether
        each already has norms."""
        rows = (await self.conn.execute(text(
            "SELECT i.id, EXISTS (SELECT 1 FROM boq_material_norms n WHERE n.planned_item_id = i.id) AS has_norms "
            "FROM work_package_planned_items i JOIN work_packages w ON w.id = i.work_package_id "
            "WHERE i.organization_id = :org AND w.project_id = :p AND i.superseded_by_id IS NULL AND i.id <> :id "
            "AND i.unit_id = :u AND lower(regexp_replace(i.work_type, '\\s+', ' ', 'g')) = "
            "lower(regexp_replace(:w, '\\s+', ' ', 'g'))"),
            {"org": organization_id, "p": project_id, "id": line["id"], "u": line["unit_id"],
             "w": line["work_type"]})).mappings().all()
        return [dict(r) for r in rows]
