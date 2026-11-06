"""CC-02: the money on a BOQ line and the totals. Worked examples from the 6 Nov GM meeting."""

from __future__ import annotations

from decimal import Decimal

from mesiri.domains.progress.boq import budget_rate, line_amounts, totals


def _line(qty, client=None, labour=None, material=None, sub=None) -> dict:
    return {
        "planned_quantity": Decimal(qty),
        "client_rate": None if client is None else Decimal(client),
        "labour_rate": None if labour is None else Decimal(labour),
        "material_rate": None if material is None else Decimal(material),
        "subcontract_rate": None if sub is None else Decimal(sub),
    }


def test_plastering_line_contract_budget_and_margin():
    # 18,000 sq ft at ₹42 to the client; budget ₹14 labour + ₹22 material.
    amounts = line_amounts(_line("18000", client="42", labour="14", material="22"))
    assert amounts["budget_rate"] == Decimal("36")
    assert amounts["contract_value"] == Decimal("756000.00")
    assert amounts["budget_cost"] == Decimal("648000.00")
    assert amounts["margin"] == Decimal("108000.00")


def test_subcontract_rate_alone_is_a_budget():
    # Plastering given out at ₹14 / sq ft: the subcontract rate is the whole budget.
    amounts = line_amounts(_line("1000", sub="14"))
    assert amounts["budget_cost"] == Decimal("14000.00")
    assert amounts["contract_value"] is None
    assert amounts["margin"] is None


def test_missing_rate_is_not_priced_never_zero():
    amounts = line_amounts(_line("20"))
    assert budget_rate(_line("20")) is None
    assert amounts == {"budget_rate": None, "contract_value": None, "budget_cost": None, "margin": None}
    # A zero rate is a real price of zero, not "not priced".
    assert line_amounts(_line("20", labour="0"))["budget_cost"] == Decimal("0.00")


def test_fractional_quantity_rounds_to_paise():
    # 20.125 m³ of M20 at ₹6,212.50: 125,026.5625 -> 125,026.56
    assert line_amounts(_line("20.125", client="6212.50"))["contract_value"] == Decimal("125026.56")


def test_totals_margin_only_when_every_line_is_priced():
    priced = {**_line("10", client="100", labour="80"), **line_amounts(_line("10", client="100", labour="80"))}
    half = {**_line("5", client="50"), **line_amounts(_line("5", client="50"))}
    complete = totals([priced])
    assert complete["margin"] == Decimal("200.00")
    partial = totals([priced, half])
    assert partial["contract_value"] == Decimal("1250.00")
    assert partial["budget_cost"] == Decimal("800.00")
    assert partial["margin"] is None
    assert partial["lines_without_budget_rate"] == 1
    assert partial["lines_without_client_rate"] == 0


def test_totals_of_nothing():
    empty = totals([])
    assert empty["line_count"] == 0
    assert empty["contract_value"] is None and empty["budget_cost"] is None and empty["margin"] is None
