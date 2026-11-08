"""CC-11 (8 Nov 2026): the evening cost card on WhatsApp, to the people who run the project.

Once a day per project, after the project's own reporting cut-off (``reporting_cutoff_time`` in its zone; 18:00
in the company's zone when unset): today's green / amber / red (CC-07, the same read as the dashboard's Green / red
page, ``router.variance_for``): the overall colour, the worst lines with why, the labour not on a BOQ line, one line
per site when there are several. Queued like the other reminders (``application/procurement/alerts.queue_reminders``;
outside the 24-hour window it waits for the person's next message, no Meta template). Nothing when nothing was
measured and no labour was put on a line today, or when the company has the ``cost`` module off.

To the owner, admins and project managers on the project (the roles that see the BOQ's rates, D-CC4). English only
for now, like the schedule and material notes.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

RULE = "cost_evening_card"
MANAGER_ROLES = ("ADMIN", "OWNER", "SUPER_ADMIN", "PROJECT_MANAGER")
DEFAULT_CUTOFF = "18:00"
_DOT = {"green": "🟢", "amber": "🟠", "red": "🔴", "grey": "⚪"}
_WORD = {"green": "Green", "amber": "Amber", "red": "Red", "grey": "Not judged"}
#: Lines named in the card; the rest are counted.
TOP = 4


def _rs(value: Any) -> str:
    """Rupees, whole, in Indian grouping: ₹1,23,456."""
    n = Decimal(str(value)).quantize(Decimal(1))
    digits = str(abs(n))
    if len(digits) > 3:
        rest, groups = digits[:-3], [digits[-3:]]
        while rest:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        digits = ",".join(groups)
    return ("-" if n < 0 else "") + "₹" + digits


def _qty(value: Any) -> str:
    n = Decimal(str(value))
    return format(n.quantize(Decimal(1)) if n == n.to_integral_value() else n.normalize(), "f")


def _line(ln: dict) -> str:
    work = ln["work"]
    if ln["reason"] in ("over_budget", "near_budget", "within_budget"):
        per = f" ({_rs(ln['cost_per_unit'])}/{ln['unit']}, budget {_rs(ln['labour_rate'])})" if ln["cost_per_unit"] else ""
        return (f"{_DOT[ln['colour']]} {work}: {_rs(ln['labour_cost'])} of labour for {_qty(ln['done_quantity'])} "
                f"{ln['unit']}{per}")
    if ln["reason"] == "labour_no_work":
        return f"{_DOT['red']} {work}: {_rs(ln['labour_cost'])} of labour, no {ln['unit']} measured"
    if ln["reason"] == "no_labour":
        return f"{_DOT['grey']} {work}: {_qty(ln['done_quantity'])} {ln['unit']} done, no labour put on it"
    if ln["reason"] == "no_labour_rate":
        return f"{_DOT['grey']} {work}: no labour rate in the BOQ"
    return f"{_DOT['grey']} {work}: labour with no wage"


def card_message(project_name: str, day: datetime.date, variance: dict, sites: list[tuple[str, dict]]) -> str | None:
    """The card, or None when nothing was measured and no labour was put on a line that day.

    ``variance``: ``router.variance_for`` for the project and day. ``sites``: (site name, its variance) when the
    project has more than one site with something that day."""
    lines = variance["lines"]
    if not lines:
        return None
    s = variance["summary"]
    head = f"🚦 *{project_name}*: today's cost ({day:%a} {day.day} {day:%b})"
    if s["colour"] == "grey":
        overall = "Nothing to colour yet: no line has both work measured and labour on it."
    else:
        diff = Decimal(s["difference"])
        gap = f"{_rs(-diff)} over" if diff < 0 else f"{_rs(diff)} under"
        overall = (f"{_DOT[s['colour']]} *{_WORD[s['colour']]}*: {_rs(s['earned_labour'])} of work earned for "
                   f"{_rs(s['labour_cost'])} of labour, {gap}.")
    body = [head, overall]
    body += [f"• {_line(ln)}" for ln in lines[:TOP]]
    if len(lines) > TOP:
        body.append(f"• and {len(lines) - TOP} more lines.")
    left = Decimal(variance["labour"]["not_on_a_line"]["cost"])
    if left > 0:
        body.append(f"Labour not on a BOQ line: {_rs(left)} ({_qty(variance['labour']['not_on_a_line']['man_days'])} "
                    "man-days), so no line shows it.")
    if len(sites) > 1:
        body.append("Sites: " + ", ".join(f"{name} {_DOT[v['summary']['colour']]}" for name, v in sites))
    body.append("Cost control › Green / red on the dashboard.")
    return "\n".join(body)


async def _cost_module_on(conn: AsyncConnection, organization_id: uuid.UUID) -> bool:
    from mesiri.domains.organizations import settings as org_settings
    from mesiri.infrastructure.postgres.repositories.organization_settings import (
        PostgresOrganizationSettingsRepository,
    )

    stored = await PostgresOrganizationSettingsRepository(conn).get(organization_id, org_settings.ENABLED_MODULES)
    return org_settings.module_enabled("cost", stored)


def _past_cutoff(cutoff: str | None, zone: str, now: datetime.datetime) -> bool:
    from mesiri.application.automations.scheduling import local_now, parse_time_of_day

    try:
        at = parse_time_of_day(cutoff or DEFAULT_CUTOFF)
    except (ValueError, IndexError):
        at = parse_time_of_day(DEFAULT_CUTOFF)
    return local_now(timezone_name=zone, now_utc=now).time() >= at


async def queue_cost_cards(conn: AsyncConnection, organization_id: uuid.UUID, today: datetime.date,
                           now: datetime.datetime) -> int:
    from mesiri.application.dpr.project_day import DEFAULT_ZONE
    from mesiri.domains.costing.router import variance_for
    from mesiri.domains.schedule.reminders import _people
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

    if not await _cost_module_on(conn, organization_id):
        return 0
    zone = (await conn.execute(text("SELECT NULLIF(timezone, 'UTC') FROM organizations WHERE id = :org"),
                               {"org": organization_id})).scalar() or DEFAULT_ZONE
    projects = (await conn.execute(text(
        "SELECT p.id, p.name, p.reporting_cutoff_time, p.reporting_timezone FROM projects p "
        "WHERE p.organization_id = :org AND COALESCE(p.status, '') <> 'archived' "
        "AND COALESCE(p.stage, '') NOT IN ('tender', 'closed') AND EXISTS (SELECT 1 FROM work_package_planned_items i "
        "JOIN work_packages w ON w.id = i.work_package_id WHERE w.project_id = p.id AND i.superseded_by_id IS NULL)"),
        {"org": organization_id})).mappings().all()
    repo = PostgresNotificationRepository(conn)
    queued = 0
    for proj in projects:
        if not _past_cutoff(proj["reporting_cutoff_time"], proj["reporting_timezone"] or zone, now):
            continue
        variance = await variance_for(conn, organization_id, proj["id"], today, today)
        if not variance["lines"]:
            continue
        sites = []
        names = (await conn.execute(text("SELECT id, name FROM sites WHERE project_id = :p ORDER BY name"),
                                    {"p": proj["id"]})).mappings().all()
        if len(names) > 1:
            for site in names:
                v = await variance_for(conn, organization_id, proj["id"], today, today, site["id"])
                if v["lines"]:
                    sites.append((site["name"], v))
        note = card_message(proj["name"], today, variance, sites)
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
