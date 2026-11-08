"""Green / amber / red per BOQ line (CC-07). Pure, no I/O.

For a period (a day, a week, the project so far) and each BOQ line that had work or labour in it: the labour
budget the work done earned (done x the line's labour rate) against the labour put on the line (CC-05). The ratio
earned / cost is the colour:

- **green**: earned at least what it cost (ratio >= 1.00);
- **amber**: within 10% of it (0.90 <= ratio < 1.00);
- **red**: less than 90%, or labour on the line and no work measured in the period.

Thresholds are decision D-CC6's default (a per-company setting is later, it is a shared settings change).

A line that cannot be judged is never coloured as if it could: no labour rate (``no_labour_rate``), work measured
but no labour put on the line (``no_labour``), or labour with no wage (``no_wage``) are grey, with the reason.
Materials are not coloured per line yet: what each line used comes with the consumption register (CC-08).

Worked example (the GM meeting): plastering, budget ₹14 of labour per sq ft. One day 4 masons put on it cost
₹4,400 and 300 sq ft was measured: earned ₹4,200, ratio 0.95, amber, ₹200 over, ₹14.67 per sq ft against ₹14.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

GREEN_AT = Decimal("1.00")
AMBER_AT = Decimal("0.90")
_CENT = Decimal("0.01")
_ZERO = Decimal(0)

#: Worst first: the order a list of lines is shown in.
COLOUR_ORDER = {"red": 0, "amber": 1, "green": 2, "grey": 3}


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def colour_of(earned: Decimal | None, cost: Decimal | None) -> tuple[str, Decimal | None]:
    """The colour and the ratio earned / cost; grey (ratio None) when the two cannot be compared."""
    if earned is None or cost is None or cost <= 0:
        return "grey", None
    ratio = (earned / cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if ratio >= GREEN_AT:
        return "green", ratio
    if ratio >= AMBER_AT:
        return "amber", ratio
    return "red", ratio


def line_variance(line: Mapping[str, Any], done: Decimal, labour: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """One line over a period: done, labour earned, labour cost, the colour and why. None when the line had
    neither work nor labour in the period (nothing to say).

    ``line``: id, labour_rate (None: not priced). ``done``: quantity in the line's unit in the period.
    ``labour``: man_days, cost, unpriced_man_days put on the line in the period (CC-05), or None.
    """
    man_days = Decimal(labour["man_days"]) if labour else _ZERO
    if done <= 0 and man_days <= 0:
        return None
    unpriced = Decimal(labour["unpriced_man_days"]) if labour else _ZERO
    rate = Decimal(line["labour_rate"]) if line.get("labour_rate") is not None else None
    earned = _money(done * rate) if rate is not None else None
    cost = _money(Decimal(labour["cost"])) if labour and man_days > unpriced else None

    if rate is None:
        colour, ratio, reason = "grey", None, "no_labour_rate"
    elif man_days <= 0:
        colour, ratio, reason = "grey", None, "no_labour"
    elif cost is None:
        colour, ratio, reason = "grey", None, "no_wage"
    elif done <= 0:
        colour, ratio, reason = "red", _ZERO, "labour_no_work"
    else:
        colour, ratio = colour_of(earned, cost)
        reason = {"green": "within_budget", "amber": "near_budget", "red": "over_budget"}[colour]
    return {
        "line_id": line["id"],
        "done_quantity": done,
        "labour_man_days": man_days,
        "labour_unpriced_man_days": unpriced,
        "labour_rate": rate,
        "earned_labour": earned,
        "labour_cost": cost,
        "difference": earned - cost if earned is not None and cost is not None else None,
        "cost_per_unit": _money(cost / done) if cost is not None and done > 0 else None,
        "ratio": ratio,
        "colour": colour,
        "reason": reason,
    }


def summarise(lines: list[dict[str, Any]]) -> dict[str, Any]:
    """A period's lines in one figure: earned and cost over the lines that can be compared, its colour, and how
    many lines are each colour. Grey lines are counted, never added in."""
    comparable = [ln for ln in lines if ln["colour"] != "grey"]
    earned = sum((ln["earned_labour"] for ln in comparable), _ZERO)
    cost = sum((ln["labour_cost"] for ln in comparable), _ZERO)
    colour, ratio = colour_of(earned, cost) if comparable else ("grey", None)
    counts = {c: 0 for c in COLOUR_ORDER}
    for ln in lines:
        counts[ln["colour"]] += 1
    return {
        "earned_labour": earned if comparable else None,
        "labour_cost": cost if comparable else None,
        "difference": earned - cost if comparable else None,
        "ratio": ratio,
        "colour": colour,
        "lines": counts,
    }


def sort_worst_first(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Red first, then amber, green, grey; within a colour the biggest overspend first."""
    return sorted(lines, key=lambda ln: (COLOUR_ORDER[ln["colour"]], ln["difference"] if ln["difference"] is not None else _ZERO))
