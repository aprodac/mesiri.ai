"""PostgreSQL access to a project's BOQ (CC-02): sections and lines.

A section is a ``work_packages`` row; a line is a ``work_package_planned_items`` row
(0420, rates added in 0508). Only a line's *current* revision is shown and edited: a
change of planned quantity keeps the old row as history (ADR-D5) and adds a new one,
so a past DPR keeps the quantity that applied on its date.

Every method takes the caller's connection and never commits; the request owns the
transaction. Every query is scoped by organization and project, as well as by
row-level security.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

_LINE_COLUMNS = (
    "i.id, i.work_package_id, i.work_type, i.unit_id, u.code AS unit, u.display_name AS unit_name, "
    "i.planned_quantity, i.boq_code, i.client_rate, i.labour_rate, i.material_rate, "
    "i.subcontract_rate, i.sort_order, i.revision_no, i.revision_reason, i.created_at"
)
_LINE_FIELDS = ("work_type", "unit_id", "boq_code", "client_rate", "labour_rate", "material_rate", "subcontract_rate", "sort_order")


class PostgresBoqRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    # -- reads ---------------------------------------------------------------

    async def project_exists(self, organization_id: uuid.UUID, project_id: uuid.UUID) -> bool:
        res = await self.conn.execute(
            text("SELECT 1 FROM projects WHERE id = :p AND organization_id = :org"),
            {"p": project_id, "org": organization_id},
        )
        return res.first() is not None

    async def site_in_project(self, project_id: uuid.UUID, site_id: uuid.UUID) -> bool:
        res = await self.conn.execute(
            text("SELECT 1 FROM sites WHERE id = :s AND project_id = :p"), {"s": site_id, "p": project_id}
        )
        return res.first() is not None

    async def list_sections(self, organization_id: uuid.UUID, project_id: uuid.UUID) -> list[dict]:
        res = await self.conn.execute(
            text(
                "SELECT id, project_id, site_id, code, name, sort_order FROM work_packages "
                "WHERE organization_id = :org AND project_id = :p ORDER BY sort_order, created_at"
            ),
            {"org": organization_id, "p": project_id},
        )
        return [dict(r) for r in res.mappings().all()]

    async def list_lines(self, organization_id: uuid.UUID, project_id: uuid.UUID) -> list[dict]:
        """Every current line of the project's sections, in order."""
        res = await self.conn.execute(
            text(
                f"SELECT {_LINE_COLUMNS} FROM work_package_planned_items i "
                "JOIN work_packages w ON w.id = i.work_package_id "
                "JOIN units_of_measure u ON u.id = i.unit_id "
                "WHERE i.organization_id = :org AND w.project_id = :p AND i.superseded_by_id IS NULL "
                "ORDER BY i.sort_order, i.created_at"
            ),
            {"org": organization_id, "p": project_id},
        )
        return [dict(r) for r in res.mappings().all()]

    async def get_section(
        self, organization_id: uuid.UUID, project_id: uuid.UUID, section_id: uuid.UUID
    ) -> dict | None:
        res = await self.conn.execute(
            text(
                "SELECT id, project_id, site_id, code, name, sort_order FROM work_packages "
                "WHERE id = :id AND organization_id = :org AND project_id = :p"
            ),
            {"id": section_id, "org": organization_id, "p": project_id},
        )
        row = res.mappings().first()
        return dict(row) if row else None

    async def get_line(
        self, organization_id: uuid.UUID, project_id: uuid.UUID, line_id: uuid.UUID
    ) -> dict | None:
        """The line if it is current and belongs to the project; a superseded revision is not editable."""
        res = await self.conn.execute(
            text(
                f"SELECT {_LINE_COLUMNS} FROM work_package_planned_items i "
                "JOIN work_packages w ON w.id = i.work_package_id "
                "JOIN units_of_measure u ON u.id = i.unit_id "
                "WHERE i.id = :id AND i.organization_id = :org AND w.project_id = :p "
                "AND i.superseded_by_id IS NULL"
            ),
            {"id": line_id, "org": organization_id, "p": project_id},
        )
        row = res.mappings().first()
        return dict(row) if row else None

    async def current_line_with(
        self, section_id: uuid.UUID, work_type: str, unit_id: uuid.UUID, exclude: uuid.UUID | None = None
    ) -> dict | None:
        """A current line in the section with the same work and unit (the 0420 unique rule)."""
        res = await self.conn.execute(
            text(
                "SELECT id FROM work_package_planned_items WHERE work_package_id = :s "
                "AND work_type = :w AND unit_id = :u AND superseded_by_id IS NULL "
                "AND (CAST(:x AS uuid) IS NULL OR id <> CAST(:x AS uuid))"
            ),
            {"s": section_id, "w": work_type, "u": unit_id, "x": exclude},
        )
        row = res.mappings().first()
        return dict(row) if row else None

    async def code_taken(self, project_id: uuid.UUID, code: str, exclude: uuid.UUID | None = None) -> bool:
        res = await self.conn.execute(
            text(
                "SELECT 1 FROM work_packages WHERE project_id = :p AND code = :c "
                "AND (CAST(:x AS uuid) IS NULL OR id <> CAST(:x AS uuid))"
            ),
            {"p": project_id, "c": code, "x": exclude},
        )
        return res.first() is not None

    async def section_has_activities(self, section_id: uuid.UUID) -> bool:
        res = await self.conn.execute(
            text("SELECT 1 FROM activities WHERE work_package_id = :s LIMIT 1"), {"s": section_id}
        )
        return res.first() is not None

    # -- writes --------------------------------------------------------------

    async def create_section(
        self,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        name: str,
        site_id: uuid.UUID | None,
        code: str | None,
        created_by: uuid.UUID,
    ) -> uuid.UUID:
        section_id = uuid.uuid4()
        await self.conn.execute(
            text(
                "INSERT INTO work_packages (id, organization_id, project_id, site_id, code, name, "
                "sort_order, created_by) VALUES (:id, :org, :p, :site, :code, :name, "
                "(SELECT COALESCE(max(sort_order), 0) + 1 FROM work_packages WHERE project_id = :p), :by)"
            ),
            {"id": section_id, "org": organization_id, "p": project_id, "site": site_id,
             "code": code, "name": name, "by": created_by},
        )
        return section_id

    async def update_section(self, section_id: uuid.UUID, changes: dict[str, Any]) -> None:
        if not changes:
            return
        sets = ", ".join(f"{k} = :{k}" for k in changes)
        await self.conn.execute(
            text(f"UPDATE work_packages SET {sets}, updated_at = now() WHERE id = :id"),
            {**changes, "id": section_id},
        )

    async def delete_section(self, section_id: uuid.UUID) -> None:
        """The section and every line in it, history included.

        One DELETE for all the lines: links between revisions are checked at the end of
        the statement, and clearing them first would make two revisions "current" at once.
        """
        await self.conn.execute(text("DELETE FROM work_package_planned_items WHERE work_package_id = :s"), {"s": section_id})
        await self.conn.execute(text("DELETE FROM work_packages WHERE id = :s"), {"s": section_id})

    async def create_line(
        self, organization_id: uuid.UUID, section_id: uuid.UUID, values: dict[str, Any], changed_by: uuid.UUID
    ) -> uuid.UUID:
        line_id = uuid.uuid4()
        fields = {k: values.get(k) for k in _LINE_FIELDS if k != "sort_order"}
        await self.conn.execute(
            text(
                "INSERT INTO work_package_planned_items (id, organization_id, work_package_id, work_type, "
                "unit_id, planned_quantity, boq_code, client_rate, labour_rate, material_rate, "
                "subcontract_rate, sort_order, changed_by) VALUES (:id, :org, :s, :work_type, :unit_id, "
                ":planned_quantity, :boq_code, :client_rate, :labour_rate, :material_rate, "
                ":subcontract_rate, (SELECT COALESCE(max(sort_order), 0) + 1 FROM "
                "work_package_planned_items WHERE work_package_id = :s), :by)"
            ),
            {**fields, "id": line_id, "org": organization_id, "s": section_id,
             "planned_quantity": values["planned_quantity"], "by": changed_by},
        )
        return line_id

    async def update_line(self, line_id: uuid.UUID, changes: dict[str, Any]) -> None:
        """Change a current line in place (anything but its planned quantity)."""
        if not changes:
            return
        sets = ", ".join(f"{k} = :{k}" for k in changes)
        await self.conn.execute(
            text(f"UPDATE work_package_planned_items SET {sets} WHERE id = :id"), {**changes, "id": line_id}
        )

    async def revise_quantity(
        self,
        organization_id: uuid.UUID,
        line: dict,
        quantity: Decimal,
        reason: str | None,
        changed_by: uuid.UUID,
    ) -> uuid.UUID:
        """A new revision with the new planned quantity; the old row stays as history.

        The old row is first marked superseded by itself, so the 0420 "one current line
        per work and unit" index lets the new row in; then it points at the new row.
        """
        new_id = uuid.uuid4()
        await self.conn.execute(
            text("UPDATE work_package_planned_items SET superseded_by_id = id WHERE id = :id"), {"id": line["id"]}
        )
        await self.conn.execute(
            text(
                "INSERT INTO work_package_planned_items (id, organization_id, work_package_id, work_type, "
                "unit_id, planned_quantity, boq_code, client_rate, labour_rate, material_rate, "
                "subcontract_rate, sort_order, revision_no, revision_reason, changed_by) "
                "SELECT :new, organization_id, work_package_id, work_type, unit_id, :q, boq_code, "
                "client_rate, labour_rate, material_rate, subcontract_rate, sort_order, revision_no + 1, "
                ":reason, :by FROM work_package_planned_items WHERE id = :old"
            ),
            {"new": new_id, "q": quantity, "reason": reason, "by": changed_by, "old": line["id"]},
        )
        await self.conn.execute(
            text("UPDATE work_package_planned_items SET superseded_by_id = :new WHERE id = :old"),
            {"new": new_id, "old": line["id"]},
        )
        return new_id

    async def delete_line(self, line_id: uuid.UUID) -> None:
        """The line and all its earlier revisions, in one DELETE (see ``delete_section``)."""
        chain = await self.conn.execute(
            text(
                "WITH RECURSIVE chain(id) AS (SELECT CAST(:id AS uuid) UNION "
                "SELECT i.id FROM work_package_planned_items i JOIN chain c ON i.superseded_by_id = c.id "
                "WHERE i.id <> c.id) SELECT id FROM chain"
            ),
            {"id": line_id},
        )
        ids = [r[0] for r in chain.all()]
        await self.conn.execute(text("DELETE FROM work_package_planned_items WHERE id = ANY(:ids)"), {"ids": ids})
