"""PRC-48: the physical stock count -- book against counted, the difference in units and rupees, approved into the
ledger.

A count is started for one site: every item it holds, one category, or the ``TOP`` most valuable (quantity x the
average rate, ``valuation.py``). The book quantity is frozen at the start; the site counts on a phone (partial saves,
"not counted" allowed) or on WhatsApp ("count: cement 92 bags"). Review sorts the differences by rupees. Approval
(admin / owner, D-P2-2) posts each difference as ADJUSTMENT_IN / ADJUSTMENT_OUT through the one posting path
(``materials.router.record_inflow`` / ``record_outflow``) with the count as reference, so book stock then equals the
count (plus whatever moved since it started). An approved count is never edited; a new count corrects it.

A site with stock that moved in the last ``DUE_DAYS`` days and no count approved in them is "due": the office hears
on Mondays (``queue_count_reminders``).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

TOP = 20
DUE_DAYS = 30
RULE = "stock_count_due"
#: D-P2-2 (default until PRC-12 is decided): who approves a count's differences into the ledger.
APPROVE_ROLES = ("ADMIN", "OWNER", "SUPER_ADMIN")
MANAGER_ROLES = ("ADMIN", "OWNER", "SUPER_ADMIN", "PROJECT_MANAGER")
REASONS = ("wastage", "theft", "wrong_entry", "unrecorded_use", "found", "other")


def ref(number: int) -> str:
    return f"SC-{number:04d}"


def num(v: Any) -> str:
    return f"{Decimal(v).normalize():f}"


def may_approve(role: str | None) -> bool:
    return str(role or "").upper() in APPROVE_ROLES


def difference(line: dict[str, Any]) -> dict[str, Any]:
    """Counted minus book for one line (None while not counted), and its value at the line's rate."""
    if line.get("counted_qty") is None:
        return {"difference": None, "difference_value": None}
    diff = Decimal(line["counted_qty"]) - Decimal(line["book_qty"])
    rate = line.get("rate")
    return {"difference": diff, "difference_value": diff * Decimal(rate) if rate is not None else None}


def review(lines: list[dict[str, Any]]) -> dict[str, Any]:
    """The count's figures: counted, not counted, differing, the net and gross rupee difference."""
    counted = [x for x in lines if x.get("counted_qty") is not None]
    diffs = [difference(x) for x in counted]
    differing = [d for d in diffs if d["difference"]]
    values = [d["difference_value"] for d in differing if d["difference_value"] is not None]
    return {"lines": len(lines), "counted": len(counted), "not_counted": len(lines) - len(counted),
            "differing": len(differing), "net_value": sum(values, Decimal(0)),
            "gross_value": sum((abs(v) for v in values), Decimal(0))}


def pick_top(rows: list[dict[str, Any]], rates: dict[str, Decimal], n: int = TOP) -> list[dict[str, Any]]:
    """The ``n`` items held with the highest value (unpriced last)."""
    return sorted(rows, key=lambda r: -(Decimal(str(r["closing"])) * rates.get(str(r["material_id"]), Decimal(-1))))[:n]


def due_message(project_name: str, sites: list[dict[str, Any]]) -> str | None:
    if not sites:
        return None
    lines = [f"• {s['name']}: " + (f"last counted {s['last'].strftime('%d %b')}" if s["last"] else "never counted")
             for s in sites[:8]]
    return (f"📋 *{project_name}*: stock count due\n" + "\n".join(lines)
            + f"\nCount the stock once every {DUE_DAYS} days: Materials › Stock count on the dashboard, or send "
            "\"count: cement 92 bags\" once a count is started.")


async def last_counted(conn: AsyncConnection, organization_id: uuid.UUID) -> dict[str, datetime.datetime]:
    rows = (await conn.execute(text(
        "SELECT site_id, MAX(approved_at) AS last FROM stock_counts WHERE organization_id = :org AND status = 'approved' "
        "GROUP BY site_id"), {"org": organization_id})).all()
    return {str(r.site_id): r.last for r in rows}


async def due_sites(conn: AsyncConnection, organization_id: uuid.UUID, today: datetime.date) -> list[dict[str, Any]]:
    """Sites whose stock moved in the last ``DUE_DAYS`` days, with no count approved in them and none open."""
    since = today - datetime.timedelta(days=DUE_DAYS)
    rows = (await conn.execute(text(
        """
        SELECT s.id, s.name, s.project_id, p.name AS project_name,
               (SELECT MAX(c.approved_at) FROM stock_counts c WHERE c.site_id = s.id AND c.status = 'approved') AS last
          FROM sites s JOIN projects p ON p.id = s.project_id
         WHERE s.organization_id = :org AND COALESCE(p.status, '') <> 'archived'
           AND COALESCE(p.stage, '') NOT IN ('tender', 'closed')
           AND EXISTS (SELECT 1 FROM material_movements m WHERE m.site_id = s.id AND m.occurred_at >= :since)
           AND NOT EXISTS (SELECT 1 FROM stock_counts c WHERE c.site_id = s.id AND (c.status = 'open'
                           OR (c.status = 'approved' AND c.approved_at >= :since)))
         ORDER BY p.name, s.name
        """), {"org": organization_id, "since": since})).mappings().all()
    return [dict(r) for r in rows]


async def queue_count_reminders(conn: AsyncConnection, organization_id: uuid.UUID, today: datetime.date) -> int:
    """Mondays: one note per project to the people who run it, naming the sites due for a count."""
    if today.weekday() != 0:
        return 0
    from mesiri.domains.schedule.reminders import _people
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

    by_project: dict[uuid.UUID, list[dict]] = {}
    for s in await due_sites(conn, organization_id, today):
        by_project.setdefault(s["project_id"], []).append(s)
    repo = PostgresNotificationRepository(conn)
    queued = 0
    for project_id, sites in by_project.items():
        message = due_message(sites[0]["project_name"], sites)
        if message is None:
            continue
        for user_id in await _people(conn, organization_id, project_id, MANAGER_ROLES):
            async with conn.begin_nested():
                claimed = await repo.claim(
                    organization_id=organization_id, rule_key=RULE, subject_id=f"{project_id}:{user_id}",
                    occurred_on=today, recipient_user_id=user_id, project_id=project_id, site_id=None,
                    payload={"message": message, "hold_until_window": True, "hold_days": 2})
            queued += 1 if claimed else 0
    return queued
