"""The report's headline, its key figures and "Needs you", made by fixed rules from the sections (PRC-19, D-R7).

Pure: no I/O. Every number in a sentence is one a section computed, so the headline can never say something the
report does not show. AI rewording may come later, behind a switch; it will start from these sentences.
"""

from __future__ import annotations

import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

MAX_FACTS = 3


def inr(value: Any) -> str:
    """Rupees the way a builder says them: ₹12,400 · ₹4.2 L · ₹2.31 Cr."""
    if value is None:
        return "—"
    v = Decimal(str(value))
    sign, v = ("-" if v < 0 else ""), abs(v)
    if v >= 10_000_000:
        return f"{sign}₹{(v / 10_000_000).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} Cr"
    if v >= 100_000:
        return f"{sign}₹{(v / 100_000).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)} L"
    return f"{sign}₹{int(v.quantize(Decimal(1), rounding=ROUND_HALF_UP)):,}"


def _day(iso: str | None) -> str:
    if not iso:
        return ""
    d = datetime.date.fromisoformat(iso[:10])
    return f"{d.day} {d:%b}"


def _num(v: Any) -> Decimal | None:
    return None if v in (None, "") else Decimal(str(v))


def _pct_text(v: Any) -> str:
    d = _num(v)
    if d is None:
        return "—"
    text = format(d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), "f")
    return text[:-2] if text.endswith(".0") else text


def _lateness(a: dict[str, Any]) -> str:
    """'is 4 days late' once its planned end has passed; 'is on pace to finish 17 days late' while it runs behind."""
    if a.get("days_late"):
        return f"is {a['days_late']} days late"
    return f"is on pace to finish {a['slip_days']} days late"


def lead(work: dict | None, money: dict | None, noun: str) -> str:
    """The first words: the period in one judgement, from the work and money colours."""
    w = (work or {}).get("status", "none")
    m = (money or {}).get("status", "none")
    if w == "none" and m in ("none", "good"):
        return f"Here is the {noun}." if not work or not work.get("has_plan") else f"A quiet {noun} on site."
    if w == "good" and m in ("good", "none"):
        return f"A good {noun} on site."
    if w == "good":
        return "Good progress on site; money needs a look."
    if m in ("good", "none"):
        return "Work is behind plan."
    return "Behind on work and over on cost."


def facts(s: dict[str, dict]) -> list[str]:
    """Sentences in order of what matters most; the first ``MAX_FACTS`` are the headline."""
    out: list[tuple[int, str]] = []
    work, sched, money, mat, iss, comp = (s.get(k) for k in ("work", "schedule", "money", "materials", "issues",
                                                              "completeness"))
    if work and work.get("plan_pct") is not None and work.get("done_pct") is not None:
        out.append((3, f"{_pct_text(work['done_pct'])}% of the job done against {_pct_text(work['plan_pct'])}% planned."))
    elif work and work.get("done_pct") is not None and _num(work["done_pct"]):
        out.append((5, f"{_pct_text(work['done_pct'])}% of the job done."))
    if sched and sched.get("rows"):
        top = sched["rows"][0]
        where = " (on the critical path)" if top["critical"] else ""
        if top["days_late"] or top["slip_days"]:
            out.append((1 if top["critical"] else 4, f"{top['activity']} {_lateness(top)}{where}."))
    if sched and sched.get("slip_days"):
        out.append((2, f"Finish now forecast {_day(sched['forecast_finish'])}, {sched['slip_days']} days after plan."))
    if money:
        worst = next((ln for ln in money.get("worst_lines") or [] if ln["colour"] == "red"), None)
        if worst and worst.get("difference") is not None:
            out.append((2, f"{worst['work']}: labour {inr(-_num(worst['difference']))} over the work done."))
        bills = money.get("overdue_bills") or []
        if bills:
            b = bills[0]
            out.append((1 if b["days"] > 60 else 3, f"{inr(b['left'])} of {b['ref']} unpaid for {b['days']} days."))
    if mat and mat.get("running_low"):
        low = next((r for r in mat["rows"] if r["running_low"]), None)
        if low:
            left = "runs out" if low["days_left"] in (None, 0) else f"lasts {low['days_left']} more days"
            out.append((3, f"{low['material']} {left}" + (f" at {low['site']}." if low.get("site") else ".")))
    if iss and iss.get("serious_open"):
        n = iss["serious_open"]
        out.append((2, f"{n} serious issue{'s' if n != 1 else ''} still open."))
    if comp and comp.get("days_missing"):
        n = len(comp["days_missing"])
        out.append((6, f"{n} day{'s' if n != 1 else ''} without a confirmed site report."))
    out.sort(key=lambda t: t[0])
    return [text for _, text in out]


def headline(sections: dict[str, dict], noun: str) -> dict[str, Any]:
    all_facts = facts(sections)
    return {"lead": lead(sections.get("work"), sections.get("money"), noun), "facts": all_facts[:MAX_FACTS],
            "more": all_facts[MAX_FACTS:]}


def _has_bills(money: dict) -> bool:
    """Client bills say something only when there is a bill or a payment: ₹0 billed, ₹0 received is noise."""
    return any(_num(money.get(k)) for k in ("billed", "received", "owed", "advance_received"))


def _versus(change_pct: Any, before: Any) -> str:
    """'▲ 6% vs last period', 'same as last period', or 'nothing last period'."""
    ch = _num(change_pct)
    if ch:
        return f"{'▲' if ch > 0 else '▼'} {_pct_text(abs(ch))}% vs last period"
    return "nothing last period" if not _num(before) else "same as last period"


def kpis(s: dict[str, dict]) -> list[dict[str, Any]]:
    """Up to five figures, each with what it is compared with and its tone (good / warn / bad / none)."""
    out: list[dict[str, Any]] = []
    work, labour, money, sched, mat, iss = (s.get(k) for k in ("work", "labour", "money", "schedule", "materials",
                                                                "issues"))
    if work:
        out.append({"key": "work", "label": "Work done", "value": f"{_pct_text(work['done_pct'])}%"
                    if work.get("done_pct") is not None else "—",
                    "note": f"plan {_pct_text(work['plan_pct'])}%" if work.get("plan_pct") is not None else "No plan yet",
                    "tone": work["status"], "section": "work"})
    if labour:
        out.append({"key": "man_days", "label": "Man-days", "value": _pct_text(labour["man_days"]),
                    "note": _versus(labour.get("change_pct"), labour.get("prev_man_days")),
                    "change_pct": labour.get("change_pct"), "trend": [p["man_days"] for p in labour["trend"]],
                    "tone": "none", "section": "labour"})
    if money:
        colour = money.get("labour_colour")
        out.append({"key": "spent", "label": "Spent", "value": inr(money["spent"]),
                    "note": {"red": "labour over work done", "amber": "labour: watch", "green": "labour on budget"}
                    .get(colour) or _versus(money.get("change_pct"), money.get("prev_spent")),
                    "change_pct": money.get("change_pct"),
                    "tone": {"red": "bad", "amber": "warn", "green": "good"}.get(colour, "none"), "section": "money"})
        if "billed" in money and _has_bills(money):
            out.append({"key": "billed", "label": "Billed · received", "value": inr(money["billed"]),
                        "note": f"{inr(money['received'])} received", "tone": "bad" if _num(money.get("overdue"))
                        and money.get("oldest_overdue_days", 0) > 60 else "warn" if _num(money.get("overdue"))
                        else "none", "section": "money"})
    if sched and sched.get("forecast_finish"):
        slip = sched.get("slip_days") or 0
        out.append({"key": "finish", "label": "Finish", "value": _day(sched["forecast_finish"]),
                    "note": f"+{slip} days" if slip else "on plan", "tone": sched["status"], "section": "schedule"})
    if len(out) < 5 and mat:
        out.append({"key": "low", "label": "Running low", "value": str(mat["running_low"]),
                    "note": f"{mat['received_items']} received · {mat['used_items']} used",
                    "tone": "warn" if mat["running_low"] else "good" if mat["rows"] else "none",
                    "section": "materials"})
    if len(out) < 5 and iss:
        out.append({"key": "issues", "label": "Open issues", "value": str(iss["open"]),
                    "note": f"{iss['raised']} raised · {iss['closed']} closed", "tone": iss["status"],
                    "section": "issues"})
    return out[:5]


def needs_you(s: dict[str, dict], waiting: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What a person should do, worst first: the report's own findings, then what the approvals inbox says is
    waiting in this project (acting stays on each module's own page)."""
    out: list[dict[str, Any]] = []
    money, sched, mat, iss, comp = (s.get(k) for k in ("money", "schedule", "materials", "issues", "completeness"))
    for b in (money or {}).get("overdue_bills") or []:
        out.append({"kind": "overdue_bill", "level": "bad" if b["days"] > 60 else "warn",
                    "title": f"{b['ref']}: {inr(b['left'])} unpaid for {b['days']} days",
                    "detail": f"Billed {_day(b['bill_date'])}", "action": "Open receivables",
                    "link": money.get("bills_link")})
    for ln in [ln for ln in (money or {}).get("worst_lines") or [] if ln["colour"] == "red"][:2]:
        out.append({"kind": "red_line", "level": "warn", "title": f"{ln['work']}: labour over the work done",
                    "detail": f"{inr(ln['labour_cost'])} spent for {ln['done_quantity']} {ln['unit']}"
                              + (f" · earned {inr(ln['earned_labour'])}" if ln.get("earned_labour") else ""),
                    "action": "Open green / red", "link": money.get("link")})
    for a in [a for a in (sched or {}).get("rows") or [] if a["critical"]][:2]:
        out.append({"kind": "late_activity", "level": "bad" if a["days_late"] else "warn",
                    "title": f"{a['activity']} {_lateness(a)}",
                    "detail": "On the critical path: it moves the finish" + (f" · {a['assigned_to']}"
                                                                             if a.get("assigned_to") else ""),
                    "action": "Open schedule", "link": sched.get("link")})
    for r in [r for r in (mat or {}).get("rows") or [] if r["running_low"]][:3]:
        out.append({"kind": "running_low", "level": "warn", "title": f"{r['material']} running low",
                    "detail": (f"{r['closing']} {r['unit']} left" + (f" · about {r['days_left']} days"
                               if r.get("days_left") else "")) + (f" · {r['site']}" if r.get("site") else ""),
                    "action": "Open stock", "link": mat.get("link")})
    for i in [i for i in (iss or {}).get("rows") or [] if i["severity"] in ("critical", "high")][:3]:
        out.append({"kind": "issue", "level": "bad" if i["severity"] == "critical" else "warn",
                    "title": f"{i['type'].replace('_', ' ').capitalize()}: {i['what'] or 'issue'}"[:120],
                    "detail": f"Open {i['days_open']} days" + (f" · {i['site']}" if i.get("site") else ""),
                    "action": "Open issues", "link": iss.get("link")})
    if comp and comp.get("days_missing"):
        n = len(comp["days_missing"])
        out.append({"kind": "missing_days", "level": "info",
                    "title": f"{n} day{'s' if n != 1 else ''} without a confirmed site report",
                    "detail": ", ".join(_day(d) for d in comp["days_missing"][:5]), "action": "Open daily reports",
                    "link": comp.get("link")})
    for w in waiting:
        out.append({"kind": w["kind"], "level": "warn" if w.get("urgent") else "info", "title": w["title"],
                    "detail": w.get("detail"), "action": None, "link": None, "waiting": w})
    order = {"bad": 0, "warn": 1, "info": 2}
    out.sort(key=lambda i: order[i["level"]])
    return out


STATUS_WORD = {"good": "On track", "warn": "Watch", "bad": "Needs action", "none": "No data"}


def areas(s: dict[str, dict]) -> list[dict[str, Any]]:
    """One line per area for "At a glance" (page 1 of the PDF, the page's summary, the Excel's Summary sheet)."""
    out = []

    def add(key: str, note: str, word: str | None = None) -> None:
        sec = s[key]
        out.append({"key": key, "title": sec["title"], "status": sec["status"],
                    "word": word or STATUS_WORD[sec["status"]], "note": note})

    if "work" in s:
        w = s["work"]
        if w.get("done_pct") is None:
            add("work", "No BOQ lines to measure work against yet.")
        else:
            plan = f" against {_pct_text(w['plan_pct'])}% planned" if w.get("plan_pct") is not None else " (no plan dates)"
            add("work", f"{_pct_text(w['done_pct'])}% of the job done{plan}; {w['progress_to_date'] or 0}% done to"
                        f" date; work recorded on {w['lines_worked']} BOQ line{'s' if w['lines_worked'] != 1 else ''}.",
                "No plan" if w["status"] == "none" else None)
    if "schedule" in s:
        sc = s["schedule"]
        if not sc["scheduled"]:
            add("schedule", "No activity has plan dates yet.", "No plan")
        else:
            late = len(sc["rows"])
            finish = f"Finish {_day(sc['forecast_finish'])}" if sc.get("forecast_finish") else "No finish date"
            add("schedule", f"{finish}" + (f", {sc['slip_days']} days after plan" if sc["slip_days"] else ", on plan")
                + (f"; {late} activit{'ies' if late != 1 else 'y'} late or behind." if late else "."))
    if "labour" in s:
        lb = s["labour"]
        top = ", ".join(f"{t['label']} {t['man_days']}" for t in lb["by_trade"][:3])
        add("labour", f"{lb['man_days']} man-days" + (f" ({top})" if top else "")
            + (f"; wages {inr(lb['wages'])}" if lb.get("wages") is not None else "") + ".",
            "Recorded" if lb["status"] == "good" else None)
    if "materials" in s:
        m = s["materials"]
        low = ", ".join(r["material"] for r in m["rows"] if r["running_low"])[:80]
        add("materials", f"{m['received_items']} received, {m['used_items']} used"
            + (f"; running low: {low}." if low else "; nothing running low."))
    if "money" in s:
        mo = s["money"]
        bits = [f"Spent {inr(mo['spent'])}"]
        if "billed" in mo and _has_bills(mo):
            bits.append(f"billed {inr(mo['billed'])}, received {inr(mo['received'])}")
            if _num(mo.get("overdue")):
                bits.append(f"{inr(mo['overdue'])} unpaid over 30 days")
        colour = {"red": "labour over the work done", "amber": "labour close to the work done",
                  "green": "labour within the work done"}.get(mo.get("labour_colour"))
        if colour:
            bits.append(colour)
        add("money", "; ".join(bits) + ".", "No budget" if mo["status"] == "none" else None)
    if "issues" in s:
        i = s["issues"]
        add("issues", f"{i['raised']} raised, {i['closed']} closed, {i['open']} open"
            + (f" ({i['serious_open']} serious)." if i["serious_open"] else "."))
    if "completeness" in s:
        c = s["completeness"]
        add("completeness", f"{c['days_full']} of {c['days_total']} days with every site report confirmed"
            + (f"; {len(c['days_no_attendance'])} without attendance." if c["days_no_attendance"] else "."),
            "Complete" if c["status"] == "good" else None)
    return out
