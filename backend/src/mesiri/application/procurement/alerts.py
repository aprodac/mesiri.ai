"""PRC-25: the office hears about material requests, and nothing waits unnoticed.

Three messages, queued in ``notifications`` (the WhatsApp sender's own rules then decide each delivery: opt-out,
quiet hours; outside the 24-hour window it waits for the person's next message, ``hold_until_window``, so no Meta
template is needed):

* a new request: to the office (admins and owners; project managers of that project), never to the person who asked;
* a request still waiting for the office after ``WAITING_AFTER``: once a day, to the same people;
* an order past its expected date with something still to come: once a day, to the person who placed it.

Each in the recipient's reply language (none chosen: Manglish, WA-207). Nothing here talks to WhatsApp.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

#: A request still waiting this long is brought up again (default from the plan; open question to Ilan).
WAITING_AFTER = datetime.timedelta(hours=4)
#: A held message older than this is dropped rather than sent stale.
HOLD_DAYS = 2

_WORDS: dict[str, dict[str, str]] = {
    "new": {
        "english": "📦 New material request {ref} from {who} · {site}: {what}{needed}{purpose}. Reply \"order {ref} "
                   "from <shop>\" to order it, or open Requests on the dashboard.",
        "manglish": "📦 Puthiya material request {ref} – {who} · {site}: {what}{needed}{purpose}. Order cheyyaan "
                    "\"{ref} <shop>-il order cheyyu\" ennu reply cheyyuka.",
        "malayalam": "📦 പുതിയ മെറ്റീരിയൽ റിക്വസ്റ്റ് {ref} – {who} · {site}: {what}{needed}{purpose}. ഓർഡർ "
                     "ചെയ്യാൻ \"{ref} <കട>-ൽ ഓർഡർ ചെയ്യൂ\" എന്ന് മറുപടി അയക്കുക.",
    },
    "waiting": {
        "english": "⏰ {ref} has waited {hours} h for the office: {what} for {site} ({who}){needed}. Order it, send it "
                   "from another site, or say no.",
        "manglish": "⏰ {ref} {hours} manikkoor aayi office-nu vendi kaathirikkunnu: {what}, {site} ({who}){needed}. "
                    "Order cheyyuka, vere site-il ninnu ayakkuka, allenkil venda ennu parayuka.",
        "malayalam": "⏰ {ref} {hours} മണിക്കൂറായി ഓഫീസിനായി കാത്തിരിക്കുന്നു: {what}, {site} ({who}){needed}. ഓർഡർ "
                     "ചെയ്യുക, മറ്റൊരു സൈറ്റിൽ നിന്ന് അയക്കുക, അല്ലെങ്കിൽ വേണ്ട എന്ന് പറയുക.",
    },
    "late": {
        "english": "🚚 {ref} from {vendor} is late (expected {date}): {what} still to come at {site}. Call them{phone}, "
                   "or move the date.",
        "manglish": "🚚 {ref} ({vendor}) late aanu ({date}-nu varendathaayirunnu): {what} {site}-il ini varaanundu. "
                    "Avare vilikkuka{phone}, allenkil date maattuka.",
        "malayalam": "🚚 {ref} ({vendor}) വൈകി ({date}-ന് വരേണ്ടതായിരുന്നു): {what} {site}-ൽ ഇനി വരാനുണ്ട്. അവരെ "
                     "വിളിക്കുക{phone}, അല്ലെങ്കിൽ തീയതി മാറ്റുക.",
    },
}
_NEEDED = {"english": ", needed by {d}", "manglish": ", {d}-nu venam", "malayalam": ", {d}-ന് വേണം"}


def language_of(value: str | None) -> str:
    """The reply language a message goes in (none chosen: Manglish; Hindi / Hinglish: English for now)."""
    if value in ("english", "manglish", "malayalam"):
        return value
    return "english" if value in ("hindi", "hinglish") else "manglish"


def _day(value: Any) -> str:
    d = value if isinstance(value, datetime.date) else datetime.date.fromisoformat(str(value))
    return d.strftime("%a %d %b").replace(" 0", " ")


def _num(value: Any) -> str:
    return f"{Decimal(str(value)).normalize():f}"


def words(kind: str, language: str | None, **values: Any) -> str:
    lang = language_of(language)
    needed = values.pop("needed_by", None)
    values["needed"] = _NEEDED[lang].format(d=_day(needed)) if needed else ""
    return _WORDS[kind][lang].format(**values)


async def office_people(conn: AsyncConnection, organization_id: uuid.UUID, project_id: Any, *,
                        besides: Any = None) -> list[dict[str, Any]]:
    """Who decides material requests for this project, with a WhatsApp number: admins and owners of the company,
    project managers of this project (``may_act_on_material_requests``; platform admins are not the company's office)."""
    rows = (await conn.execute(text(
        """
        SELECT u.id, u.reply_language FROM users u
         WHERE u.organization_id = :org AND u.status = 'active' AND u.whatsapp_number IS NOT NULL
           AND upper(u.role) IN ('ADMIN', 'OWNER', 'PROJECT_MANAGER')
           AND (CAST(:besides AS uuid) IS NULL OR u.id <> CAST(:besides AS uuid))
           AND (upper(u.role) IN ('ADMIN', 'OWNER')
                OR EXISTS (SELECT 1 FROM project_members m WHERE m.project_id = :project AND m.user_id = u.id))
        """), {"org": organization_id, "project": project_id, "besides": besides})).all()
    return [{"id": r.id, "language": r.reply_language} for r in rows]


def _what(item: dict[str, Any]) -> str:
    return ", ".join(f"{line['quantity']} {line['unit']} {line['material']}" for line in item["lines"])


async def _claim(conn: AsyncConnection, organization_id: uuid.UUID, *, rule_key: str, subject_id: str,
                 recipient: Any, project_id: Any, site_id: Any, message: str, today: datetime.date) -> bool:
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

    async with conn.begin_nested():
        claimed = await PostgresNotificationRepository(conn).claim(
            organization_id=organization_id, rule_key=rule_key, subject_id=subject_id, occurred_on=today,
            recipient_user_id=uuid.UUID(str(recipient)), project_id=uuid.UUID(str(project_id)),
            site_id=uuid.UUID(str(site_id)) if site_id else None,
            payload={"message": message, "hold_until_window": True, "hold_days": HOLD_DAYS})
    return claimed is not None


async def tell_office_of_new_request(conn: AsyncConnection, organization_id: uuid.UUID, item: dict[str, Any]) -> int:
    """A request was just raised (dashboard or WhatsApp): each office person hears it once, in their language."""
    sent = 0
    today = datetime.date.today()
    for person in await office_people(conn, organization_id, item["project_id"], besides=item["requested_by"]):
        message = words("new", person["language"], ref=item["ref"], who=item["requested_by_name"] or "Someone",
                        site=item["site_name"], what=_what(item), needed_by=item["needed_by"],
                        purpose=f" ({item['purpose']})" if item.get("purpose") else "")
        sent += await _claim(conn, organization_id, rule_key="material_request_new",
                             subject_id=f"{item['id']}:{person['id']}", recipient=person["id"],
                             project_id=item["project_id"], site_id=item["site_id"], message=message, today=today)
    return sent


async def queue_reminders(conn: AsyncConnection, organization_id: uuid.UUID, *, now: datetime.datetime) -> int:
    """The scheduled check: requests waiting too long (to the office) and late orders (to whoever placed them), at
    most once a day each."""
    from mesiri.application.dpr import project_day
    from mesiri.domains.procurement import orders as order_store
    from mesiri.domains.procurement import requests as request_store

    queued = 0
    today = await project_day.company_today(conn, organization_id)
    for req in await request_store.fetch_requests(conn, organization_id, project_ids=None):
        if req["status"] != request_store.WAITING:
            continue
        waited = now - req["created_at"]
        if waited < WAITING_AFTER:
            continue
        item = {**req, "ref": request_store.ref(req["number"]),
                "lines": [{**line, "quantity": _num(line["quantity"])} for line in req["lines"]]}
        for person in await office_people(conn, organization_id, req["project_id"], besides=req["requested_by"]):
            message = words("waiting", person["language"], ref=item["ref"], hours=int(waited.total_seconds() // 3600),
                            what=_what(item), site=req["site_name"], who=req["requested_by_name"] or "someone",
                            needed_by=req["needed_by"])
            queued += await _claim(conn, organization_id, rule_key="material_request_waiting",
                                   subject_id=f"{req['id']}:{person['id']}", recipient=person["id"],
                                   project_id=req["project_id"], site_id=req["site_id"], message=message, today=today)
    for order in await order_store.fetch_orders(conn, organization_id, project_ids=None):
        if order["status"] != "open" or order["expected_date"] is None or order["expected_date"] >= today:
            continue
        coming = [line for line in order["lines"] if Decimal(line["quantity"]) > Decimal(line["received"])]
        if not coming or order["created_by"] is None:
            continue
        language = (await conn.execute(text("SELECT reply_language FROM users WHERE id = :id"),
                                       {"id": order["created_by"]})).scalar()
        what = ", ".join(f"{_num(Decimal(line['quantity']) - Decimal(line['received']))} {line['unit']} "
                         f"{line['material']}" for line in coming)
        message = words("late", language, ref=order_store.ref(order["number"]), vendor=order["vendor_name"],
                        date=_day(order["expected_date"]), what=what, site=order["site_name"],
                        phone=f" ({order['vendor_phone']})" if order.get("vendor_phone") else "")
        queued += await _claim(conn, organization_id, rule_key="purchase_order_late", subject_id=str(order["id"]),
                               recipient=order["created_by"], project_id=order["project_id"],
                               site_id=order["site_id"], message=message, today=today)
    return queued


#: The in-app scheduler ticks every minute; reminders are looked for at most this often.
_EVERY = datetime.timedelta(minutes=15)
_last_run: dict[str, datetime.datetime] = {}


async def queue_all_reminders(conn: AsyncConnection, *, now: datetime.datetime | None = None) -> int:
    """Every working company's reminders (``queue_reminders``), at most every ``_EVERY``. Called by the WhatsApp
    app's scheduler (runtime/automation_runner.py) and the backup cron (scripts/run_notification_checks.py)."""
    from mesiri.domains.organizations.lifecycle import operational_sql

    now = now or datetime.datetime.now(tz=datetime.UTC)
    last = _last_run.get("all")
    if last is not None and now - last < _EVERY:
        return 0
    _last_run["all"] = now
    queued = 0
    orgs = (await conn.execute(text(f"SELECT id FROM organizations WHERE {operational_sql('')}"))).all()  # noqa: S608
    for org in orgs:
        async with conn.begin_nested():
            queued += await queue_reminders(conn, org.id, now=now)
    return queued
