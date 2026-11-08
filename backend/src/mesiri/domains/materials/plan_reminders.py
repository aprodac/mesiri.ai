"""MP-03 (8 Nov 2026): "order cement by Thursday" comes to the people who order, before the site runs out.

One note a day per project, queued like the other reminders (``application/procurement/alerts.queue_reminders``;
outside the 24-hour window it waits for the person's next message, no Meta template), to the people who run the
project (owner, admin, project manager on it): the materials of the material plan (MP-02) whose order-by day is
within ``SOON_DAYS`` (or has passed), grouped in one message. Nothing when nothing needs ordering. A material stops
appearing once enough is in stock or on an open order (the plan counts open orders).

English only for now, like the schedule notes (ST-11 translates both).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

RULE = "material_order_by"
#: Materials whose order-by day is within this many days are in the note.
SOON_DAYS = 2
#: The plan looks this many weeks ahead for the note.
WEEKS = 4
MANAGER_ROLES = ("ADMIN", "OWNER", "SUPER_ADMIN", "PROJECT_MANAGER")


def _day(d: datetime.date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _num(value: Any) -> str:
    n = Decimal(str(value))
    return f"{n.quantize(Decimal(1)) if n == n.to_integral_value() else n.normalize():,}"


def due(rows: list[dict[str, Any]], today: datetime.date) -> list[dict[str, Any]]:
    """The plan's rows to order now or within ``SOON_DAYS``, soonest first."""
    soon = today + datetime.timedelta(days=SOON_DAYS)
    return sorted((r for r in rows if r.get("order_by") and r["order_by"] <= soon), key=lambda r: r["order_by"])


def order_message(project_name: str, rows: list[dict[str, Any]], today: datetime.date) -> str | None:
    """The note, or None when nothing needs ordering soon."""
    rows = due(rows, today)
    if not rows:
        return None
    lines = []
    for r in rows[:6]:
        held = Decimal(r["on_hand"]) + Decimal(r["on_order"])
        when = "today" if r["order_by"] <= today else _day(r["order_by"])
        if r["order_by"] < today:
            when = f"today (it should have gone {_day(r['order_by'])})"
        source = f", {r['supplier']} takes {r['lead_days']} days" if r.get("supplier") and r.get("lead_known") else ""
        lines.append(
            f"• *{r['material']}*: {_num(r['short_by'])} {r['unit']} more needed, short from {_day(r['short_day'])} "
            f"({_num(held)} in stock and ordered). Order by {when}{source}.")
    more = len(rows) - 6
    if more > 0:
        lines.append(f"• and {more} more.")
    return (f"📦 *{project_name}*: materials to order\n" + "\n".join(lines)
            + "\nFrom the BOQ and the schedule. Planning › Material plan on the dashboard.")


async def queue_material_reminders(conn: AsyncConnection, organization_id: uuid.UUID, today: datetime.date) -> int:
    from mesiri.domains.materials.plan_router import load_plan
    from mesiri.domains.schedule.reminders import _people
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

    projects = (await conn.execute(text(
        "SELECT p.id, p.name FROM projects p WHERE p.organization_id = :org AND COALESCE(p.status, '') <> 'archived' "
        "AND p.stage NOT IN ('tender', 'closed') AND EXISTS (SELECT 1 FROM boq_material_norms n "
        "JOIN work_package_planned_items i ON i.id = n.planned_item_id JOIN work_packages w ON w.id = i.work_package_id "
        "WHERE w.project_id = p.id AND i.superseded_by_id IS NULL)"), {"org": organization_id})).mappings().all()
    repo = PostgresNotificationRepository(conn)
    queued = 0
    for proj in projects:
        result = await load_plan(conn, organization_id, proj["id"], today, WEEKS)
        note = order_message(proj["name"], result["materials"], today)
        if note is None:
            continue
        for user_id in await _people(conn, organization_id, proj["id"], MANAGER_ROLES):
            async with conn.begin_nested():
                claimed = await repo.claim(
                    organization_id=organization_id, rule_key=RULE, subject_id=f"{proj['id']}:{user_id}",
                    occurred_on=today, recipient_user_id=user_id, project_id=proj["id"], site_id=None,
                    payload={"message": note, "hold_until_window": True, "hold_days": 1})
            queued += 1 if claimed else 0
    return queued
