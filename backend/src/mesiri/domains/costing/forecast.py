"""Committed cost and the forecast at completion (CC-18). Pure, no I/O.

**Committed** is money promised but not spent yet, so it shows what is coming before the bill does:

- materials: on open purchase orders, what has not been delivered yet (ordered - received) x the order's rate;
  a line with no rate is counted, not valued (``unpriced_lines``);
- subcontract: on issued or completed work orders, the agreed value not billed yet.

Labour has no commitment (it is paid as it is worked).

**Forecast at completion** for a kind (labour, materials, subcontract): what was spent, plus the budget of the
work still to do at the rate the work has cost so far: ``actual + (budget - earned) x actual / earned``. It needs
some work earned and some money spent; without them there is no basis and it is None, never a guess. When the work
earned has reached the budget, the forecast is what was spent.

Worked example: plastering labour budget ₹2,52,000 (18,000 sq ft at ₹14). 640 sq ft done earned ₹8,960 for ₹8,800
spent: forecast ₹8,800 + ₹2,43,040 x 8,800 / 8,960 = ₹2,47,500, ₹4,500 under the budget.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

_CENT = Decimal("0.01")
_ZERO = Decimal(0)
#: Work orders whose agreed value is a commitment (a draft is not yet given; closed and cancelled are over).
COMMITTED_WORK_ORDERS = ("issued", "completed")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def committed_materials(orders: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Open purchase orders' value still to come; lines with no rate are counted apart."""
    amount, unpriced = _ZERO, 0
    for order in orders:
        if order["status"] != "open":
            continue
        for line in order["lines"]:
            left = Decimal(line["quantity"]) - Decimal(line["received"])
            if left <= 0:
                continue
            if line.get("rate") is None:
                unpriced += 1
            else:
                amount += left * Decimal(line["rate"])
    return {"amount": _money(amount), "unpriced_lines": unpriced}


def committed_subcontract(work_orders: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Issued and completed work orders' agreed value not billed yet."""
    amount, count = _ZERO, 0
    for wo in work_orders:
        if wo["status"] not in COMMITTED_WORK_ORDERS:
            continue
        left = Decimal(wo["totals"]["value"]) - Decimal(wo["totals"]["billed"])
        if left > 0:
            amount += left
            count += 1
    return {"amount": _money(amount), "work_orders": count}


def forecast(budget: Decimal | None, earned: Decimal | None, actual: Decimal) -> dict[str, Any]:
    """Forecast at completion and the gap to the budget (below zero: over), or None with the reason."""
    if budget is None:
        return {"forecast": None, "forecast_difference": None, "forecast_basis": "no_budget"}
    if not earned or earned <= 0 or actual <= 0:
        return {"forecast": None, "forecast_difference": None, "forecast_basis": "too_early"}
    left = max(budget - earned, _ZERO)
    at_completion = _money(actual + left * actual / earned)
    return {"forecast": at_completion, "forecast_difference": _money(budget - at_completion),
            "forecast_basis": "rate_so_far"}
