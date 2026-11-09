"""GM-04: the attention rules -- when a number crosses a line, one alert that says what, by how much, and what to do.

Pure functions: each takes what its module's own route answered and returns alerts. Nothing here reads the database
or decides who may see what (the routes did). Plan: docs/plans/gm-pm-plan.md (GM-04).

An alert: ``key`` (names the thing, stable across days, so a snooze holds), ``kind``, ``severity`` (``bad`` /
``warn``), ``title`` (what crossed the line), ``detail`` (by how much, in words), project and site, ``since``, and
``action`` (a label and the dashboard page that acts on it).

=============  =====================================================  ========  ============================
kind           crosses the line when                                  severity  source (its own route)
=============  =====================================================  ========  ============================
budget         a project's forecast at completion is red (CC-18)      bad       /cost/portfolio
cost           a BOQ line is red over the last 7 days (D-CC6)         bad       /cost/projects/{id}/variance
handover       the schedule forecasts the handover after its target   bad       /projects/{id}/schedule
late           an activity is past its end and not done               bad on the critical path, else warn
order          a material must be ordered today (or by tomorrow)      bad / warn  /projects/{id}/material-plan
unreported     a working site sent nothing by the project's cut-off   warn      /dpr/site-days
issue          an issue open for 2+ days                              bad if high / critical, else warn
hire           a hire bill asks for more than the machine's log       warn      /equipment/hire-check
=============  =====================================================  ========  ============================

Severity orders the list; ``warn`` items are still worth a look. A site engineer's cost answer has no money
(D-CC4), so their cost alerts say quantities and man-days, never rupees.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

#: An issue open this many days or more is an alert.
ISSUE_DAYS = 2
#: When a project has no reporting cut-off of its own.
DEFAULT_CUTOFF = datetime.time(18, 0)
#: At most this many alerts of one kind per project, worst first (the rest: "and N more" in the last one).
PER_PROJECT = 3
_RANK = {"bad": 0, "warn": 1}


def _alert(key: str, kind: str, severity: str, title: str, detail: str, *, project_id: Any = None,
           project_name: str | None = None, site_name: str | None = None, since: str | None = None,
           action: str, link: str) -> dict[str, Any]:
    return {"key": key, "kind": kind, "severity": severity, "title": title, "detail": detail,
            "project_id": str(project_id) if project_id else None, "project_name": project_name,
            "site_name": site_name, "since": since, "action": {"label": action, "link": link}}


def _inr(v: Any) -> str:
    from mesiri.domains.equipment.rules import inr

    return inr(Decimal(str(v)))


def _num(v: Any) -> str:
    return f"{Decimal(str(v)).normalize():f}"


def _day(v: Any) -> str:
    d = v if isinstance(v, datetime.date) else datetime.date.fromisoformat(str(v)[:10])
    return f"{d:%a} {d.day} {d:%b}"


def _days(n: int) -> str:
    return f"{n} day{'s' if n != 1 else ''}"


def _cap(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the worst PER_PROJECT; the last one kept says how many more there are."""
    if len(alerts) <= PER_PROJECT:
        return alerts
    kept = alerts[:PER_PROJECT]
    kept[-1] = {**kept[-1], "detail": kept[-1]["detail"] + f" (and {len(alerts) - PER_PROJECT} more like this)"}
    return kept


# --- one rule per source ---------------------------------------------------------------------------------------------


def cost_alerts(project: dict[str, Any], variance: dict[str, Any]) -> list[dict[str, Any]]:
    """Red BOQ lines in the variance answer (last 7 days), the biggest overspend first."""
    hidden = bool(variance.get("money_hidden"))
    out = []
    for ln in variance.get("lines", []):
        if ln["colour"] != "red":
            continue
        work, unit = ln["work"], ln["unit"]
        done, man_days = ln.get("done_quantity") or "0", ln.get("labour_man_days") or "0"
        if ln["reason"] == "labour_no_work":
            title = f"Labour on {work}, but no work recorded"
            detail = f"{_num(man_days)} man-days in the last 7 days and no {unit} counted on the line"
        elif hidden:
            title = f"{work} is over its labour budget"
            detail = f"{_num(done)} {unit} for {_num(man_days)} man-days in the last 7 days"
        else:
            over = -Decimal(ln["difference"]) if ln.get("difference") is not None else Decimal(0)
            title = f"{work} is {_inr(over)} over its labour budget"
            detail = (f"{_inr(ln['labour_cost'])} of labour for {_num(done)} {unit} in the last 7 days; the work earned "
                      f"{_inr(ln['earned_labour'])}" if ln.get("labour_cost") is not None else
                      f"{_num(done)} {unit} for {_num(man_days)} man-days in the last 7 days")
        out.append(_alert(f"cost:{ln['line_id']}", "cost", "bad", title, detail, project_id=project["id"],
                          project_name=project["name"], action="See green / red",
                          link=f"/cost/green-red?project={project['id']}"))
    return _cap(out)


def budget_alerts(portfolio: dict[str, Any]) -> list[dict[str, Any]]:
    """Projects whose forecast at completion is red against their budget (the portfolio's own colour, CC-19)."""
    out = []
    for p in portfolio.get("projects", []):
        diff = p.get("forecast_difference")
        if p.get("colour") != "red" or diff is None or Decimal(diff) >= 0:
            continue
        kinds = ", ".join(p.get("forecast_kinds") or []) or "the BOQ"
        out.append(_alert(f"budget:{p['project_id']}", "budget", "bad",
                          f"Forecast {_inr(-Decimal(diff))} over budget",
                          f"At this rate {kinds} will cost {_inr(p['forecast'])} against a budget of "
                          f"{_inr(p['forecast_budget'])}; {p.get('percent_done') or '0'}% done, "
                          f"{p.get('percent_spent') or '0'}% spent", project_id=p["project_id"],
                          project_name=p["name"], action="Open budget vs actual",
                          link=f"/cost/budget?project={p['project_id']}"))
    return out


def schedule_alerts(project: dict[str, Any], schedule: dict[str, Any]) -> list[dict[str, Any]]:
    """The handover forecast after its target, then late activities: the critical path first, the longest late."""
    out = []
    s = schedule.get("summary") or {}
    link = f"/planning/schedule?project={project['id']}"
    if s.get("slip_days") and s.get("forecast_finish"):
        target = s.get("contract_finish") or s.get("planned_finish")
        out.append(_alert(f"handover:{project['id']}", "handover", "bad",
                          f"Handover forecast {_days(s['slip_days'])} late",
                          f"At the pace site is going it finishes {_day(s['forecast_finish'])}; "
                          f"{'the contract date' if s.get('contract_finish') else 'the plan'} is {_day(target)}",
                          project_id=project["id"], project_name=project["name"], action="Open the schedule", link=link))
    late = [a for a in schedule.get("activities", []) if a.get("state") == "late"]
    late.sort(key=lambda a: (not a.get("critical"), -(a.get("days_late") or 0)))
    acts = []
    for a in late:
        pushes = f"; it pushes the work after it by {_days(a['pushed_days'])}" if a.get("pushed_days") else ""
        progress = f"{a['progress']}% done" if a.get("progress") is not None else "Not started"
        detail = (f"{progress}, planned to finish {_day(a['end'])}"
                  + (f"; forecast {_day(a['forecast_end'])}" if a.get("forecast_end") else "") + pushes)
        if a.get("critical"):
            detail += ". On the critical path: each day late moves the handover"
        acts.append(_alert(f"late:{a['id']}", "late", "bad" if a.get("critical") else "warn",
                           f"{a['name']} is {_days(a.get('days_late') or 0)} late", detail, project_id=project["id"],
                           project_name=project["name"], site_name=a.get("site_name"), action="Open the schedule",
                           link=link))
    return out + _cap(acts)


def order_alerts(project: dict[str, Any], plan: dict[str, Any], today: datetime.date) -> list[dict[str, Any]]:
    """Materials whose order-by day is today (or past), then tomorrow."""
    out = []
    for m in plan.get("materials", []):
        order_by = m.get("order_by")
        if order_by is None:
            continue
        order_by = order_by if isinstance(order_by, datetime.date) else datetime.date.fromisoformat(str(order_by))
        if order_by > today + datetime.timedelta(days=1):
            continue
        now = order_by <= today
        lead = f"; {m['supplier']} takes {_days(int(m['lead_days']))}" if m.get("supplier") and m.get("lead_days") else ""
        short = f"{_num(Decimal(str(m['short_by'])).quantize(Decimal('1')))} {m['unit']} short" if m.get("short_by") else "Short"
        out.append(_alert(f"order:{project['id']}:{m['material_id']}", "order", "bad" if now else "warn",
                          f"Order {m['material']} {'today' if now else 'by tomorrow'}",
                          f"{short} from {_day(m['short_day'])}{lead}" if m.get("short_day") else short + lead,
                          project_id=project["id"], project_name=project["name"], action="Open the material plan",
                          link=f"/planning/materials?project={project['id']}"))
    return _cap(out)


def _cutoff(value: Any) -> datetime.time:
    if isinstance(value, datetime.time):
        return value
    if value:
        try:
            return datetime.time.fromisoformat(str(value)[:8])
        except ValueError:
            pass
    return DEFAULT_CUTOFF


def has_updates(site: dict[str, Any]) -> bool:
    """The Today page's rule (dashboard ``lib/site-day.ts`` hasUpdates): anything sent that day, or "no work today"."""
    return any((site.get(k) or 0) > 0 for k in ("work_items", "workers", "materials", "issues_today",
                                                  "progress_updates", "drafts")) or site.get("site_working") == "none"


def report_alerts(site_days: dict[str, Any], now_local: datetime.datetime) -> list[dict[str, Any]]:
    """Sites that sent nothing today once their project's reporting cut-off has passed."""
    cutoffs = {str(p["project_id"]): _cutoff(p.get("reporting_cutoff_time")) for p in site_days.get("projects", [])}
    date = site_days.get("date") or now_local.date().isoformat()
    out = []
    for s in site_days.get("items", []):
        cutoff = cutoffs.get(str(s["project_id"]), DEFAULT_CUTOFF)
        if has_updates(s) or now_local.time() < cutoff:
            continue
        out.append(_alert(f"unreported:{s['site_id']}:{date}", "unreported", "warn",
                          f"{s['site_name']} has not reported today",
                          f"Nothing from the site by {cutoff:%H:%M}" + (f"; last update {_day(s['last_update_at'])}"
                                                                         if s.get("last_update_at") else ""),
                          project_id=s["project_id"], project_name=s.get("project_name"), site_name=s["site_name"],
                          action="Open Today", link="/today"))
    return out


def issue_alerts(issues: list[dict[str, Any]], now: datetime.datetime, names: dict[str, str]) -> list[dict[str, Any]]:
    """Issues open for ISSUE_DAYS days or more; high / critical ones are bad. ``names``: project and site names."""
    out = []
    for i in issues:
        occurred = i["occurred_at"] if isinstance(i["occurred_at"], datetime.datetime) else \
            datetime.datetime.fromisoformat(str(i["occurred_at"]))
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=datetime.UTC)
        age = (now - occurred).days
        if age < ISSUE_DAYS:
            continue
        what = (i.get("narrative") or str(i.get("issue_type") or "Issue").replace("_", " ").capitalize()).strip()
        what = what if len(what) <= 70 else what[:67].rstrip() + "…"
        owner = "no one is on it" if not i.get("assigned_user_id") else "someone is on it"
        severity = str(i.get("severity") or "").upper()
        out.append(_alert(f"issue:{i['id']}", "issue", "bad" if severity in ("HIGH", "CRITICAL") else "warn",
                          f"Open {_days(age)}: {what}",
                          f"{severity.capitalize() or 'Medium'} · {owner}", project_id=i["project_id"],
                          project_name=names.get(str(i["project_id"])), site_name=names.get(str(i["site_id"])),
                          since=occurred.isoformat(), action="Open issues", link="/issues"))
    return out


def hire_alerts(hire: dict[str, Any]) -> list[dict[str, Any]]:
    """Hire bills that ask for more than the machine's log."""
    out = []
    for m in hire.get("items", []):
        for b in m.get("bills", []):
            check = b.get("check") or {}
            if check.get("status") != "over":
                continue
            out.append(_alert(f"hire:{b['id']}", "hire", "warn", f"{m['name']} hire bill is more than its log",
                              (check.get("flags") or ["The bill is more than the hours recorded"])[0].rstrip("."),
                              project_name=m.get("project_name"), site_name=m.get("site_name"),
                              action="Open the hire check", link="/equipment/hire"))
    return out


def arrange(alerts: list[dict[str, Any]], snoozed: set[str]) -> dict[str, Any]:
    """Bad first, then by kind's order in the table above; snoozed ones out (counted)."""
    kinds = ("handover", "budget", "cost", "late", "order", "issue", "unreported", "hire")
    shown = [a for a in alerts if a["key"] not in snoozed]
    shown.sort(key=lambda a: (_RANK[a["severity"]], kinds.index(a["kind"]), a["project_name"] or ""))
    counts = {"total": len(shown), "bad": sum(1 for a in shown if a["severity"] == "bad"),
              "warn": sum(1 for a in shown if a["severity"] == "warn"), "snoozed": len(alerts) - len(shown)}
    hidden = [a for a in alerts if a["key"] in snoozed]
    return {"items": shown, "snoozed": hidden, "counts": counts}
