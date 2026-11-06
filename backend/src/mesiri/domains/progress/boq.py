"""A project's Bill of Quantities (CC-02): the money on each line. Pure, no I/O.

A BOQ line is a ``work_package_planned_items`` row: what (``work_type``), unit, planned
quantity, and up to four rates per unit (0508):

- ``client_rate``: what the client pays per unit. quantity x client_rate = contract value.
- ``labour_rate`` + ``material_rate`` + ``subcontract_rate``: the internal budget per unit.
  quantity x their sum = budget cost.
- margin = contract value - budget cost.

A rate left empty is "not priced", never zero: a line with no client rate has no contract
value, and a line with no budget rate at all has no budget cost. Totals add only the
lines that have the figure and say how many lines are missing it, so a half-priced BOQ
never shows a margin that looks real.

Worked example (the GM meeting, 6 Nov 2026): plastering 18,000 sq ft at ₹42 to the
client, budget ₹14 labour + ₹22 material = ₹36 per sq ft:
contract value ₹7,56,000, budget cost ₹6,48,000, margin ₹1,08,000.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

BUDGET_RATES = ("labour_rate", "material_rate", "subcontract_rate")
_CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def budget_rate(line: Mapping[str, Any]) -> Decimal | None:
    """The budget cost per unit: the sum of the budget rates given; None when none is."""
    rates = [Decimal(line[k]) for k in BUDGET_RATES if line.get(k) is not None]
    return sum(rates, Decimal(0)) if rates else None


def line_amounts(line: Mapping[str, Any]) -> dict[str, Decimal | None]:
    """Contract value, budget cost and margin of one line (None where a rate is missing)."""
    quantity = Decimal(line["planned_quantity"])
    client = line.get("client_rate")
    contract_value = _money(quantity * Decimal(client)) if client is not None else None
    per_unit = budget_rate(line)
    budget_cost = _money(quantity * per_unit) if per_unit is not None else None
    margin = (
        contract_value - budget_cost if contract_value is not None and budget_cost is not None else None
    )
    return {
        "budget_rate": per_unit,
        "contract_value": contract_value,
        "budget_cost": budget_cost,
        "margin": margin,
    }


def totals(lines: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Totals over lines that already carry ``line_amounts``.

    ``margin`` is only given when every line has both a contract value and a budget cost;
    otherwise the missing counts say why it is absent.
    """
    lines = list(lines)
    contract = [ln["contract_value"] for ln in lines if ln["contract_value"] is not None]
    budget = [ln["budget_cost"] for ln in lines if ln["budget_cost"] is not None]
    missing_client = len(lines) - len(contract)
    missing_budget = len(lines) - len(budget)
    contract_value = sum(contract, Decimal(0)) if contract else None
    budget_cost = sum(budget, Decimal(0)) if budget else None
    complete = lines and missing_client == 0 and missing_budget == 0
    return {
        "line_count": len(lines),
        "contract_value": contract_value,
        "budget_cost": budget_cost,
        "margin": contract_value - budget_cost if complete else None,
        "lines_without_client_rate": missing_client,
        "lines_without_budget_rate": missing_budget,
    }
