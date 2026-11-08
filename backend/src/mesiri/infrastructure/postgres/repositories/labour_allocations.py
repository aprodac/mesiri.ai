"""Labour put on BOQ lines (CC-05): the ``labour_boq_allocations`` table (migration 0528).

Keyed by project, site, day and trade, never by attendance line (a re-sent attendance list replaces the earlier
lines, BE-10). Attendance itself is read through the Labour module's own repository
(``PostgresWorkforceReadRepository.attendance_by_site_day_trade``), never re-counted here.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class PostgresLabourAllocationRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def list(
        self,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
    ) -> list[dict[str, Any]]:
        rows = await self.conn.execute(text(
            "SELECT site_id, work_date, trade_key, planned_item_id, man_days FROM labour_boq_allocations "
            "WHERE organization_id = :org AND project_id = :p "
            "AND (CAST(:f AS date) IS NULL OR work_date >= CAST(:f AS date)) "
            "AND (CAST(:t AS date) IS NULL OR work_date <= CAST(:t AS date)) "
            "ORDER BY work_date, trade_key, created_at"),
            {"org": organization_id, "p": project_id, "f": date_from, "t": date_to})
        return [dict(r) for r in rows.mappings().all()]

    async def first_date(self, organization_id: uuid.UUID, project_id: uuid.UUID) -> datetime.date | None:
        return (await self.conn.execute(text(
            "SELECT min(work_date) FROM labour_boq_allocations WHERE organization_id = :org AND project_id = :p"),
            {"org": organization_id, "p": project_id})).scalar()

    async def replace_group(
        self,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        site_id: uuid.UUID | None,
        work_date: datetime.date,
        trade_key: str,
        parts: list[tuple[uuid.UUID, Decimal]],
        user_id: uuid.UUID | None,
    ) -> None:
        """The lines a site's day of one trade is on, replacing what was there (an empty list takes it off)."""
        await self.conn.execute(text(
            "DELETE FROM labour_boq_allocations WHERE organization_id = :org AND project_id = :p "
            "AND site_id IS NOT DISTINCT FROM CAST(:s AS uuid) AND work_date = :d AND trade_key = :k"),
            {"org": organization_id, "p": project_id, "s": site_id, "d": work_date, "k": trade_key})
        for line_id, man_days in parts:
            await self.conn.execute(text(
                "INSERT INTO labour_boq_allocations (organization_id, project_id, site_id, work_date, trade_key, "
                "planned_item_id, man_days, created_by) VALUES (:org, :p, CAST(:s AS uuid), :d, :k, :line, :md, :u)"),
                {"org": organization_id, "p": project_id, "s": site_id, "d": work_date, "k": trade_key,
                 "line": line_id, "md": man_days, "u": user_id})
