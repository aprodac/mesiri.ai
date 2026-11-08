"""NXT-11 / NXT-13 / NXT-15: the rules that decide what a machine's day means -- what the hire company may charge,
whether it is working, broken down or not logged, when it is due for service, and whether a hire bill matches the
hours recorded on site. Pure functions over plain dicts (the rows ``store.py`` reads); no SQL here.

**What a hired machine earns** (the hire company's charge, as site teams in Kerala agree it):

- **per hour**: the hours it worked; on a day it was on site (worked or idle) the hire's minimum hours a day
  (``min_hours_per_day``, "minimum 8 hours") is charged when it worked less. Breakdown hours are never charged:
  a broken machine is the hire company's loss, not ours.
- **per day**: one day's rate for each day it was on site (worked or idle), nothing for a day it only stood broken.
- **per month**: the month's rate spread over the calendar days on hire (rate / 30 a day), whether logged or not,
  from on hire to off hire (or today).

A day is put on the site it was logged at; a monthly day with no log goes to the site of the last log before it,
else the machine's site.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

ZERO = Decimal(0)
_C = Decimal("0.01")
#: Days a monthly rate is spread over.
MONTH_DAYS = Decimal(30)
#: A bill this much over what was recorded is flagged (rounding, a half-hour here and there).
HOURS_TOLERANCE = Decimal("0.5")
AMOUNT_TOLERANCE = Decimal("0.01")  # 1 %
#: Service is "soon" from this share of the interval.
SERVICE_SOON = Decimal("0.9")


def d(value: Any) -> Decimal:
    return ZERO if value is None or value == "" else Decimal(str(value))


def money(value: Decimal) -> str:
    return str(Decimal(value).quantize(_C))


def inr(value: Decimal) -> str:
    """Rupees as people write them: "₹80,300", "₹1,43,000" (Indian grouping, whole rupees)."""
    n = int(Decimal(value).quantize(Decimal(1)))
    sign, s = ("-" if n < 0 else ""), str(abs(n))
    head, tail = s[:-3], s[-3:]
    while len(head) > 2:
        tail = f"{head[-2:]},{tail}"
        head = head[:-2]
    return f"{sign}₹{head + ',' if head else ''}{tail}"


def num(value: Decimal | None) -> str | None:
    """A figure as people read it: "6", "6.5", never "6.00"."""
    if value is None:
        return None
    q = Decimal(value).quantize(_C).normalize()
    return format(q, "f")


def ref(number: int) -> str:
    return f"EQ-{number:04d}"


def worked(log: dict) -> Decimal:
    return d(log.get("duration_hours"))


def on_site(log: dict) -> bool:
    """It stood on the site that day ready to work (worked or idle), not only broken."""
    return worked(log) + d(log.get("idle_hours")) > 0


def charged_hours(machine: dict, log: dict) -> Decimal:
    """Per-hour hire: the hours the hire company may charge for this day."""
    if not on_site(log):
        return ZERO
    minimum = d(machine.get("min_hours_per_day"))
    return max(worked(log), minimum) if minimum else worked(log)


def _day_rate(machine: dict) -> Decimal:
    return d(machine.get("rate"))


def hire_lines(machine: dict, logs: list[dict], date_from: datetime.date, date_to: datetime.date,
               today: datetime.date) -> list[dict]:
    """What a hired machine earned per day in the period: ``{date, project_id, site_id, hours, amount}``.

    Owned machines, and hired ones without a rate, earn nothing here (their diesel still costs)."""
    if machine.get("ownership") != "hired" or machine.get("rate") is None or not machine.get("rate_unit"):
        return []
    unit, rate = machine["rate_unit"], _day_rate(machine)
    day_logs = sorted((x for x in logs if x.get("event_type") == "day_log" and not x.get("voided_at")),
                      key=lambda x: x["occurred_date"])
    out: list[dict] = []
    if unit in ("hour", "day"):
        for log in day_logs:
            if not (date_from <= log["occurred_date"] <= date_to) or not on_site(log):
                continue
            hours = charged_hours(machine, log)
            amount = rate * hours if unit == "hour" else rate
            out.append({"date": log["occurred_date"], "project_id": log["project_id"], "site_id": log["site_id"],
                        "hours": hours, "amount": amount})
        return out
    # Monthly: every calendar day on hire.
    start = machine.get("on_hire_from") or (day_logs[0]["occurred_date"] if day_logs else None)
    if start is None:
        return []
    end = machine.get("off_hire_on") or today
    start, end = max(start, date_from), min(end, date_to, today)
    by_date = {x["occurred_date"]: x for x in day_logs}
    before = [x for x in day_logs if x["occurred_date"] < start]
    where = (before[-1]["project_id"], before[-1]["site_id"]) if before else (machine.get("project_id"), machine.get("site_id"))
    per_day = rate / MONTH_DAYS
    day = start
    while day <= end:
        log = by_date.get(day)
        if log is not None:
            where = (log["project_id"], log["site_id"])
        out.append({"date": day, "project_id": where[0], "site_id": where[1],
                    "hours": charged_hours(machine, log) if log else ZERO, "amount": per_day})
        day += datetime.timedelta(days=1)
    return out


def billed(day: datetime.date, bills: list[dict], *, with_expense_only: bool = False) -> dict | None:
    """The hire bill covering this day, if any. For cost, only a bill that is an expense counts (that expense is
    in Expenses already; the day is not counted twice)."""
    for b in bills:
        if b["period_from"] <= day <= b["period_to"] and (b.get("expense_id") or not with_expense_only):
            return b
    return None


def utilisation(worked_h: Decimal, idle_h: Decimal, breakdown_h: Decimal) -> Decimal | None:
    """Worked hours as a share of the hours it stood on site (worked + idle + broken)."""
    total = worked_h + idle_h + breakdown_h
    return None if not total else (worked_h / total).quantize(Decimal("0.001"))


def state(machine: dict, today_log: dict | None) -> str:
    """One word for the board: off_hire, retired, no_site, not_logged, breakdown, idle, working."""
    if machine.get("status") in ("off_hire", "retired"):
        return str(machine["status"])
    if today_log is None:
        return "not_logged" if machine.get("site_id") else "no_site"
    if d(today_log.get("breakdown_hours")) > 0 and worked(today_log) == 0:
        return "breakdown"
    if worked(today_log) == 0:
        return "idle"
    return "working"


def service(machine: dict, hours_since: Decimal) -> dict | None:
    """Service due by hours worked since the last service (or since it was added)."""
    every = machine.get("service_every_hours")
    if every is None:
        return None
    every = d(every)
    left = every - hours_since
    status = "due" if left <= 0 else "soon" if hours_since >= every * SERVICE_SOON else "ok"
    return {"every": num(every), "since": num(hours_since), "left": num(max(left, ZERO)), "status": status,
            "last_on": machine["last_service_on"].isoformat() if machine.get("last_service_on") else None}


def hire_check(machine: dict, logs: list[dict], bill: dict, today: datetime.date) -> dict:
    """NXT-13: one hire bill against what was recorded on site for its machine and period."""
    f, t = bill["period_from"], bill["period_to"]
    lines = hire_lines(machine, logs, f, t, today)
    in_period = [x for x in logs if x.get("event_type") == "day_log" and not x.get("voided_at")
                 and f <= x["occurred_date"] <= t]
    recorded = {
        "worked": sum((worked(x) for x in in_period), ZERO),
        "idle": sum((d(x.get("idle_hours")) for x in in_period), ZERO),
        "breakdown": sum((d(x.get("breakdown_hours")) for x in in_period), ZERO),
        "days_on_site": sum(1 for x in in_period if on_site(x)),
        # From the logs, whatever the rate (a machine without one still has its hours checked).
        "charged_hours": sum((charged_hours(machine, x) for x in in_period), ZERO),
        "expected": sum((x["amount"] for x in lines), ZERO),
    }
    # Days it should have a log: on hire, in the period, up to today.
    start, end = max(f, machine.get("on_hire_from") or f), min(t, today, machine.get("off_hire_on") or t)
    period_days = (end - start).days + 1 if start <= end else 0
    logged_days = {x["occurred_date"] for x in in_period if start <= x["occurred_date"] <= end}
    missing = max(period_days - len(logged_days), 0) if period_days else 0
    over: list[str] = []   # the bill asks for more than was recorded
    notes: list[str] = []  # the check could not be complete
    billed_h, billed_d, amount = bill.get("billed_hours"), bill.get("billed_days"), d(bill["amount"])
    if billed_h is not None and d(billed_h) > recorded["charged_hours"] + HOURS_TOLERANCE:
        over.append(f"Bill says {num(d(billed_h))} hours; {num(recorded['charged_hours'])} recorded on site.")
    if billed_d is not None and d(billed_d) > recorded["days_on_site"]:
        over.append(f"Bill says {num(d(billed_d))} days; on site {recorded['days_on_site']} days.")
    if recorded["expected"] and amount > recorded["expected"] * (1 + AMOUNT_TOLERANCE):
        over.append(f"Bill is {inr(amount - recorded['expected'])} more than the hours recorded come to.")
    if machine.get("rate") is None:
        notes.append("No hire rate on the machine: add it to check the amount.")
    if missing:
        notes.append(f"{missing} day{'s' if missing != 1 else ''} in the period with no log.")
    difference = amount - recorded["expected"] if recorded["expected"] else None
    return {
        "recorded": {"worked": num(recorded["worked"]), "idle": num(recorded["idle"]),
                     "breakdown": num(recorded["breakdown"]), "days_on_site": recorded["days_on_site"],
                     "charged_hours": num(recorded["charged_hours"]), "expected": money(recorded["expected"])},
        "difference": money(difference) if difference is not None else None,
        "days_not_logged": missing,
        "status": "over" if over else "check" if notes else "ok",
        "flags": over + notes,
    }
