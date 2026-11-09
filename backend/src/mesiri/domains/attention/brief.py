"""GM-08 with TSK-05: one morning message per person on WhatsApp, at 8 am company time.

One message, never two: the Tasks module's morning card (TSK-05: my tasks due today, overdue, and how many more this
week) and the GM brief (what to act on now, GM-04; what is waiting for my decision, NXT-08). Each part is read as
the person (their projects, their role, the module switches), so nobody is told what they could not open. Nothing is
sent when all of it is empty, or to someone who turned it off (``users.morning_brief``, migration 0538). It goes
through the notification queue and waits for their 24-hour window (no template).

Rules that also send a note on their own (the order-by note MP-03, the delay note ST-06, the evening cost card CC-11)
keep doing so; the brief only lists the act-now alerts, it does not repeat their detail.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)

RULE = "morning_brief"
#: Not before this, company time.
SEND_FROM = datetime.time(8, 0)
#: Act-now alerts and waiting decisions go to the people who run projects; tasks go to everyone.
RUNS_PROJECTS = ("OWNER", "ADMIN", "SUPER_ADMIN", "PROJECT_MANAGER")
_LIVE = ("open", "doing", "blocked")

_W = {
    "hello": {"english": "☀️ *Good morning, {name}* · {day}", "manglish": "☀️ *Suprabhatham, {name}* · {day}",
              "malayalam": "☀️ *സുപ്രഭാതം, {name}* · {day}"},
    "act": {"english": "🔴 *Act now ({n})*", "manglish": "🔴 *Ippo nokkendath ({n})*", "malayalam": "🔴 *ഇപ്പോൾ നോക്കേണ്ടത് ({n})*"},
    "waiting": {"english": "📥 *Waiting for you ({n})*", "manglish": "📥 *Ningalkku vendi kaathirikkunnu ({n})*",
                "malayalam": "📥 *നിങ്ങൾക്കായി കാത്തിരിക്കുന്നത് ({n})*"},
    "tasks": {"english": "✅ *Your tasks*: {today} due today, {overdue} overdue, {week} more this week",
              "manglish": "✅ *Ningalude tasks*: inn {today}, {overdue} vaikiyath, ee aazhcha {week} koode",
              "malayalam": "✅ *നിങ്ങളുടെ ടാസ്കുകൾ*: ഇന്ന് {today}, വൈകിയത് {overdue}, ഈ ആഴ്ച {week} കൂടി"},
    "more": {"english": "and {n} more", "manglish": "{n} koode", "malayalam": "{n} കൂടി"},
    "off": {"english": "Say \"stop the morning message\" to turn this off.",
            "manglish": "Ee message venda enkil \"morning message venda\" ennu parayuka.",
            "malayalam": "ഈ സന്ദേശം വേണ്ടെങ്കിൽ \"morning message venda\" എന്ന് പറയുക."},
}


def _lang(language: str | None) -> str:
    if language in ("english", "manglish", "malayalam"):
        return language
    return "english" if language in ("hindi", "hinglish") else "manglish"


def _d(v: Any) -> datetime.date | None:
    if v is None or isinstance(v, datetime.date):
        return v
    return datetime.date.fromisoformat(str(v)[:10])


def compose(name: str, language: str | None, today: datetime.date, *, alerts: list[dict], waiting: dict | None,
            tasks: list[dict]) -> str | None:
    """The message, or None when there is nothing to say. ``alerts``: act-now attention alerts (bad), worst first;
    ``waiting``: the NXT-08 answer (None: not for this person); ``tasks``: the person's live tasks."""
    lang = _lang(language)
    week_end = today + datetime.timedelta(days=6 - today.weekday())
    live = [t for t in tasks if t.get("status") in _LIVE and _d(t.get("due_date"))]
    overdue = sorted((t for t in live if _d(t["due_date"]) < today), key=lambda t: _d(t["due_date"]))
    due_today = [t for t in live if _d(t["due_date"]) == today]
    later = [t for t in live if today < _d(t["due_date"]) <= week_end]
    items = (waiting or {}).get("items") or []
    if not (alerts or items or overdue or due_today or later):
        return None

    def more(n: int) -> list[str]:
        return [f"   {_W['more'][lang].format(n=n)}"] if n > 0 else []

    lines = [_W["hello"][lang].format(name=(name or "").split(" ")[0] or "there", day=f"{today:%a} {today.day} {today:%b}")]
    if alerts:
        lines += ["", _W["act"][lang].format(n=len(alerts))]
        lines += [f"• {a['title']}" + (f" ({a['project_name']})" if a.get("project_name") else "") for a in alerts[:3]]
        lines += more(len(alerts) - 3)
    if items:
        lines += ["", _W["waiting"][lang].format(n=len(items))]
        lines += [f"• {'⚠️ ' if i.get('urgent') else ''}{i['title']}" + (f" ({i['project_name']})" if i.get("project_name") else "")
                  for i in items[:3]]
        lines += more(len(items) - 3)
    if overdue or due_today or later:
        lines += ["", _W["tasks"][lang].format(today=len(due_today), overdue=len(overdue), week=len(later))]
        for t in (overdue + due_today)[:3]:
            due = _d(t["due_date"])
            lines.append(f"• {t.get('ref') or ''} {t['title']} ({due:%a} {due.day} {due:%b})".replace("•  ", "• "))
    lines += ["", _W["off"][lang]]
    return "\n".join(lines)


async def queue_morning_briefs(conn: AsyncConnection, org: uuid.UUID, today: datetime.date,
                               now_local: datetime.datetime) -> int:
    """Once a day per person, from 8 am company time: compose and queue each person's brief."""
    if now_local.time() < SEND_FROM:
        return 0
    from mesiri.authorization.service import AuthorizationService
    from mesiri.domains.approvals import inbox
    from mesiri.domains.attention import feed, rules
    from mesiri.domains.organizations import settings as org_settings
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )
    from mesiri.infrastructure.postgres.repositories.organization_settings import (
        PostgresOrganizationSettingsRepository,
    )

    stored = await PostgresOrganizationSettingsRepository(conn).get(org, org_settings.ENABLED_MODULES)
    enabled = {m for m in org_settings.MODULES if org_settings.module_enabled(m, stored)}
    people = (await conn.execute(text(
        "SELECT id, full_name, role, reply_language FROM users WHERE organization_id = :org AND status = 'active' "
        "AND whatsapp_number IS NOT NULL AND morning_brief"), {"org": org})).mappings().all()
    repo = PostgresNotificationRepository(conn)
    queued = 0
    for p in people:
        role = str(p["role"] or "").upper()
        try:
            async with conn.begin_nested():
                sent = (await conn.execute(text(
                    "SELECT 1 FROM notifications WHERE organization_id = :org AND rule_key = :r AND subject_id = :s "
                    "AND occurred_on = :d"), {"org": org, "r": RULE, "s": str(p["id"]), "d": today})).first()
                if sent:  # queued on an earlier pass today: nothing to work out again
                    continue
                ctx = await AuthorizationService(conn).resolve_from_jwt(p["id"], org, role)
                alerts: list[dict] = []
                if role in RUNS_PROJECTS:
                    found = await feed.collect(conn, ctx, enabled=enabled)
                    shown = rules.arrange(found, await feed.snoozed(conn, ctx, today))["items"]
                    alerts = [a for a in shown if a["severity"] == "bad"]
                waiting = await inbox.waiting(conn, ctx, lambda m: m in enabled)
                tasks: list[dict] = []
                if "tasks" in enabled:
                    from mesiri.domains.tasks import store as task_store

                    tasks = await task_store.listing(conn, org, project_ids=None, project_id=None, site_id=None,
                                                     statuses=_LIVE, assignee_user_id=p["id"], assignee_vendor_id=None,
                                                     q=None, limit=100)
                message = compose(p["full_name"], p["reply_language"], today, alerts=alerts, waiting=waiting, tasks=tasks)
                if message is None:
                    continue
                claimed = await repo.claim(organization_id=org, rule_key=RULE, subject_id=str(p["id"]), occurred_on=today,
                                           recipient_user_id=p["id"], payload={"message": message, "hold_until_window": True,
                                                                               "hold_days": 1})
                queued += 1 if claimed else 0
        except Exception:  # noqa: BLE001 -- one person's brief must not stop the others'
            logger.exception("morning_brief.failed user=%s", p["id"])
    return queued
