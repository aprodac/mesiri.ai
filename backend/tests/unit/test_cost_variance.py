"""CC-07: green / amber / red per BOQ line (domains/costing/variance.py)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from mesiri.domains.costing.variance import colour_of, line_variance, sort_worst_first, summarise

PLASTER = {"id": uuid.uuid4(), "labour_rate": Decimal("14")}


def _labour(cost: str, man_days: str = "4", unpriced: str = "0") -> dict:
    return {"man_days": Decimal(man_days), "cost": Decimal(cost), "unpriced_man_days": Decimal(unpriced)}


def test_the_gm_example_is_amber_with_the_cost_per_unit():
    # 4 masons put on plastering cost 4,400; 300 sq ft measured earns 300 x 14 = 4,200: 0.95, amber.
    v = line_variance(PLASTER, Decimal("300"), _labour("4400"))
    assert (v["colour"], v["reason"], v["ratio"]) == ("amber", "near_budget", Decimal("0.95"))
    assert v["earned_labour"] == Decimal("4200.00") and v["difference"] == Decimal("-200.00")
    assert v["cost_per_unit"] == Decimal("14.67")


def test_the_thresholds_are_at_one_and_ninety_percent():
    assert colour_of(Decimal("100"), Decimal("100")) == ("green", Decimal("1.00"))
    assert colour_of(Decimal("90"), Decimal("100"))[0] == "amber"
    assert colour_of(Decimal("89"), Decimal("100"))[0] == "red"
    assert colour_of(Decimal("50"), None) == ("grey", None)


def test_labour_with_no_work_measured_is_red_and_says_so():
    v = line_variance(PLASTER, Decimal("0"), _labour("4400"))
    assert (v["colour"], v["reason"], v["difference"]) == ("red", "labour_no_work", Decimal("-4400.00"))


def test_what_cannot_be_judged_is_grey_with_the_reason_never_a_colour():
    assert line_variance({**PLASTER, "labour_rate": None}, Decimal("300"), _labour("4400"))["reason"] == "no_labour_rate"
    assert line_variance(PLASTER, Decimal("300"), None)["reason"] == "no_labour"
    no_wage = line_variance(PLASTER, Decimal("300"), _labour("0", unpriced="4"))
    assert (no_wage["colour"], no_wage["reason"], no_wage["labour_cost"]) == ("grey", "no_wage", None)
    assert line_variance(PLASTER, Decimal("0"), None) is None  # nothing happened: nothing to say


def test_the_summary_adds_only_comparable_lines_and_worst_comes_first():
    red = line_variance({**PLASTER, "id": 1}, Decimal("100"), _labour("4400"))
    green = line_variance({**PLASTER, "id": 2}, Decimal("400"), _labour("4400"))
    grey = line_variance({**PLASTER, "id": 3}, Decimal("50"), None)
    s = summarise([green, grey, red])
    assert s["earned_labour"] == Decimal("7000.00") and s["labour_cost"] == Decimal("8800.00")
    assert s["colour"] == "red" and s["lines"] == {"red": 1, "amber": 0, "green": 1, "grey": 1}
    assert [v["line_id"] for v in sort_worst_first([green, grey, red])] == [1, 2, 3]
    assert summarise([grey])["colour"] == "grey"


def test_quantities_are_never_written_with_an_exponent():
    from mesiri.domains.costing.router import _q, _q3

    assert [_q(Decimal(x)) for x in ("20.00", "2.50", "0", "24")] == ["20", "2.5", "0", "24"]
    assert [_q3(Decimal(x)) for x in ("250", "700.000", "12.125", "100.5")] == ["250", "700", "12.125", "100.5"]


# -- CC-18: committed and forecast ----------------------------------------------------------------------------------


def test_the_forecast_is_the_rate_so_far_applied_to_the_work_left():
    from mesiri.domains.costing.forecast import forecast

    # Plastering labour: 2,52,000 budget, 8,960 earned for 8,800 spent.
    f = forecast(Decimal("252000"), Decimal("8960"), Decimal("8800"))
    assert (f["forecast"], f["forecast_difference"], f["forecast_basis"]) == (
        Decimal("247500.00"), Decimal("4500.00"), "rate_so_far")
    assert forecast(Decimal("1000"), Decimal("1200"), Decimal("900"))["forecast"] == Decimal("900.00")  # all earned
    assert forecast(Decimal("1000"), None, Decimal("500"))["forecast_basis"] == "too_early"
    assert forecast(Decimal("1000"), Decimal("100"), Decimal("0"))["forecast"] is None
    assert forecast(None, Decimal("100"), Decimal("50"))["forecast_basis"] == "no_budget"


def test_committed_is_what_is_ordered_or_agreed_and_not_yet_delivered_or_billed():
    from mesiri.domains.costing.forecast import committed_materials, committed_subcontract

    orders = [
        {"status": "open", "lines": [{"quantity": "100", "received": "40", "rate": "410"},
                                     {"quantity": "10", "received": "10", "rate": "99"},
                                     {"quantity": "5", "received": "0", "rate": None}]},
        {"status": "closed", "lines": [{"quantity": "100", "received": "0", "rate": "1"}]},
    ]
    assert committed_materials(orders) == {"amount": Decimal("24600.00"), "unpriced_lines": 1}
    wos = [{"status": "issued", "totals": {"value": "756000", "billed": "200000"}},
           {"status": "draft", "totals": {"value": "99", "billed": "0"}},
           {"status": "completed", "totals": {"value": "100", "billed": "150"}}]
    assert committed_subcontract(wos) == {"amount": Decimal("556000.00"), "work_orders": 1}


# -- CC-08: material reconciliation ---------------------------------------------------------------------------------


def test_cement_used_beyond_what_the_work_needed_is_red_and_the_shortage_at_completion_is_said():
    from mesiri.domains.costing.materials import reconcile

    cement = "cement-id"
    lines = [{"planned": "18000", "done": "640", "norms": [
        {"material_id": cement, "material": "Cement", "unit": "bags", "per_unit": "0.0045", "wastage_pct": "5"}]}]
    stock = {cement: {"unit": "bags", "received": "60", "used": "4", "on_hand": "56", "on_order": "20"}}
    [row] = reconcile(lines, stock)
    assert (row["required_total"], row["should_have_used"]) == (Decimal("85.05"), Decimal("3.02"))
    assert (row["colour"], row["reason"], row["used_over_work"]) == ("red", "over_norm", Decimal("0.98"))
    # Still needed 82.03; 56 on hand + 20 coming: 6.03 bags short at completion.
    assert row["short_by"] == Decimal("6.03")


def test_materials_never_compared_across_units_or_coloured_without_usage():
    from mesiri.domains.costing.materials import reconcile

    lines = [{"planned": "10", "done": "2", "norms": [
        {"material_id": "m", "material": "Metal", "unit": "cft", "per_unit": "20", "wastage_pct": None}]}]
    [row] = reconcile(lines, {"m": {"unit": "loads", "used": "1"}})
    assert (row["colour"], row["reason"], row["short_by"]) == ("grey", "unit_differs", None)
    [row] = reconcile(lines, {})
    assert (row["colour"], row["reason"]) == ("grey", "no_usage_recorded")
    used_no_work = [{**lines[0], "done": "0"}]
    assert reconcile(used_no_work, {"m": {"unit": "cft", "used": "5"}})[0]["reason"] == "used_no_work"
