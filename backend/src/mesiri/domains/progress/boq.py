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
    progress = {}
    if any("earned" in ln for ln in lines):  # CC-04: lines that carry the work done
        earned = [ln["earned"] for ln in lines if ln.get("earned") is not None]
        progress = {"earned": sum(earned, Decimal(0)) if earned else None}
    return {
        **progress,
        "line_count": len(lines),
        "contract_value": contract_value,
        "budget_cost": budget_cost,
        "margin": contract_value - budget_cost if complete else None,
        "lines_without_client_rate": missing_client,
        "lines_without_budget_rate": missing_budget,
    }


# -- CC-04: the work done against a line ----------------------------------------------------------


def line_progress(line: Mapping[str, Any], done: Decimal) -> dict[str, Any]:
    """Done, left and earned on one line, given the quantity done in the line's own unit.

    Earned is the budget the work done has *earned*: done x each budget rate, kept apart
    (labour, material, subcontract), so a day's labour can be compared with the labour it
    earned (the GM's "₹6,400 of labour: was the work done?"). A rate not given earns None,
    never zero. Done can pass the planned quantity: that is said (``over_planned``), not hidden.

    Worked example: M20 concrete, 100 m³ planned, budget ₹1,500 labour + ₹3,500 material per
    m³; 8 m³ done -> 92 left, 8% done, earned ₹12,000 labour + ₹28,000 material = ₹40,000.
    """
    planned = Decimal(line["planned_quantity"])
    earned = {
        k.removesuffix("_rate"): _money(done * Decimal(line[k])) if line.get(k) is not None else None
        for k in BUDGET_RATES
    }
    given = [v for v in earned.values() if v is not None]
    return {
        "done_quantity": done,
        "remaining_quantity": max(planned - done, Decimal(0)),
        "percent_done": (done * 100 / planned).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) if planned else None,
        "over_planned": done > planned,
        "earned_labour": earned["labour"],
        "earned_material": earned["material"],
        "earned_subcontract": earned["subcontract"],
        "earned": sum(given, Decimal(0)) if given else None,
    }


def _words(value: str | None) -> set[str]:
    cleaned = "".join(ch if ch.isalnum() else " " for ch in (value or "").lower())
    return {w for w in cleaned.split() if len(w) > 2 or any(ch.isdigit() for ch in w)}


def suggest_line(
    work: str | None, unit_id: Any, section_id: Any, lines: Iterable[Mapping[str, Any]], *, any_unit: bool = False
) -> Any | None:
    """The BOQ line a site's work update most likely belongs to, for a person to confirm.

    Only lines in the same unit are candidates (a quantity is never counted in another unit);
    the one sharing the most words with the work wins, a line in the activity's own section
    first. None when nothing shares a word or two lines tie: a guess is never made.
    ``any_unit``: for labour (CC-05), which is man-days on any line, so every unit is a candidate.
    """
    said = _words(work)
    scored = []
    for line in lines:
        if not any_unit and line["unit_id"] != unit_id:
            continue
        shared = len(said & _words(line["work_type"]))
        if shared:
            scored.append((shared, line["work_package_id"] == section_id, line["id"]))
    if not scored:
        return None
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    if len(scored) > 1 and scored[0][:2] == scored[1][:2]:
        return None
    return scored[0][2]
