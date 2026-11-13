"""The owner's board on Live (WEB-83): six questions an owner carries all day, each answered in a sentence
with the number inside it (docs/plans/live-value-plan.md, section 3).

One table, ``QUESTIONS``: a question is a list of parts, and a part is one module's own read (``READS``) and
the sentence said from it (``say``). A new answer is one part in the table.

Nothing is computed here. Every read calls the route function the module's own page calls (as
``approvals/inbox.py`` does), so:

- the number on the board is the number on the page it opens;
- the module's own scope and role rules apply: a read that answers 403 or 404 for this person is left out of
  their board (money answers go only to the roles that see spending, plan decision 4);
- a module that is switched off is not read, and is named in ``off`` so the screen can say what it would add
  (plan decision 3).

Read-only. A part with nothing to say says nothing: no sentence is made up.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.reports.period.headline import inr

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Ctx:
    conn: AsyncConnection
    auth: AuthorizationContext
    request: Request
    today: datetime.date


# --- the reads: each is the module's own route function ---------------------------------------------------------------


async def _costs(c: Ctx) -> Any:
    from mesiri.domains.finance.router import project_costs

    return await project_costs(date_from=c.today - datetime.timedelta(days=6), date_to=c.today, project_id=None,
                               site_id=None, auth_context=c.auth, conn=c.conn)


async def _budget(c: Ctx) -> Any:
    from mesiri.domains.costing.router import portfolio

    return await portfolio(auth=c.auth, conn=c.conn)


async def _rates(c: Ctx) -> Any:
    from mesiri.domains.procurement.rates_router import list_rates

    return await list_rates(date_from=None, date_to=None, project_id=None, site_id=None, category_id=None,
                            vendor_id=None, auth_context=c.auth, conn=c.conn)


async def _stock(c: Ctx) -> Any:
    from mesiri.domains.materials.router import stock_summary

    return await stock_summary(date_from=None, date_to=None, project_id=None, site_id=None, material_id=None,
                               category_id=None, auth_context=c.auth, conn=c.conn)


async def _below(c: Ctx) -> Any:
    from mesiri.domains.materials.stock_levels_router import below

    return await below(project_id=None, site_id=None, include_covered=True, auth_context=c.auth, conn=c.conn)


async def _days(c: Ctx) -> Any:
    from mesiri.domains.dpr.router import list_site_days

    return await list_site_days(report_date=c.today, project_id=None, auth_context=c.auth, conn=c.conn)


async def _schedule(c: Ctx) -> Any:
    from mesiri.domains.schedule.router import projects_lifecycle

    return await projects_lifecycle(auth=c.auth, conn=c.conn)


async def _wages(c: Ctx) -> Any:
    from mesiri.domains.workforce.pay_router import pay_summary

    return await pay_summary(project_id=None, auth=c.auth, conn=c.conn)


async def _suppliers(c: Ctx) -> Any:
    from mesiri.domains.vendors.router import payables

    return await payables(project_id=None, include_settled=False, auth_context=c.auth, conn=c.conn)


async def _clients(c: Ctx) -> Any:
    from mesiri.domains.billing.router import receivables

    return await receivables(project_id=None, auth=c.auth, conn=c.conn)


async def _to_bill(c: Ctx) -> Any:
    from mesiri.domains.billing.router import work_to_bill

    return await work_to_bill(project_id=None, auth=c.auth, conn=c.conn)


async def _waiting(c: Ctx) -> Any:
    from mesiri.domains.approvals.router import waiting

    return await waiting(request=c.request, kind=None, limit=100, auth=c.auth, conn=c.conn)


#: Read name -> the read. One name is read once for the whole board, however many parts use it.
READS: dict[str, Callable[[Ctx], Awaitable[Any]]] = {
    "costs": _costs, "budget": _budget, "rates": _rates, "stock": _stock, "below": _below, "days": _days,
    "schedule": _schedule, "wages": _wages, "suppliers": _suppliers, "clients": _clients, "to_bill": _to_bill,
    "waiting": _waiting,
}


# --- the sentences: pure, from what the read returned -----------------------------------------------------------------


def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except ArithmeticError:
        return Decimal(0)


def _n(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


def _get(row: Any, key: str) -> Any:
    return row.get(key) if isinstance(row, dict) else getattr(row, key, None)


def say_costs(data: dict) -> str | None:
    total = _d(data.get("total"))
    if total <= 0:
        return None
    parts = [(name, _d((data.get(key) or {}).get("amount")))
             for key, name in (("labour", "labour"), ("materials", "materials"), ("expenses", "expenses"),
                               ("machines", "machines"))]
    said = ", ".join(f"{name} {inr(amount)}" for name, amount in sorted(parts, key=lambda p: -p[1]) if amount > 0)
    return f"{inr(total)} spent in the last 7 days" + (f": {said}." if said else ".")


def say_budget(data: dict) -> str | None:
    rows = [p for p in data.get("projects") or [] if p.get("percent_spent") is not None]
    if not rows:
        return None
    over = [p for p in rows if p.get("forecast_difference") is not None and _d(p["forecast_difference"]) < 0]
    if over:
        worst = min(over, key=lambda p: _d(p["forecast_difference"]))
        return f"{worst['name']} is heading {inr(-_d(worst['forecast_difference']))} over its budget."
    top = max(rows, key=lambda p: _d(p["percent_spent"]))
    return f"{top['name']} has spent {_d(top['percent_spent']).normalize():f}% of its budget."


def say_beyond_stock(data: list) -> str | None:
    beyond = [r for r in data if _d(_get(r, "closing")) < 0]
    if not beyond:
        return None
    first = beyond[0]
    over = -_d(_get(first, "closing"))
    more = f" and {_n(len(beyond) - 1, 'more item')}" if len(beyond) > 1 else ""
    return (f"{over.normalize():f} {_get(first, 'unit')} of {_get(first, 'material_name')} used beyond the stock "
            f"on the books{more}.")


def say_rates(data: dict) -> str | None:
    summary = data.get("summary") or {}
    above, rising = _d(summary.get("above_best")), int(summary.get("rising") or 0)
    if above <= 0 and not rising:
        return None
    said = []
    if above > 0:
        said.append(f"{inr(above)} paid above the best rate in the last 90 days")
    if rising:
        said.append(f"{_n(rising, 'item')} cost{'s' if rising == 1 else ''} more than last time")
    return "; ".join(said) + "."


def say_schedule(data: list) -> str | None:
    rows = [p for p in data if p.get("scheduled")]
    if not rows:
        return None
    late = [p for p in rows if int(p.get("slip_days") or 0) > 0]
    if not late:
        return f"{_n(len(rows), 'project')} on schedule."
    worst = max(late, key=lambda p: int(p["slip_days"]))
    done = f"{worst['progress']}% done, " if worst.get("progress") is not None else ""
    more = f" {_n(len(late) - 1, 'more project')} behind." if len(late) > 1 else ""
    return f"{worst['name']}: {done}{_n(int(worst['slip_days']), 'day')} behind the schedule.{more}"


def say_work_today(data: dict) -> str | None:
    items = data.get("items") or []
    work = sum(int(s.get("work_items") or 0) + int(s.get("progress_updates") or 0) for s in items)
    sites = sum(1 for s in items if int(s.get("work_items") or 0) + int(s.get("progress_updates") or 0) > 0)
    workers = sum(int(s.get("workers") or 0) for s in items)
    if not work and not workers:
        return None
    said = []
    if work:
        said.append(f"{_n(work, 'work update')} from {_n(sites, 'site')} today")
    if workers:
        said.append(f"{_n(workers, 'worker')} on site")
    return ", ".join(said) + "."


def say_wages(data: dict) -> str | None:
    due, drafts = _d(data.get("due")), int(data.get("drafts") or 0)
    advances = _d(data.get("advances_outstanding"))
    said = []
    if due > 0:
        said.append(f"Wages due {inr(due)} to {_n(int(data.get('due_rows') or 0), 'person', 'people')}")
    if drafts:
        said.append(f"{_n(drafts, 'wage sheet')} waiting to be approved")
    if advances > 0:
        said.append(f"{inr(advances)} of advances still out")
    return "; ".join(said) + "." if said else None


def say_suppliers(data: dict) -> str | None:
    totals = data.get("totals") or {}
    payable, overdue, unbilled = _d(totals.get("payable")), _d(totals.get("overdue")), _d(totals.get("unbilled"))
    if payable <= 0 and unbilled <= 0:
        return None
    said = f"Suppliers are owed {inr(payable)}"
    if overdue > 0:
        said += f", {inr(overdue)} of it overdue"
    if unbilled > 0:
        said += f"; {inr(unbilled)} delivered and not billed yet"
    return said + "."


def say_clients(data: dict) -> str | None:
    owed = _d(data.get("outstanding"))
    return f"Clients owe you {inr(owed)}." if owed > 0 else None


def say_to_bill(data: dict) -> str | None:
    """WEB-91: measured work on no client bill yet, at the client rate (before retention and GST)."""
    amount = _d(data.get("amount"))
    if amount <= 0:
        return None
    projects = data.get("projects") or []
    where = f" on {projects[0]['project']}" if len(projects) == 1 else f" across {_n(len(projects), 'project')}"
    return f"{inr(amount)} of measured work{where} can be billed to the client now."


def say_below(data: dict) -> str | None:
    rows = data.get("items") or []
    if not rows:
        return None
    first = rows[0]
    open_ = int(data.get("not_covered") or 0)
    what = f"{first['material']} at {first['site_name']}: {first['closing']} {first['unit']}, minimum {first['min_qty']}"
    return (f"{_n(len(rows), 'item')} below {'its' if len(rows) == 1 else 'their'} minimum, {open_} not ordered yet "
            f"({what}).")


def say_days_left(data: list, days: dict | None = None) -> str | None:
    """``days`` (WEB-89): today's site days, only for the site's name; without them the site is not named."""
    short = [r for r in data if _get(r, "days_left") is not None and _d(_get(r, "closing")) > 0]
    if not short:
        return None
    first = min(short, key=lambda r: int(_get(r, "days_left")))
    left = int(_get(first, "days_left"))
    if left > 7:
        return None
    names = {str(s.get("site_id")): s.get("site_name") for s in (days or {}).get("items") or []}
    site = names.get(str(_get(first, "site_id")))
    where = f" at {site}" if site else ""
    return f"{_get(first, 'material_name')}{where} lasts {_n(left, 'more day')} at this week's use."


def say_issues(data: dict) -> str | None:
    items = data.get("items") or []
    n = sum(int(s.get("open_issues") or 0) for s in items)
    if not n:
        return None
    sites = sum(1 for s in items if int(s.get("open_issues") or 0) > 0)
    return f"{_n(n, 'issue')} open on {_n(sites, 'site')}."


def say_waiting(data: dict) -> str | None:
    n = int(data.get("total") or len(data.get("items") or []))
    return f"{_n(n, 'thing')} waiting for your yes." if n else None


def say_reports(data: dict) -> str | None:
    items, projects = data.get("items") or [], data.get("projects") or []
    if not items:
        return None
    heard = [s for s in items if s.get("last_update_at")]
    lines = sum(int(s.get(k) or 0) for s in items
                for k in ("work_items", "materials", "issues_today", "progress_updates")) + sum(
        1 for s in items if int(s.get("workers") or 0) > 0)
    photos = sum(int(s.get("photos") or 0) for s in items)
    sent = sum(1 for p in projects if p.get("sent"))
    said = f"Today's reports: {_n(lines, 'line')}, {_n(photos, 'photo')}, from {len(heard)} of {_n(len(items), 'site')}."
    if sent:
        said += f" {_n(sent, 'report')} sent."
    # WEB-89: when the next one goes out by itself (a project that sends its report, not sent yet today).
    due = sorted(p["dpr_send_deadline"] for p in projects
                 if p.get("auto_generate_dpr") and not p.get("sent") and p.get("dpr_send_deadline") is not None)
    if due:
        said += f" The next goes out at {due[0]:%-I:%M %p}.".replace("AM", "am").replace("PM", "pm")
    return said


# --- the table ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Part:
    read: str
    #: The module that must be switched on (organizations/settings.py MODULES); its router's own gate.
    module: str
    say: Callable[..., str | None]
    #: The page that shows this number.
    opens: str
    #: A second read the sentence may use for a name (never for a number); passed as the second argument, or
    #: None when this person may not see it.
    also: str | None = None


@dataclass(frozen=True)
class Question:
    key: str
    text: str
    #: Said when every part could be read and none had anything to say.
    quiet: str
    parts: tuple[Part, ...]


QUESTIONS: tuple[Question, ...] = (
    Question("money", "Where is my money going?", "Nothing spent in the last 7 days.", (
        Part("costs", "finance", say_costs, "/finance"),
        Part("budget", "cost", say_budget, "/cost/budget"),
    )),
    Question("leaks", "Is anything leaking?", "Nothing to check right now.", (
        Part("stock", "materials", say_beyond_stock, "/materials"),
        Part("rates", "materials", say_rates, "/procurement/rates"),
    )),
    Question("work", "Is the work moving?", "No work reported yet today.", (
        Part("schedule", "dpr", say_schedule, "/planning/schedule"),
        Part("days", "dpr", say_work_today, "/today"),
    )),
    Question("owed", "What do I owe, and who owes me?", "Nothing owed either way.", (
        Part("wages", "labour", say_wages, "/labour/wages"),
        Part("suppliers", "finance", say_suppliers, "/finance/vendors"),
        Part("to_bill", "dpr", say_to_bill, "/billing/ra-bills"),
        Part("clients", "dpr", say_clients, "/accounts/receivables"),
    )),
    Question("stops", "What will stop work tomorrow?", "Nothing in the way.", (
        Part("below", "materials", say_below, "/materials"),
        Part("stock", "materials", say_days_left, "/materials", also="days"),
        Part("days", "dpr", say_issues, "/issues"),
        Part("waiting", "dpr", say_waiting, "/today"),
    )),
    Question("proof", "Can I prove it?", "No updates from site yet today.", (
        Part("days", "dpr", say_reports, "/reports"),
    )),
)

#: Which question a kind of message answers (``live_feed.KIND_LABELS``): where its card lands on the board, and
#: the messages an answer opens into. A kind not here lands nowhere.
KIND_QUESTIONS: dict[str, tuple[str, ...]] = {
    "attendance": ("owed", "work", "proof"),
    "work": ("work", "proof"),
    "correction": ("work", "proof"),
    "delivery": ("money", "stops", "proof"),
    "usage": ("stops", "leaks", "proof"),
    "transfer": ("stops", "proof"),
    "expense": ("money", "owed"),
    "issue": ("stops", "proof"),
    "issue_closed": ("stops", "proof"),
    "machine": ("work", "owed"),
    "report": ("proof",),
}


async def build(conn: AsyncConnection, auth: AuthorizationContext, request: Request, today: datetime.date,
                enabled: Callable[[str], bool]) -> dict[str, Any]:
    """The six answers for this person. Each: ``lines`` (sentence, the page it opens, the read it came from),
    ``quiet`` (the sentence when all was read and nothing is to be said), ``off`` (modules switched off that would
    add to it) and ``hidden`` (a part this person's role or scope may not see)."""
    ctx = Ctx(conn=conn, auth=auth, request=request, today=today)
    got: dict[str, tuple[str, Any]] = {}

    async def read(name: str) -> tuple[str, Any]:
        if name not in got:
            try:
                # A savepoint: a read that fails must not take the reads after it down with it.
                async with conn.begin_nested():
                    got[name] = ("ok", await READS[name](ctx))
            except HTTPException as exc:
                got[name] = ("hidden" if exc.status_code in (403, 404) else "failed", None)
            except Exception:  # noqa: BLE001 -- the board shows what it can; the failure is logged, never a number
                logger.exception("live board: the %s read failed", name)
                got[name] = ("failed", None)
        return got[name]

    questions = []
    for q in QUESTIONS:
        lines: list[dict[str, str]] = []
        off: list[str] = []
        hidden = failed = False
        for part in q.parts:
            if not enabled(part.module):
                if part.module not in off:
                    off.append(part.module)
                continue
            state, data = await read(part.read)
            if state == "hidden":
                hidden = True
                continue
            if state == "failed":
                failed = True
                continue
            try:
                if part.also is not None:
                    also_state, also_data = await read(part.also)
                    text = part.say(data, also_data if also_state == "ok" else None)
                else:
                    text = part.say(data)
            except Exception:  # noqa: BLE001 -- as above
                logger.exception("live board: the %s sentence failed", part.read)
                failed = True
                continue
            if text:
                lines.append({"text": text, "opens": part.opens, "read": part.read})
        questions.append({
            "key": q.key, "question": q.text, "lines": lines,
            # Quiet only when everything was read: "nothing to check" is never said over a part that was not seen.
            "quiet": q.quiet if not lines and not off and not hidden and not failed else None,
            "off": off, "hidden": hidden,
            "opens": lines[0]["opens"] if lines else q.parts[0].opens,
        })
    return {"date": today.isoformat(), "questions": questions, "kinds": {k: list(v) for k, v in KIND_QUESTIONS.items()}}
