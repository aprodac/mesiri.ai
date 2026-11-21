"""Wages and advances: the rules (LW-03, LW-04; docs/plans/wages-and-labour-plan.md, approved by Ilan 9 Nov 2026).

Pure, no I/O: attendance lines and advances in, a wage sheet's rows out. ``pay_store.py`` reads and writes.

- **Pay period (D-W1):** a week ending on the pay day, Saturday by default.
- **Payee (D-W2):** a line naming a labour contractor (``vendor_id``), or a worker whose register row names a team,
  is paid through that contractor; a registered worker with no team is paid directly; anything else (a name in
  words, a headcount with no name) is grouped by its words, so nothing reported is lost from the sheet.
- **Days:** present 1, half day 0.5, absent 0; a line's man-days are its headcount times that. The same figure the
  cost control counts (``repositories/workforce.aggregate_attendance``), so wages and labour cost agree.
- **Overtime (D-W4):** hours x daily wage / 8, per person on the line.
- **Advance recovery (D-W3):** everything outstanding at the end of the period is recovered, up to what the row
  earns, unless the person paying set the amount.
- **Net:** gross + overtime - advances recovered - deductions (each with a reason).
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

PAY_DAY = 5  # Monday is 0: Saturday (D-W1)
OVERTIME_HOURS_PER_DAY = Decimal(8)  # D-W4: hours x daily wage / 8
DAY_FACTOR = {"present": Decimal(1), "half_day": Decimal("0.5"), "absent": Decimal(0)}
_CENT = Decimal("0.01")


def money(v: Any) -> Decimal:
    return Decimal(str(v or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)


def week_of(day: datetime.date, pay_day: int = PAY_DAY) -> tuple[datetime.date, datetime.date]:
    """The pay week a day falls in: the seven days ending on the pay day."""
    end = day + datetime.timedelta(days=(pay_day - day.weekday()) % 7)
    return end - datetime.timedelta(days=6), end


Teams = Mapping[str, Any]  # {"by_id": {vendor id: name}, "by_name": {lower-case name: vendor id}}


def team_of(line: Mapping[str, Any], worker_team: Mapping[str, Any], teams: Teams | None) -> Any:
    """The labour contractor a line is paid through: its own ``vendor_id``, the worker's team on the register, or the
    contractor named in words when a team of that name exists (attendance sent before the team was set up)."""
    if line.get("vendor_id"):
        return line["vendor_id"]
    if line.get("worker_id") and worker_team.get(str(line["worker_id"])):
        return worker_team[str(line["worker_id"])]
    words = " ".join(str(line.get("contractor") or "").lower().split())
    return (teams or {}).get("by_name", {}).get(words) if words else None


def payee_of(line: Mapping[str, Any], worker_team: Mapping[str, Any], teams: Teams | None = None) -> tuple[str, dict[str, Any]]:
    """(payee key, who) for an attendance line. ``worker_team`` maps a worker id to its team's vendor id."""
    vendor = team_of(line, worker_team, teams)
    if vendor:
        name = (teams or {}).get("by_id", {}).get(str(vendor)) or line.get("vendor_name") or line.get("contractor")
        return f"vendor:{vendor}", {"vendor_id": vendor, "worker_id": None, "payee_name": name or "Labour team"}
    if line.get("worker_id"):
        return f"worker:{line['worker_id']}", {"worker_id": line["worker_id"], "vendor_id": None,
                                                "payee_name": line.get("worker_name") or "Worker"}
    words = (line.get("contractor") or "").strip()
    if words:
        return f"name:{words.lower()}", {"worker_id": None, "vendor_id": None, "payee_name": f"{words} (team, not linked)"}
    name = (line.get("worker_name") or "").strip()
    if name:
        return f"name:{name.lower()}", {"worker_id": None, "vendor_id": None, "payee_name": name}
    trade = (line.get("trade") or "labour").strip()
    return f"headcount:{trade.lower()}", {"worker_id": None, "vendor_id": None, "payee_name": f"{trade.title()} (no names)"}


def build_rows(lines: Iterable[Mapping[str, Any]], worker_team: Mapping[str, Any],
               teams: Teams | None = None) -> dict[str, dict[str, Any]]:
    """Attendance lines of one sheet's period -> one row per payee: days, man-days, gross, overtime."""
    rows: dict[str, dict[str, Any]] = {}
    for ln in lines:
        factor = DAY_FACTOR.get(ln.get("attendance_status") or "present", Decimal(1))
        heads = Decimal(int(ln.get("headcount") or 1))
        md = heads * factor
        if md == 0 and not ln.get("overtime_hours"):
            continue
        key, who = payee_of(ln, worker_team, teams)
        row = rows.setdefault(key, {"payee_key": key, **who, "trades": set(), "dates": set(), "man_days": Decimal(0),
                                    "unpriced_man_days": Decimal(0), "overtime_hours": Decimal(0), "gross": Decimal(0),
                                    "overtime_amount": Decimal(0)})
        if ln.get("trade"):
            row["trades"].add(str(ln["trade"]))
        if md:
            row["dates"].add(ln["date"])
        row["man_days"] += md
        wage = ln.get("daily_wage")
        ot = Decimal(str(ln.get("overtime_hours") or 0)) * heads
        row["overtime_hours"] += ot
        if wage is None:
            row["unpriced_man_days"] += md
        else:
            row["gross"] += md * Decimal(str(wage))
            row["overtime_amount"] += ot * Decimal(str(wage)) / OVERTIME_HOURS_PER_DAY
    for row in rows.values():
        row["days"] = Decimal(len(row["dates"]))
        row["trades"] = ", ".join(sorted(row["trades"]))
        row["gross"] = money(row["gross"])
        row["overtime_amount"] = money(row["overtime_amount"])
        del row["dates"]
    return rows


def deductions_total(deductions: Iterable[Mapping[str, Any]]) -> Decimal:
    return money(sum((Decimal(str(d.get("amount") or 0)) for d in deductions), Decimal(0)))


def settle(row: Mapping[str, Any], outstanding: Decimal, recovered: Decimal | None = None) -> dict[str, Decimal]:
    """Advances recovered and net for a row. ``recovered`` is the payer's own figure; None means the default (D-W3):
    all outstanding, never more than the row earns after deductions."""
    earned = money(row["gross"]) + money(row["overtime_amount"]) - deductions_total(row.get("deductions") or [])
    if recovered is None:
        recovered = min(max(outstanding, Decimal(0)), max(earned, Decimal(0)))
    recovered = money(recovered)
    return {"advances_recovered": recovered, "net": money(earned - recovered)}


def outstanding_advances(advances: Iterable[Mapping[str, Any]], recovered_elsewhere: Decimal, until: datetime.date) -> Decimal:
    """What a payee still owes from advances given up to ``until``, after recoveries on other sheets."""
    given = sum((Decimal(str(a["amount"])) for a in advances if not a.get("voided_at") and a["given_on"] <= until),
                Decimal(0))
    return money(given - recovered_elsewhere)


def slip_text(row: Mapping[str, Any], period_from: datetime.date, period_to: datetime.date, project: str | None) -> str:
    """The payment slip sent to a worker or a contractor on WhatsApp (LW-05)."""
    def r(v: Any) -> str:
        return f"₹{money(v):,.0f}"
    lines = [f"*{row['payee_name']}*", f"{project + ' · ' if project else ''}{period_from:%d %b} – {period_to:%d %b %Y}",
             f"Days: {Decimal(row['man_days']).normalize():f} ({row.get('trades') or 'labour'})", f"Wages: {r(row['gross'])}"]
    if money(row.get("overtime_amount")):
        lines.append(f"Overtime: {r(row['overtime_amount'])}")
    if money(row.get("advances_recovered")):
        lines.append(f"Advance taken back: −{r(row['advances_recovered'])}")
    for d in row.get("deductions") or []:
        lines.append(f"{d.get('reason') or 'Deduction'}: −{r(d.get('amount'))}")
    lines.append(f"*To pay: {r(row['net'])}*")
    if money(row.get("paid")):
        lines.append(f"Paid: {r(row['paid'])}" + (f" · still due {r(money(row['net']) - money(row['paid']))}"
                                                  if money(row['net']) > money(row['paid']) else ""))
    return "\n".join(lines)


# -- LW-10: labour reports (21 Nov 2026) -------------------------------------------------------------------------------

REPORT_BY = ("project", "site", "trade", "payee")
_NO_TRADE = "Trade not said"


def report_key(line: Mapping[str, Any], by: str, worker_team: Mapping[str, Any], teams: Teams | None) -> tuple[str, str]:
    """(key, label) a line is reported under: its project, its site, its trade, or who is paid for it (D-W2)."""
    if by == "project":
        return str(line.get("project_id")), line.get("project_name") or "Project"
    if by == "site":
        return str(line.get("site_id")), " › ".join(x for x in (line.get("project_name"), line.get("site_name")) if x) or "No site"
    if by == "trade":
        trade = " ".join(str(line.get("trade") or "").replace("_", " ").split())
        return trade.lower(), trade.capitalize() if trade else _NO_TRADE
    key, who = payee_of(line, worker_team, teams)
    return key, who["payee_name"]


def report_rows(lines: Iterable[Mapping[str, Any]], sheet_rows: Iterable[Mapping[str, Any]], by: str,
                worker_team: Mapping[str, Any], teams: Teams | None = None) -> list[dict[str, Any]]:
    """Labour for a period, one row per project, site, trade or payee (LW-10).

    Earned from attendance by the wage sheet's own rule (``build_rows``: present 1, half 0.5, overtime hours x wage / 8),
    so a report and the wage sheets never disagree. Paid from the wage sheets in the period (``sheet_rows``: each with
    project_id, site_id, payee_key, status, net, paid): ``to_pay`` is what approved sheets say (after advances taken
    back and deductions), ``paid`` what was paid on them, ``owed`` approved and not yet paid, ``waiting`` the drafts
    nobody approved yet. By trade there is no pay: a sheet pays a person or a team, not a trade (None, never a guess).
    """
    groups: dict[str, dict[str, Any]] = {}
    for ln in lines:
        key, label = report_key(ln, by, worker_team, teams)
        g = groups.setdefault(key, {"key": key, "label": label, "lines": [], "dates": set()})
        g["lines"].append(ln)
    out: dict[str, dict[str, Any]] = {}
    for key, g in groups.items():
        built = build_rows(g["lines"], worker_team, teams).values()
        if not built:
            continue
        worked = {ln["date"] for ln in g["lines"] if DAY_FACTOR.get(ln.get("attendance_status") or "present", Decimal(1))}
        out[key] = {
            "key": key, "label": g["label"],
            "days": len(worked),
            "man_days": sum((r["man_days"] for r in built), Decimal(0)),
            "unpriced_man_days": sum((r["unpriced_man_days"] for r in built), Decimal(0)),
            "earned": money(sum((r["gross"] + r["overtime_amount"] for r in built), Decimal(0))),
            "trades": ", ".join(sorted({t for r in built for t in (r["trades"] or "").split(", ") if t})),
            **({"to_pay": Decimal(0), "paid": Decimal(0), "owed": Decimal(0), "waiting": Decimal(0)} if by != "trade"
               else {"to_pay": None, "paid": None, "owed": None, "waiting": None}),
        }
    if by != "trade":
        for r in sheet_rows:
            # A sheet made for the whole project (no site) is its own row by site: its pay cannot be split by site.
            site_key = str(r["site_id"]) if r.get("site_id") else f"project:{r.get('project_id')}"
            key = {"project": str(r.get("project_id")), "site": site_key, "payee": r.get("payee_key")}[by]
            row = out.get(key)
            if row is None:  # paid for days outside the period's attendance (a carry-forward): still shown
                row = out[key] = {"key": key, "label": r.get("label") or r.get("payee_name") or "—", "days": 0,
                                  "man_days": Decimal(0), "unpriced_man_days": Decimal(0), "earned": Decimal(0),
                                  "trades": r.get("trades") or "", "to_pay": Decimal(0), "paid": Decimal(0),
                                  "owed": Decimal(0), "waiting": Decimal(0)}
            net, paid = money(r["net"]), money(r["paid"])
            if r["status"] == "approved":
                row["to_pay"] += net
                row["paid"] += paid
                row["owed"] += max(net - paid, Decimal(0))
            else:
                row["waiting"] += net
    return sorted(out.values(), key=lambda r: (-r["earned"], r["label"].lower()))


def statement_text(st: Mapping[str, Any]) -> str:
    """A worker's or team's statement as a WhatsApp message (LW-10), in the payment slip's words."""
    def r(v: Any) -> str:
        return f"₹{money(v):,.0f}"
    out = [f"*{st['payee_name']}*", f"{st['date_from']:%d %b} – {st['date_to']:%d %b %Y}"]
    for w in st["weeks"]:
        unit = "man-days" if Decimal(w["man_days"]) > Decimal(w.get("days") or 0) else "days"  # a team, or one person
        line = f"{w['period_from']:%d %b}–{w['period_to']:%d %b}: {Decimal(w['man_days']).normalize():f} {unit}, {r(w['wages'])}"
        if money(w["advances_recovered"]):
            line += f", advance −{r(w['advances_recovered'])}"
        if money(w["deductions"]):
            line += f", deductions −{r(w['deductions'])}"
        line += f" → {r(w['net'])}" + (" (not approved yet)" if w["status"] != "approved" else
                                         f", paid {r(w['paid'])}" if money(w["paid"]) else ", not paid yet")
        out.append(line)
    t = st["totals"]
    if money(t["advances_given"]):
        out.append(f"Advances given: {r(t['advances_given'])}")
    out.append(f"*Paid: {r(t['paid'])}*")
    if money(t["due"]):
        out.append(f"*Still to pay: {r(t['due'])}*")
    if money(t["advance_outstanding"]):
        out.append(f"Advance still to take back: {r(t['advance_outstanding'])}")
    return "\n".join(out)
