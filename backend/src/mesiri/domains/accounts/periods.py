"""ACC-02: financial years (April to March, D-ACC7) and months (``accounting_periods``), open or closed.

A closed month is never changed by the posting sweep: when a record of a closed month changes, the difference is
posted on the first open day after the closed months and marked "changed after close" (D-ACC2). Nothing on site is
ever blocked by a closed month.

Closing and reopening are for the roles that manage money; reopening is the owner's or an admin's, with a reason
(D-ACC6). The checklist before closing is ACC-14.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

#: The first month of a financial year (April).
FY_START_MONTH = 4


def fy_start(day: datetime.date) -> datetime.date:
    year = day.year if day.month >= FY_START_MONTH else day.year - 1
    return datetime.date(year, FY_START_MONTH, 1)


def fy_end(day: datetime.date) -> datetime.date:
    start = fy_start(day)
    return datetime.date(start.year + 1, FY_START_MONTH, 1) - datetime.timedelta(days=1)


def fy_label(day: datetime.date) -> str:
    """``2026-27`` for any day from 1 Apr 2026 to 31 Mar 2027."""
    start = fy_start(day).year
    return f"{start}-{str(start + 1)[-2:]}"


def month_start(day: datetime.date) -> datetime.date:
    return day.replace(day=1)


def month_end(day: datetime.date) -> datetime.date:
    nxt = (day.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return nxt - datetime.timedelta(days=1)


def first_open_day(closed: list[tuple[datetime.date, datetime.date]], after: datetime.date) -> datetime.date:
    """The first day on or after ``after`` that is in no closed month: where a change to a closed month is posted."""
    day = after
    spans = sorted(closed)
    moved = True
    while moved:
        moved = False
        for start, end in spans:
            if start <= day <= end:
                day = end + datetime.timedelta(days=1)
                moved = True
    return day


async def closed_spans(conn: AsyncConnection, org: uuid.UUID) -> list[tuple[datetime.date, datetime.date]]:
    return [(r[0], r[1]) for r in (await conn.execute(text(
        "SELECT starts_on, ends_on FROM accounting_periods WHERE organization_id = :org AND status = 'closed' "
        "ORDER BY starts_on"), {"org": org}))]


async def ensure_months(conn: AsyncConnection, org: uuid.UUID, days: set[datetime.date]) -> None:
    """A month row for every month the books have an entry in (all open until someone closes them)."""
    for start in sorted({month_start(d) for d in days}):
        await conn.execute(text(
            "INSERT INTO accounting_periods (organization_id, starts_on, ends_on) VALUES (:org, :s, :e) "
            "ON CONFLICT (organization_id, starts_on) DO NOTHING"), {"org": org, "s": start, "e": month_end(start)})


async def list_months(conn: AsyncConnection, org: uuid.UUID) -> list[dict[str, Any]]:
    return [dict(r) for r in (await conn.execute(text(
        "SELECT p.id, p.starts_on, p.ends_on, p.status, p.closed_at, cu.full_name AS closed_by, p.reopened_at, "
        "ru.full_name AS reopened_by, p.reopen_reason, "
        "(SELECT COUNT(*) FROM journal_entries j WHERE j.organization_id = p.organization_id "
        " AND j.entry_date BETWEEN p.starts_on AND p.ends_on) AS entries, "
        "(SELECT COUNT(*) FROM journal_entries j WHERE j.organization_id = p.organization_id AND j.after_close "
        " AND j.entry_date BETWEEN p.starts_on AND p.ends_on) AS changed_after_close "
        "FROM accounting_periods p LEFT JOIN users cu ON cu.id = p.closed_by LEFT JOIN users ru ON ru.id = p.reopened_by "
        "WHERE p.organization_id = :org ORDER BY p.starts_on DESC"), {"org": org})).mappings()]


async def set_status(conn: AsyncConnection, org: uuid.UUID, starts_on: datetime.date, status: str,
                     user_id: uuid.UUID, reason: str | None = None) -> None:
    await ensure_months(conn, org, {starts_on})
    if status == "closed":
        await conn.execute(text(
            "UPDATE accounting_periods SET status = 'closed', closed_by = :u, closed_at = now() "
            "WHERE organization_id = :org AND starts_on = :s"), {"org": org, "s": starts_on, "u": user_id})
    else:
        await conn.execute(text(
            "UPDATE accounting_periods SET status = 'open', reopened_by = :u, reopened_at = now(), reopen_reason = :r "
            "WHERE organization_id = :org AND starts_on = :s"), {"org": org, "s": starts_on, "u": user_id, "r": reason})
