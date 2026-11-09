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
