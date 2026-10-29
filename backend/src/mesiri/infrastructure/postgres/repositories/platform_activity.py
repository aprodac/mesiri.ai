"""Read-only: how much the platform is being used, for the control panel's
Overview (SA-18).

Counts over what is already recorded -- `inbound_messages` (a WhatsApp
message from a company's people), `daily_reports` (a project DPR, PUBLISHED
once sent) and `projects` (each project's DPR send time and the local date it
last went). Days are Indian calendar days. Takes an externally supplied
connection and never commits.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from mesiri.domains.organizations.lifecycle import operational_sql

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

_INDIAN_DAY = "(({col}) AT TIME ZONE 'Asia/Kolkata')::date"


class PostgresPlatformActivityRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def _all(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows = (await self._conn.execute(sa.text(sql), params)).mappings().all()
        return [dict(r) for r in rows]

    async def by_day(self, *, first_day: dt.date, last_day: dt.date) -> list[dict[str, Any]]:
        """Per Indian day in [first_day, last_day], oldest first, every day
        present: messages received, the companies and people who sent them,
        and project DPRs sent for that day."""
        day = _INDIAN_DAY.format(col="im.received_at")
        return await self._all(
            "WITH msgs AS ("
            f" SELECT {day} AS day, count(*) AS messages,"
            "  count(DISTINCT im.organization_id) AS active_companies,"
            "  count(DISTINCT im.sender_wa_id) AS active_people"
            " FROM inbound_messages im"
            " WHERE im.received_at >= (CAST(:first AS date) AT TIME ZONE 'Asia/Kolkata')"
            " GROUP BY 1"
            "), dprs AS ("
            " SELECT dr.report_date AS day, count(*) AS dprs_sent FROM daily_reports dr"
            " WHERE dr.level = 'PROJECT' AND dr.status = 'PUBLISHED'"
            "  AND dr.report_date BETWEEN :first AND :last GROUP BY 1"
            ") "
            "SELECT d.day::date AS day, COALESCE(m.messages, 0) AS messages,"
            " COALESCE(m.active_companies, 0) AS active_companies,"
            " COALESCE(m.active_people, 0) AS active_people,"
            " COALESCE(p.dprs_sent, 0) AS dprs_sent "
            "FROM generate_series(CAST(:first AS date), CAST(:last AS date), interval '1 day') AS d(day)"
            " LEFT JOIN msgs m ON m.day = d.day::date LEFT JOIN dprs p ON p.day = d.day::date "
            "ORDER BY d.day",
            {"first": first_day, "last": last_day},
        )

    async def unanswered(self, *, older_than: dt.timedelta, within: dt.timedelta) -> dict[str, Any]:
        """Messages still waiting for a reply `older_than` after they came in
        (looking back `within`), and since when the oldest has waited. A photo
        held for "what is this photo for?" waits here too."""
        rows = await self._all(
            "SELECT count(*) AS count, min(received_at) AS oldest FROM inbound_messages"
            " WHERE processing_status = 'pending'"
            "  AND received_at < now() - CAST(:older AS interval)"
            "  AND received_at > now() - CAST(:within AS interval)",
            {"older": older_than, "within": within},
        )
        return rows[0]

    async def by_company(self, *, since: dt.datetime) -> list[dict[str, Any]]:
        """Per company that has ever sent a message: messages and people
        since `since`, project DPRs sent for days since then, and when its
        last message came."""
        return await self._all(
            "SELECT im.organization_id,"
            " count(*) FILTER (WHERE im.received_at >= :since) AS messages,"
            " count(DISTINCT im.sender_wa_id) FILTER (WHERE im.received_at >= :since) AS people,"
            " max(im.received_at) AS last_message_at,"
            " (SELECT count(*) FROM daily_reports dr WHERE dr.organization_id = im.organization_id"
            "   AND dr.level = 'PROJECT' AND dr.status = 'PUBLISHED'"
            f"   AND dr.report_date >= {_INDIAN_DAY.format(col='CAST(:since AS timestamptz)')})"
            "   AS dprs_sent "
            "FROM inbound_messages im WHERE im.organization_id IS NOT NULL "
            "GROUP BY im.organization_id",
            {"since": since},
        )

    async def dpr_projects(self) -> list[dict[str, Any]]:
        """Projects that send a DPR on their own (auto DPR on, not archived),
        in companies that may use Mesiri now -- the same set the DPR sender
        works through (application/projects/auto_dpr.py)."""
        return await self._all(
            "SELECT p.id, p.name, p.organization_id, o.name AS organization_name,"
            " p.reporting_timezone, p.dpr_send_deadline, p.dpr_last_sent_on "
            "FROM projects p JOIN organizations o ON o.id = p.organization_id "
            f"WHERE p.auto_generate_dpr = true AND p.status != 'archived' AND {operational_sql('o')}",
            {},
        )
