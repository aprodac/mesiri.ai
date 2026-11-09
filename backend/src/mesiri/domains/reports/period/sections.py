"""The sections of a period report (PRC-19), each read from the module that owns the data.

No section has its own copy of a module's rule. Each calls the module's own function, and where the module has an
access rule of its own, its route function as the caller (the approvals inbox's way), so a section shows exactly
what that module's page would show this person:

- ``work``: work done in the period on BOQ lines (``progress.boq_router.counted_work``: the BOQ's one rule), and
  progress against plan (``schedule.store.load``: the Gantt's own read).
- ``schedule``: what is late or behind, the forecast finish (the same read).
- ``labour``: man-days by trade, day and site (``workforce.pay_store.attendance_lines`` and ``pay.build_rows``:
  the wage sheet's own counting); wages only for the roles that see spending.
- ``materials``: received, used, running low (``materials.router.stock_summary``, PRC-17, as the caller).
- ``money``: spent by cost centre (``costing.centres.cost_centres``), labour green / red
  (``costing.router.variance_for``), billed, received and owed (``billing``). Only for the roles that see spending;
  the client bills only for the roles that see them (``may_manage_money``).
- ``issues``: raised, closed and still open (``progress.router.list_issues``, as the caller).
- ``photos``: from confirmed site days only (``client_view.view.approved_photos``, D-R6).
- ``completeness``: each day, whether site reports were confirmed and attendance recorded
  (``dpr.router.list_daily_reports``, as the caller).

Every section returns ``{"key", "title", "status", "summary", ...}``; status is good / warn / bad / none (none: no
data or no plan, never shown as good).
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.reports.period.periods import Period, clip_to_today, trend

ZERO = Decimal(0)
PHOTO_COUNT = 6
TREND_PERIODS = 8
ISSUE_OPEN = ("OPEN", "ACKNOWLEDGED")
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
OVERDUE_DAYS = 30


@dataclass
class Ctx:
    conn: AsyncConnection
    auth: AuthorizationContext
    project: dict[str, Any]
    site_id: uuid.UUID | None
    period: Period
    prev: Period
    today: datetime.date
    #: The roles that see the company's spending (``may_view_expenses``).
    money: bool
    #: The roles that see client bills (``may_manage_money``).
    bills: bool
    enabled: Callable[[str], bool]
    storage: Any = None
    sites: dict[str, str] = field(default_factory=dict)
    cache: dict[str, Any] = field(default_factory=dict)

    @property
    def org(self) -> uuid.UUID:
        return self.auth.organization_id

    @property
    def project_id(self) -> uuid.UUID:
        return self.project["id"]

    @property
    def last_day(self) -> datetime.date:
        return clip_to_today(self.period, self.today)

    def in_site(self, site_id: Any) -> bool:
        return self.site_id is None or (site_id is not None and str(site_id) == str(self.site_id))


# -- small helpers ----------------------------------------------------------------------------------------------------

def money(v: Any) -> str | None:
    return None if v is None else str(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def qty(v: Any) -> str:
    d = Decimal(str(v)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    text = format(d, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def pct(v: Decimal | None) -> str | None:
    return None if v is None else str(Decimal(v).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _date(v: Any) -> datetime.date | None:
    if v is None:
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    return datetime.date.fromisoformat(str(v)[:10])


def _in(period: Period, day: datetime.date | None) -> bool:
    return day is not None and period.start <= day <= period.end


def change(now: Decimal | None, before: Decimal | None) -> str | None:
    """The change from the last period in percent; None when there is nothing to compare with."""
    if now is None or before is None or before == 0:
        return None
    return pct((now - before) / before * 100)


# -- shared reads (once per report) ------------------------------------------------------------------------------------

async def _boq(ctx: Ctx) -> dict[str, Any]:
    """The schedule (Gantt read), the BOQ's current lines, and every quantity counted on them."""
    if "boq" not in ctx.cache:
        from mesiri.domains.progress.boq_router import counted_work
        from mesiri.domains.schedule import store
        from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

        repo = PostgresBoqRepository(ctx.conn)
        lines = await repo.list_lines(ctx.org, ctx.project_id)
        ctx.cache["boq"] = {
            "schedule": await store.load(ctx.conn, ctx.org, ctx.project_id, ctx.today),
            "lines": lines,
            "work": await counted_work(repo, ctx.org, ctx.project_id, lines),
        }
    return ctx.cache["boq"]


async def _attendance(ctx: Ctx, start: datetime.date, end: datetime.date) -> list[dict[str, Any]]:
    from mesiri.domains.workforce import pay_store

    key = f"att:{start}:{end}"
    if key not in ctx.cache:
        ctx.cache[key] = await pay_store.attendance_lines(ctx.conn, ctx.org, ctx.project_id, ctx.site_id, start, end)
    return ctx.cache[key]


def _labour_totals(lines: list[dict[str, Any]]) -> dict[str, Decimal]:
    """Man-days and wages of attendance lines, by the wage sheet's own rule (``pay.build_rows``)."""
    from mesiri.domains.workforce import pay

    rows = pay.build_rows(lines, {}, None).values()
    return {"man_days": sum((r["man_days"] for r in rows), ZERO),
            "wages": sum((r["gross"] + r["overtime_amount"] for r in rows), ZERO),
            "unpriced_man_days": sum((r["unpriced_man_days"] for r in rows), ZERO)}


# -- work -------------------------------------------------------------------------------------------------------------

def _line_weight(line: dict[str, Any]) -> Decimal | None:
    planned, rate = line.get("planned_quantity"), line.get("client_rate")
    if planned is None or rate is None:
        return None
    value = Decimal(str(planned)) * Decimal(str(rate))
    return value if value > 0 else None


def work_numbers(activities: list[dict[str, Any]], lines: list[dict[str, Any]], work: list[dict[str, Any]],
                 period: Period, today: datetime.date, in_site: Callable[[Any], bool]) -> dict[str, Any]:
    """The share of the whole job done in the period and planned for it, and progress to date against the plan.

    Pure. Lines are weighted by contract value when every line has one, else equally: ``schedule.logic
    .line_progress``'s own rule, so the percentages agree with the Gantt. Planned for the period: each scheduled
    activity's weight times the share of its planned days that fall in the period."""
    from mesiri.domains.schedule import logic

    acts = [a for a in activities if in_site(a.get("site_id")) or a.get("site_id") is None]
    line_ids = {str(ln["id"]) for a in acts for ln in a.get("lines") or []}
    rows = [ln for ln in lines if str(ln["id"]) in line_ids and Decimal(str(ln.get("planned_quantity") or 0)) > 0]
    values = {str(ln["id"]): _line_weight(ln) for ln in rows}
    by_value = bool(rows) and all(v is not None for v in values.values())
    weight = {k: (v if by_value else Decimal(1)) for k, v in values.items()}
    total = sum(weight.values(), ZERO)
    planned = {str(ln["id"]): Decimal(str(ln["planned_quantity"])) for ln in rows}

    done: dict[str, Decimal] = defaultdict(Decimal)
    other_unit = 0
    for w in work:
        lid = str(w["line_id"])
        if lid not in weight or not _in(period, _date(w["work_date"])) or not in_site(w.get("site_id")):
            continue
        if w["quantity"] is None:
            other_unit += 1
        else:
            done[lid] += Decimal(str(w["quantity"]))

    def share(lid: str, q: Decimal) -> Decimal:
        return weight[lid] * min(q / planned[lid], Decimal(1))

    done_pct = sum((share(k, q) for k, q in done.items()), ZERO) / total * 100 if total else None

    plan_pct = expected_pct = None
    scheduled = [a for a in acts if a.get("start") and a.get("end")]
    if scheduled and total:
        before = period.start - datetime.timedelta(days=1)
        plan_sum = exp_sum = ZERO
        for a in scheduled:
            w_a = sum((weight.get(str(ln["id"]), ZERO) for ln in a.get("lines") or []), ZERO)
            if not w_a:
                continue
            shape = {"start": _date(a["start"]), "end": _date(a["end"]), "milestone": a.get("milestone")}
            plan_sum += w_a * (logic.expected_progress(shape, period.end) - logic.expected_progress(shape, before))
            exp_sum += w_a * logic.expected_progress(shape, today)
        plan_pct, expected_pct = plan_sum / total * 100, exp_sum / total * 100
    return {"done_pct": done_pct, "plan_pct": plan_pct, "expected_pct": expected_pct, "done_by_line": dict(done),
            "other_unit": other_unit, "has_plan": bool(scheduled)}


def work_status(done_pct: Decimal | None, plan_pct: Decimal | None) -> str:
    if done_pct is None or plan_pct is None:
        return "none"
    if plan_pct <= 0:
        return "good"
    ratio = done_pct / plan_pct
    return "good" if ratio >= Decimal("0.9") else "warn" if ratio >= Decimal("0.7") else "bad"


async def work(ctx: Ctx) -> dict[str, Any]:
    b = await _boq(ctx)
    sched, lines = b["schedule"], b["lines"]
    n = work_numbers(sched["activities"], lines, b["work"], ctx.period, ctx.today, ctx.in_site)
    line_by_id = {str(ln["id"]): ln for ln in lines}
    rows = []
    for a in sched["activities"]:
        if a.get("site_id") is not None and not ctx.in_site(a["site_id"]):
            continue
        did = [(line_by_id[str(ln["id"])], n["done_by_line"][str(ln["id"])]) for ln in a.get("lines") or []
               if str(ln["id"]) in n["done_by_line"]]
        overlaps = bool(a.get("start") and a.get("end")) and _date(a["start"]) <= ctx.period.end \
            and _date(a["end"]) >= ctx.period.start
        if not did and not (overlaps and not a.get("done")):
            continue
        rows.append({
            "activity_id": str(a["id"]), "activity": a["name"], "site": a.get("site_name"),
            "progress": a.get("progress"), "expected": a.get("expected"), "state": a.get("state"),
            "days_late": a.get("days_late") or 0, "slip_days": a.get("slip_days") or 0,
            "critical": bool(a.get("critical")),
            "done_in_period": [{"work": ln["work_type"], "quantity": qty(q), "unit": ln["unit"]} for ln, q in did],
        })
    order = {"late": 0, "behind": 1, "on_track": 2, "not_started": 3, "done": 4, "unscheduled": 5}
    rows.sort(key=lambda r: (not r["done_in_period"], order.get(r["state"] or "", 9), r["activity"]))
    status = work_status(n["done_pct"], n["plan_pct"])
    progress = sched["summary"].get("progress")
    return {
        "key": "work", "title": "Work", "status": status,
        "done_pct": pct(n["done_pct"]), "plan_pct": pct(n["plan_pct"]),
        "progress_to_date": progress, "expected_to_date": pct(n["expected_pct"]),
        "has_plan": n["has_plan"], "work_in_other_unit": n["other_unit"],
        "lines_worked": len(n["done_by_line"]),
        "rows": rows, "link": f"/projects/{ctx.project_id}/boq",
    }


# -- schedule ---------------------------------------------------------------------------------------------------------

async def schedule(ctx: Ctx) -> dict[str, Any]:
    sched = (await _boq(ctx))["schedule"]
    s = sched["summary"]
    late = [a for a in sched["activities"] if a.get("state") in ("late", "behind")
            and (a.get("site_id") is None or ctx.in_site(a["site_id"]))]
    late.sort(key=lambda a: (not a.get("critical"), -((a.get("days_late") or 0) + (a.get("slip_days") or 0))))
    slip = int(s.get("slip_days") or 0)
    status = "none" if not s.get("scheduled") else "good" if slip == 0 else "warn" if slip <= 7 else "bad"
    return {
        "key": "schedule", "title": "Schedule", "status": status,
        "forecast_finish": _iso(s.get("forecast_finish")),
        "planned_finish": _iso(s.get("contract_finish") or s.get("planned_finish")),
        "slip_days": slip, "counts": s.get("counts") or {}, "scheduled": s.get("scheduled") or 0,
        "rows": [{"activity_id": str(a["id"]), "activity": a["name"], "site": a.get("site_name"), "state": a["state"],
                  "days_late": a.get("days_late") or 0, "slip_days": a.get("slip_days") or 0,
                  "forecast_end": _iso(a.get("forecast_end")), "end": _iso(a.get("end")),
                  "critical": bool(a.get("critical")), "progress": a.get("progress"), "expected": a.get("expected"),
                  "assigned_to": a.get("assigned_to"), "open_issues": a.get("open_issues") or 0} for a in late],
        "link": f"/planning/schedule?project={ctx.project_id}",
    }


def _iso(v: Any) -> str | None:
    return v.isoformat() if isinstance(v, datetime.date) else (str(v) if v else None)


# -- labour -----------------------------------------------------------------------------------------------------------

async def labour(ctx: Ctx) -> dict[str, Any]:
    periods = trend(ctx.period, TREND_PERIODS)
    span = await _attendance(ctx, periods[0].start, ctx.period.end)
    now = [ln for ln in span if _in(ctx.period, _date(ln["date"]))]
    before = [ln for ln in span if _in(ctx.prev, _date(ln["date"]))]
    totals, prev_totals = _labour_totals(now), _labour_totals(before)

    def grouped(key: Callable[[dict], Any]) -> dict[Any, list[dict]]:
        out: dict[Any, list[dict]] = defaultdict(list)
        for ln in now:
            out[key(ln)].append(ln)
        return out

    def row(label: str, ls: list[dict]) -> dict[str, Any]:
        t = _labour_totals(ls)
        return {"label": label, "man_days": qty(t["man_days"]), **({"wages": money(t["wages"])} if ctx.money else {})}

    by_trade = sorted((row((k or "labour").title(), v) for k, v in grouped(lambda ln: ln.get("trade")).items()),
                      key=lambda r: -Decimal(r["man_days"]))
    by_day = [{"date": d.isoformat(), **row(d.isoformat(), grouped(lambda ln: _date(ln["date"])).get(d, []))}
              for d in ctx.period.dates() if d <= ctx.last_day]
    by_site = sorted((row(ctx.sites.get(str(k), "Site"), v) for k, v in grouped(lambda ln: ln.get("site_id")).items()),
                     key=lambda r: -Decimal(r["man_days"]))
    series = [{"label": p.label, "from": p.start.isoformat(),
               "man_days": qty(_labour_totals([ln for ln in span if _in(p, _date(ln["date"]))])["man_days"])}
              for p in periods]
    worked_days = sum(1 for d in by_day if Decimal(d["man_days"]) > 0)
    return {
        "key": "labour", "title": "Labour", "status": "good" if now else "none",
        "man_days": qty(totals["man_days"]), "prev_man_days": qty(prev_totals["man_days"]),
        "change_pct": change(totals["man_days"], prev_totals["man_days"]),
        "average_per_day": qty(totals["man_days"] / worked_days) if worked_days else None,
        **({"wages": money(totals["wages"]), "prev_wages": money(prev_totals["wages"]),
            "unpriced_man_days": qty(totals["unpriced_man_days"])} if ctx.money else {}),
        "by_trade": by_trade, "by_day": by_day, "by_site": by_site, "trend": series,
        "link": "/labour",
    }


# -- materials --------------------------------------------------------------------------------------------------------

async def materials(ctx: Ctx) -> dict[str, Any]:
    from mesiri.domains.materials.router import stock_summary

    rows = await stock_summary(date_from=ctx.period.start, date_to=ctx.period.end, project_id=ctx.project_id,
                               site_id=ctx.site_id, material_id=None, category_id=None, auth_context=ctx.auth,
                               conn=ctx.conn)
    out = []
    for r in rows:
        received, used = Decimal(str(_get(r, "received") or 0)), Decimal(str(_get(r, "used") or 0))
        low = bool(_get(r, "running_low"))
        if not received and not used and not low:
            continue
        spend = _get(r, "spend")
        out.append({
            "material": _get(r, "material_name"), "unit": _get(r, "unit"), "category": _get(r, "category"),
            "site": ctx.sites.get(str(_get(r, "site_id")), None),
            "opening": qty(_get(r, "opening") or 0), "received": qty(received), "used": qty(used),
            "closing": qty(_get(r, "closing") or 0), "days_left": _get(r, "days_left"), "running_low": low,
            **({"spend": money(spend)} if ctx.money and spend is not None else {}),
        })
    out.sort(key=lambda r: (not r["running_low"], -Decimal(r["used"]), r["material"] or ""))
    low = [r for r in out if r["running_low"]]
    spend_total = sum((Decimal(r["spend"]) for r in out if r.get("spend")), ZERO) if ctx.money else None
    return {
        "key": "materials", "title": "Materials", "status": "warn" if low else "good" if out else "none",
        "received_items": sum(1 for r in out if Decimal(r["received"]) > 0),
        "used_items": sum(1 for r in out if Decimal(r["used"]) > 0),
        "running_low": len(low), **({"spend": money(spend_total)} if ctx.money else {}),
        "rows": out, "link": "/materials",
    }


# -- money ------------------------------------------------------------------------------------------------------------

async def _spent(ctx: Ctx, period: Period) -> dict[str, Any]:
    from mesiri.domains.costing.centres import cost_centres
    from mesiri.domains.costing.router import _scope

    return await cost_centres(ctx.conn, ctx.org, date_from=period.start, date_to=period.end,
                              **_scope(ctx.auth, ctx.project_id, ctx.site_id))


async def money_section(ctx: Ctx) -> dict[str, Any]:
    from mesiri.domains.costing.router import _scope, variance_for

    spent, prev = await _spent(ctx, ctx.period), await _spent(ctx, ctx.prev)
    total, prev_total = Decimal(str(spent["total"])), Decimal(str(prev["total"]))
    centres = [{"key": c["key"], "label": c["label"], "amount": money(c["amount"])}
               for c in spent["centres"] if Decimal(str(c["amount"]))]
    centres.sort(key=lambda c: -Decimal(c["amount"]))
    variance = await variance_for(ctx.conn, ctx.org, ctx.project_id, ctx.period.start, ctx.period.end, ctx.site_id,
                                  _scope(ctx.auth, ctx.project_id, ctx.site_id))
    summary = variance["summary"]
    worst = [ln for ln in variance["lines"] if ln["colour"] in ("red", "amber")][:5]
    out: dict[str, Any] = {
        "key": "money", "title": "Money",
        "spent": money(total), "prev_spent": money(prev_total), "change_pct": change(total, prev_total),
        "centres": centres, "not_set": money(spent.get("not_set", {}).get("amount")),
        "labour_colour": summary["colour"], "labour_earned": summary["earned_labour"],
        "labour_cost": summary["labour_cost"], "labour_difference": summary["difference"],
        "labour_lines": summary["lines"],
        "worst_lines": [{"work": ln["work"], "section": ln["section"], "colour": ln["colour"],
                         "done_quantity": ln["done_quantity"], "unit": ln["unit"], "labour_cost": ln["labour_cost"],
                         "earned_labour": ln["earned_labour"], "difference": ln["difference"],
                         "reason": ln["reason"]} for ln in worst],
        "materials_earned": variance["materials"]["earned"], "materials_bought": variance["materials"]["bought"],
        "link": f"/cost/green-red?project={ctx.project_id}",
    }
    if ctx.bills and ctx.site_id is None:
        out.update(await _billing(ctx))
    colour = summary["colour"]
    overdue = Decimal(out.get("overdue") or 0)
    # Green only when the labour was set against the work it earned and came out within it: spending alone, with
    # nothing to compare it with, is "none" (never a fake green).
    out["status"] = ("bad" if colour == "red" or overdue > 0 and out.get("oldest_overdue_days", 0) > 60
                     else "warn" if colour == "amber" or overdue > 0 else "good" if colour == "green" else "none")
    return out


async def _billing(ctx: Ctx) -> dict[str, Any]:
    from mesiri.domains.billing import bills as bill_store
    from mesiri.domains.billing import receipts
    from mesiri.domains.billing.receivables import OWED_STATUSES

    pid = {ctx.project_id}
    sent = [b for b in await bill_store.list_bills(ctx.conn, ctx.org, pid)
            if b["status"] in (*OWED_STATUSES, "paid") and _in(ctx.period, _date(b["bill_date"]))]
    got = await receipts.list_receipts(ctx.conn, ctx.org, pid, date_from=ctx.period.start, date_to=ctx.period.end,
                                       confirmed_only=True)
    owed = await receipts.owed(ctx.conn, ctx.org, pid, ctx.today)
    open_bills = [b for b in owed["bills"] if b["left"] > 0]
    overdue = [b for b in open_bills if b["days"] > OVERDUE_DAYS]
    overdue.sort(key=lambda b: -b["days"])
    return {
        "billed": money(sum((Decimal(str(b["net"] or 0)) for b in sent), ZERO)), "bills_sent": len(sent),
        "received": money(sum((Decimal(str(r["amount"])) for r in got if r["kind"] != "advance"), ZERO)),
        "advance_received": money(sum((Decimal(str(r["amount"])) for r in got if r["kind"] == "advance"), ZERO)),
        "owed": money(sum((b["left"] for b in open_bills), ZERO)),
        "overdue": money(sum((b["left"] for b in overdue), ZERO)),
        "oldest_overdue_days": overdue[0]["days"] if overdue else 0,
        "overdue_bills": [{"ref": b.get("ref"), "left": money(b["left"]), "days": b["days"],
                           "bill_date": _iso(b["bill_date"])} for b in overdue[:5]],
        "bills_link": "/accounts/receivables",
    }


# -- issues -----------------------------------------------------------------------------------------------------------

async def issues(ctx: Ctx) -> dict[str, Any]:
    from mesiri.domains.progress.router import list_issues

    listed = await list_issues(project_id=ctx.project_id, site_id=ctx.site_id, status=None, severity=None, limit=100,
                               offset=0, auth_context=ctx.auth, conn=ctx.conn)
    items = [i if isinstance(i, dict) else i.model_dump() for i in listed["items"]]
    raised = [i for i in items if _in(ctx.period, _date(i["occurred_at"]))]
    closed = [i for i in items if _in(ctx.period, _date(i.get("resolved_at")))]
    still = [i for i in items if str(i["status"]).upper() in ISSUE_OPEN]
    still.sort(key=lambda i: (SEVERITY_ORDER.get(str(i["severity"]).upper(), 9), _date(i["occurred_at"])))
    serious = [i for i in still if str(i["severity"]).upper() in ("CRITICAL", "HIGH")]
    return {
        "key": "issues", "title": "Issues",
        "status": "bad" if serious else "warn" if still else "good" if items else "none",
        "raised": len(raised), "closed": len(closed), "open": len(still), "serious_open": len(serious),
        "delay_hours": qty(sum((Decimal(i.get("delay_duration_minutes") or 0) for i in raised), ZERO) / 60),
        "rows": [{"id": str(i["id"]), "type": i["issue_type"], "severity": str(i["severity"]).lower(),
                  "what": i.get("narrative"), "site": ctx.sites.get(str(i["site_id"])),
                  "since": _iso(_date(i["occurred_at"])),
                  "days_open": (ctx.today - _date(i["occurred_at"])).days} for i in still[:20]],
        "link": "/issues",
    }


# -- photos -----------------------------------------------------------------------------------------------------------

def spread(items: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """``n`` items spread evenly over a list already in date order (the first and the last always kept)."""
    if len(items) <= n:
        return items
    if n == 1:
        return [items[-1]]
    step = (len(items) - 1) / (n - 1)
    return [items[round(i * step)] for i in range(n)]


async def photos(ctx: Ctx) -> dict[str, Any]:
    from mesiri.domains.client_view.view import approved_photos
    from mesiri.domains.shared.media import signed_media_url

    rows = [r for r in await approved_photos(ctx.conn, ctx.org, ctx.project_id, date_from=ctx.period.start,
                                             date_to=ctx.period.end, limit=200) if ctx.in_site(r.get("site_id"))]
    rows.sort(key=lambda r: (_date(r["day"]) or ctx.period.start))
    picked = spread(rows, PHOTO_COUNT)
    out = []
    for r in reversed(picked):  # newest first on the page
        url = await signed_media_url(ctx.storage, r["media_object_key"]) if ctx.storage else None
        out.append({"url": url, "caption": r.get("caption"), "work": r.get("work_type"),
                    "date": _iso(_date(r["day"])), "site": ctx.sites.get(str(r.get("site_id"))),
                    "_key": r["media_object_key"]})
    return {"key": "photos", "title": "Photos", "status": "good" if out else "none", "available": len(rows),
            "rows": out, "link": "/gallery"}


# -- completeness -----------------------------------------------------------------------------------------------------

async def completeness(ctx: Ctx) -> dict[str, Any]:
    """Each day up to today: confirmed site reports out of the sites, attendance recorded, the weather."""
    from mesiri.domains.dpr.router import list_daily_reports

    reports: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = await list_daily_reports(project_id=ctx.project_id, site_id=ctx.site_id, status=None, level="site",
                                        category=None, date_from=ctx.period.start, date_to=ctx.last_day, limit=100,
                                        offset=offset, auth_context=ctx.auth, conn=ctx.conn)
        reports.extend(page["items"])
        offset += 100
        if offset >= page["total"] or not page["items"]:
            break
    confirmed: dict[datetime.date, set[str]] = defaultdict(set)
    weather: dict[datetime.date, str] = {}
    for r in reports:
        day = _date(r["report_date"])
        if r.get("workflow_status") in ("approved", "published"):
            confirmed[day].add(str(r["site_id"]))
        if r.get("weather"):
            weather.setdefault(day, str(r["weather"]))
    attendance: dict[datetime.date, set[str]] = defaultdict(set)
    if ctx.enabled("labour"):
        for ln in await _attendance(ctx, *_span(ctx)):
            attendance[_date(ln["date"])].add(str(ln["site_id"]))
    sites = len(ctx.sites) if ctx.site_id is None else 1
    days = []
    for d in ctx.period.dates():
        if d > ctx.last_day:
            break
        days.append({"date": d.isoformat(), "weekday": f"{d:%a}", "reports": len(confirmed.get(d, ())),
                     "attendance": len(attendance.get(d, ())), "sites": sites, "weather": weather.get(d)})
    full = [d for d in days if d["reports"] >= d["sites"]]
    missing = [d for d in days if d["reports"] == 0]
    no_attendance = [d for d in days if ctx.enabled("labour") and d["attendance"] == 0]
    return {
        "key": "completeness", "title": "Is the data complete?",
        "status": "none" if not days else "good" if not missing and not no_attendance else
                  "warn" if len(missing) <= max(1, len(days) // 7) else "bad",
        "days_total": len(days), "days_full": len(full), "days_missing": [d["date"] for d in missing],
        "days_no_attendance": [d["date"] for d in no_attendance], "sites": sites, "days": days,
        "link": "/reports",
    }


def _span(ctx: Ctx) -> tuple[datetime.date, datetime.date]:
    """The attendance read the labour section already made (eight periods back to the period's end), so the
    completeness check does not read it again."""
    return trend(ctx.period, TREND_PERIODS)[0].start, ctx.period.end


SECTIONS = {
    "work": work, "schedule": schedule, "labour": labour, "materials": materials, "money": money_section,
    "issues": issues, "photos": photos, "completeness": completeness,
}
#: The module switch each section needs (``organization.settings.MODULES``); None: always on.
MODULE_OF: dict[str, str | None] = {
    "work": "dpr", "schedule": "dpr", "labour": "labour", "materials": "materials", "money": "finance",
    "issues": "dpr", "photos": "dpr", "completeness": "dpr",
}
