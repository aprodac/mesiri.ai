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
            "SELECT site_id, work_date, trade_key, planned_item_id, man_days, source FROM labour_boq_allocations "
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
        """The lines a site's day of one trade is on, replacing what was there (a person's split, or the automatic
        one). An empty list takes it off every line, and that is remembered (BOQ-02b: "on no line", so the automatic
        split never puts it back); a list clears that mark."""
        await self.conn.execute(text(
            "DELETE FROM labour_boq_day_marks WHERE organization_id = :org AND project_id = :p "
            "AND site_id IS NOT DISTINCT FROM CAST(:s AS uuid) AND work_date = :d AND trade_key = :k"),
            {"org": organization_id, "p": project_id, "s": site_id, "d": work_date, "k": trade_key})
        if not parts:
            await self.conn.execute(text(
                "INSERT INTO labour_boq_day_marks (organization_id, project_id, site_id, work_date, trade_key, mark, "
                "created_by) VALUES (:org, :p, CAST(:s AS uuid), :d, :k, 'none', :u)"),
                {"org": organization_id, "p": project_id, "s": site_id, "d": work_date, "k": trade_key, "u": user_id})
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

    async def on_no_line(
        self, organization_id: uuid.UUID, project_id: uuid.UUID, date_from: datetime.date, date_to: datetime.date
    ) -> list[dict[str, Any]]:
        """BOQ-02b: the site-day-trades a person took off every line (site_id, work_date, trade_key)."""
        rows = await self.conn.execute(text(
            "SELECT site_id, work_date, trade_key FROM labour_boq_day_marks WHERE organization_id = :org "
            "AND project_id = :p AND mark = 'none' AND work_date BETWEEN :f AND :t"),
            {"org": organization_id, "p": project_id, "f": date_from, "t": date_to})
        return [dict(r) for r in rows.mappings().all()]

    async def keep_auto(self, organization_id: uuid.UUID, project_id: uuid.UUID, rows: list[dict[str, Any]]) -> None:
        """BOQ-02b: store automatic splits of days whose week is over, so they stop moving. A group that has rows by
        then (a person split it meanwhile) is left as it is."""
        for a in rows:
            await self.conn.execute(text(
                "INSERT INTO labour_boq_allocations (organization_id, project_id, site_id, work_date, trade_key, "
                "planned_item_id, man_days, source) SELECT :org, :p, CAST(:s AS uuid), :d, :k, :line, :md, 'auto' "
                "WHERE NOT EXISTS (SELECT 1 FROM labour_boq_allocations WHERE project_id = :p "
                "AND site_id IS NOT DISTINCT FROM CAST(:s AS uuid) AND work_date = :d AND trade_key = :k "
                "AND (source = 'person' OR planned_item_id = :line)) "
                # Two reads at once (Cost overview and Budget vs actual on one page) both store the same split: the
                # second is a no-op, never a 500 (found recording episode 9: /cost/portfolio failed, the P&L lost
                # its "Books or real").
                "ON CONFLICT DO NOTHING"),
                {"org": organization_id, "p": project_id, "s": a["site_id"], "d": a["work_date"], "k": a["trade_key"],
                 "line": a["planned_item_id"], "md": a["man_days"]})
