"""ST-04 (8 Nov 2026): the schedule comes to people on WhatsApp; nobody has to open it to find a delay.

Two notes, queued like the other reminders (``application/procurement/alerts.queue_reminders``; outside the 24-hour
window they wait for the person's next message, no Meta template):

- **Delay alert**, once a day, to the people who run the project (owner, admin, project manager on it), only when
  something is late or behind: what, by how much, what it pushes, and the forecast finish against the contract.
  Nothing when all is on time.
- **This week**, on Monday, to everyone on the project with WhatsApp (not finance): what starts, runs and should
  finish this week, and what is already late, so the site works in the planned order. It ends by reminding them
  that their usual work updates fill the schedule.

Only projects that have a schedule (dated activities) and are not closed or still a tender get either note.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.schedule import logic

DELAY_RULE = "schedule_delays"
WEEK_RULE = "schedule_this_week"
MANAGER_ROLES = ("ADMIN", "OWNER", "SUPER_ADMIN", "PROJECT_MANAGER")
#: Roles that get the Monday note (everyone who works on a project; finance does not run the site).
WEEK_ROLES = ("ADMIN", "OWNER", "SUPER_ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "SUPERVISOR")


def _day(d: datetime.date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _days(n: int) -> str:
    return f"{n} day{'s' if n != 1 else ''}"


def delay_message(project_name: str, schedule: dict[str, Any]) -> str | None:
    """The owner / PM note, or None when nothing is late or behind."""
    acts = [a for a in schedule["activities"] if a["state"] in (logic.LATE, logic.BEHIND)]
    if not acts:
        return None
    acts.sort(key=lambda a: (a["state"] != logic.LATE, -(a["slip_days"] or a["days_late"] or 0)))
    names = {a["id"]: a["name"] for a in schedule["activities"]}
    lines = []
    for a in acts[:3]:
        progress = f", {a['progress']}% done" if a["progress"] is not None else ""
        not_started = not a["actual_start"] and not a["progress"]
        if a["state"] == logic.LATE:
            what = f"*{a['name']}* is {_days(a['days_late'])} late{progress}"
        elif not_started:
            what = f"*{a['name']}* has not started (planned {_day(a['start'])})"
        else:
            what = f"*{a['name']}* is behind{progress}"
        if a["forecast_end"] and a["slip_days"]:
            what += f": {'starting today' if not_started else 'at this pace'} it finishes {_day(a['forecast_end'])}"
        pushed = [names[x["id"]] for x in schedule["activities"] if x["pushed_days"] and any(
            p["id"] == a["id"] for p in x["after"])]
        if pushed:
            what += f" and pushes {', '.join(pushed[:3])}"
        lines.append("• " + what + ".")
    more = len(acts) - 3
    if more > 0:
        lines.append(f"• and {more} more.")
    s = schedule["summary"]
    finish = ""
    if s.get("forecast_finish") and s.get("slip_days"):
        target = s.get("contract_finish") or s.get("planned_finish")
        finish = (f"\nForecast finish {_day(s['forecast_finish'])}, {_days(s['slip_days'])} after "
                  f"{'the contract date' if s.get('contract_finish') else 'the plan'} ({_day(target)}).")
    return f"⏱️ *{project_name}* schedule\n" + "\n".join(lines) + finish + "\nPlanning › Schedule on the dashboard."


def week_message(project_name: str, schedule: dict[str, Any], today: datetime.date) -> str | None:
    """The Monday note: this week's work in order, and what is already late. None when the week is empty."""
    week_end = today + logic.DAY * 6
    late = [a for a in schedule["activities"] if a["state"] == logic.LATE]
    starting, running, finishing, waiting = [], [], [], []
    for a in schedule["activities"]:
        if not a["start"] or a["state"] in (logic.DONE, logic.LATE):
            continue
        if today <= a["start"] <= week_end:
            starting.append(a)
        elif a["start"] < today and a["end"] >= today:
            if not a["actual_start"] and not a["progress"]:
                waiting.append(a)  # should be running, has not started
            else:
                (finishing if a["end"] <= week_end else running).append(a)
    if not (starting or running or finishing or waiting or late):
        return None
    parts = []
    if starting:
        parts.append("Starts: " + ", ".join(
            f"{a['name']} ({'milestone ' if a['milestone'] else ''}{_day(a['start'])})" for a in starting[:5]))
    if finishing:
        parts.append("Should finish: " + ", ".join(
            f"{a['name']} ({_day(a['end'])}{', ' + str(a['progress']) + '% now' if a['progress'] is not None else ''})"
            for a in finishing[:5]))
    if running:
        parts.append("Continues: " + ", ".join(a["name"] for a in running[:5]))
    if waiting:
        parts.append("⚠️ Should have started: " + ", ".join(f"{a['name']} ({_day(a['start'])})" for a in waiting[:5]))
    if late:
        parts.append("⚠️ Late: " + ", ".join(f"{a['name']} ({_days(a['days_late'])})" for a in late[:5]))
    return (f"📅 *This week at {project_name}* ({_day(today)} - {_day(week_end)})\n" + "\n".join(parts)
            + "\nSend your work updates as usual: they fill in the schedule.")


async def _people(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, roles: tuple[str, ...]) -> list:
    """Active people with WhatsApp in these roles who are on the project (org-wide admins and owners always are)."""
    return (await conn.execute(text(
        "SELECT DISTINCT u.id FROM users u LEFT JOIN project_members m ON m.user_id = u.id AND m.project_id = :p "
        "WHERE u.organization_id = :org AND u.status = 'active' AND u.whatsapp_number IS NOT NULL "
        "AND upper(u.role) = ANY(:roles) AND (m.id IS NOT NULL OR upper(u.role) IN ('ADMIN', 'OWNER', 'SUPER_ADMIN'))"),
        {"org": org, "p": project_id, "roles": list(roles)})).scalars().all()


async def queue_schedule_reminders(conn: AsyncConnection, organization_id: uuid.UUID, today: datetime.date) -> int:
    from mesiri.domains.schedule import store
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

    projects = (await conn.execute(text(
        "SELECT p.id, p.name FROM projects p WHERE p.organization_id = :org AND COALESCE(p.status, '') <> 'archived' "
        "AND p.stage NOT IN ('tender', 'closed') AND EXISTS (SELECT 1 FROM work_packages w WHERE w.project_id = p.id "
        "AND w.planned_start IS NOT NULL)"), {"org": organization_id})).mappings().all()
    repo = PostgresNotificationRepository(conn)
    queued = 0
    for proj in projects:
        schedule = await store.load(conn, organization_id, proj["id"], today)
        notes = [(DELAY_RULE, delay_message(proj["name"], schedule), MANAGER_ROLES)]
        if today.weekday() == 0:
            notes.append((WEEK_RULE, week_message(proj["name"], schedule, today), WEEK_ROLES))
        for rule, note, roles in notes:
            if note is None:
                continue
            for user_id in await _people(conn, organization_id, proj["id"], roles):
                async with conn.begin_nested():
                    claimed = await repo.claim(
                        organization_id=organization_id, rule_key=rule, subject_id=f"{proj['id']}:{user_id}",
                        occurred_on=today, recipient_user_id=user_id, project_id=proj["id"], site_id=None,
                        payload={"message": note, "hold_until_window": True, "hold_days": 1})
                queued += 1 if claimed else 0
    return queued
