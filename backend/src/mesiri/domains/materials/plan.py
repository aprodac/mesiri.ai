"""The material plan (MP-02): what a project needs of each material, week by week, and when it runs short. Pure, no I/O.

Inputs, as plain dicts:

- **lines**: the project's current BOQ lines that have norms (MP-01), each with its activity's dates::

      {"id", "work", "unit", "planned", "done", "start", "end", "finished", "site_id",
       "norms": [{"material_id", "material", "unit", "per_unit", "wastage_pct"}]}

  ``planned`` / ``done`` are in the line's unit (``done`` from CC-04's ``done_by_line``, the Gantt's own count);
  ``start`` / ``end`` are the activity's planned days (inclusive; None when the activity has no dates);
  ``finished`` is the PM's "this activity is finished".
- **stock**: per material id, ``{"unit", "on_hand", "on_order"}`` in the material's stock unit.

The rule, per line and material:

- required = planned × per_unit × (1 + wastage%) — what the whole line takes;
- still needed = max(planned − done, 0) × per_unit × (1 + wastage%), nothing once the activity is finished;
- the still-needed amount is spread evenly over the activity's days still to come: from max(today, start) to end.
  An activity whose end has passed but is not finished is late: it needs the rest now, spread over the next 7 days.
  A line with no dates is *unscheduled*: counted in "still needed", in no week;
- weeks start on Monday; the first week is the one ``today`` is in. Need after the last week is "later";
- available = on hand + on order. The **short day** is the first day whose need, added up from today, is more than
  what is available (``short_from`` is the Monday of its week); ``short_by`` is how much more the weeks shown need
  than what is available;
- **order by** (MP-03) = short day − the lead time of the supplier who last delivered it (``stock[...]["lead_days"]``,
  ``DEFAULT_LEAD_DAYS`` when unknown). ``order_now`` when that day is today or has passed.

Units are never converted: a norm is in the material's stock unit (MP-01). A stock row in another unit is not counted
(``stock_unit_differs``), so a wrong unit shows up instead of a wrong number.

Worked example: "M20 in slab", 30 m³ planned, 10 done, 8 bags cement per m³ with 5% wastage, 11-24 Nov (14 days).
On Tue 10 Nov: still needed 20 × 8 × 1.05 = 168 bags, 12 bags a day; week of 9 Nov: 11-15 Nov, 5 days = 60 bags;
week of 16 Nov: 7 days = 84; week of 23 Nov: 2 days = 24. With 100 bags in stock and none ordered, cumulative need
60, 144: short in the week of 16 Nov, on Thu 19 Nov (the 9th day of work takes the total to 108), short by 68
bags (168 − 100). With a 3-day lead time: order by Mon 16 Nov.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

DAY = datetime.timedelta(days=1)
#: A late activity (end passed, not finished) needs the rest within this many days.
LATE_SPREAD_DAYS = 7
#: Days from order to delivery when the supplier's lead time is not known (D-MP2).
DEFAULT_LEAD_DAYS = 3
_ZERO = Decimal(0)
_Q = Decimal("0.001")


def week_starts(today: datetime.date, weeks: int) -> list[datetime.date]:
    """The Mondays of the ``weeks`` weeks shown, starting with ``today``'s week."""
    monday = today - datetime.timedelta(days=today.weekday())
    return [monday + datetime.timedelta(weeks=i) for i in range(weeks)]


def _days(line: Mapping[str, Any], today: datetime.date) -> list[datetime.date] | None:
    """The days the line's remaining work is spread over, or None when it has no dates."""
    start, end = line.get("start"), line.get("end")
    if start is None or end is None:
        return None
    if end < today:
        first, last = today, today + (LATE_SPREAD_DAYS - 1) * DAY
    else:
        first, last = max(today, start), end
    return [first + i * DAY for i in range((last - first).days + 1)]


def _q(value: Decimal) -> Decimal:
    return value.quantize(_Q)


def build(
    lines: Iterable[Mapping[str, Any]],
    stock: Mapping[Any, Mapping[str, Any]],
    today: datetime.date,
    weeks: int = 8,
) -> dict[str, Any]:
    """The plan: the weeks shown and one row per material (worst first: short soonest, then by name)."""
    starts = week_starts(today, weeks)
    horizon_end = starts[-1] + 6 * DAY
    rows: dict[Any, dict[str, Any]] = {}
    for line in lines:
        planned = Decimal(line["planned"])
        remaining = _ZERO if line.get("finished") else max(planned - Decimal(line.get("done") or 0), _ZERO)
        days = _days(line, today) if remaining > 0 else []
        for norm in line.get("norms") or []:
            factor = Decimal(norm["per_unit"]) * (1 + Decimal(norm.get("wastage_pct") or 0) / 100)
            row = rows.setdefault(norm["material_id"], {
                "material_id": norm["material_id"], "material": norm["material"], "unit": norm["unit"],
                "required": _ZERO, "still_needed": _ZERO, "unscheduled": _ZERO, "later": _ZERO,
                "weeks": [_ZERO] * weeks, "lines": [], "_days": defaultdict(lambda: _ZERO),
            })
            need = remaining * factor
            row["required"] += planned * factor
            row["still_needed"] += need
            if need > 0:
                row["lines"].append({"line_id": line["id"], "work": line["work"], "need": _q(need),
                                     "site_id": line.get("site_id"),
                                     "start": line.get("start"), "end": line.get("end"),
                                     "late": days is not None and line.get("end") is not None and line["end"] < today})
            if need == 0:
                continue
            if days is None:
                row["unscheduled"] += need
                continue
            per_day = need / len(days)
            by_week: dict[int, Decimal] = defaultdict(lambda: _ZERO)
            for d in days:
                if d > horizon_end:
                    row["later"] += per_day
                else:
                    by_week[(d - starts[0]).days // 7] += per_day
                    row["_days"][d] += per_day
            for i, amount in by_week.items():
                row["weeks"][i] += amount

    out = []
    for material_id, row in rows.items():
        held = stock.get(material_id) or {}
        same_unit = not held or held.get("unit") in (None, row["unit"])
        on_hand = Decimal(held.get("on_hand") or 0) if same_unit else _ZERO
        on_order = Decimal(held.get("on_order") or 0) if same_unit else _ZERO
        available = on_hand + on_order
        daily = row.pop("_days")
        cumulative, short_day = _ZERO, None
        for d in sorted(daily):
            cumulative += daily[d]
            if short_day is None and daily[d] > 0 and _q(cumulative) > available:
                short_day = d
        lead = held.get("lead_days")
        lead = DEFAULT_LEAD_DAYS if lead is None else int(lead)
        order_by = short_day - lead * DAY if short_day is not None else None
        out.append({
            **row,
            "required": _q(row["required"]), "still_needed": _q(row["still_needed"]),
            "unscheduled": _q(row["unscheduled"]), "later": _q(row["later"]),
            "weeks": [_q(w) for w in row["weeks"]],
            "on_hand": _q(on_hand), "on_order": _q(on_order),
            "stock_unit_differs": not same_unit,
            "short_day": short_day,
            "short_from": short_day - datetime.timedelta(days=short_day.weekday()) if short_day else None,
            "short_by": _q(cumulative - available) if _q(cumulative) > available else _ZERO,
            "supplier": held.get("supplier"), "lead_days": lead, "lead_known": held.get("lead_days") is not None,
            "order_by": order_by, "order_now": order_by is not None and order_by <= today,
        })
    out.sort(key=lambda r: (r["order_by"] is None, r["order_by"] or today, r["material"].lower()))
    return {"weeks": starts, "materials": out}
