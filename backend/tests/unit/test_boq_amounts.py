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


def test_a_half_priced_boq_gives_the_margin_of_its_priced_lines_only():
    """20 Nov test: the unpriced line's ₹250 of contract value is never counted as margin."""
    priced = {**_line("10", client="100", labour="80"), **line_amounts(_line("10", client="100", labour="80"))}
    half = {**_line("5", client="50"), **line_amounts(_line("5", client="50"))}
    partial = totals([priced, half])
    assert partial["margin"] is None  # the full margin still waits for every line
    assert partial["margin_priced"] == Decimal("200.00")
    assert partial["priced_contract_value"] == Decimal("1000.00")
    assert totals([half])["margin_priced"] is None


def test_totals_of_nothing():
    empty = totals([])
    assert empty["line_count"] == 0
    assert empty["contract_value"] is None and empty["budget_cost"] is None and empty["margin"] is None


# -- CC-04: work done against a line --------------------------------------------------------------

from mesiri.domains.progress.boq import line_progress, suggest_line  # noqa: E402


def test_concrete_line_done_left_and_earned_by_kind():
    # M20 concrete, 100 m³, budget ₹1,500 labour + ₹3,500 material; 8 m³ poured.
    p = line_progress(_line("100", labour="1500", material="3500"), Decimal("8"))
    assert p["remaining_quantity"] == Decimal("92")
    assert p["percent_done"] == Decimal("8.0")
    assert p["earned_labour"] == Decimal("12000.00")
    assert p["earned_material"] == Decimal("28000.00")
    assert p["earned_subcontract"] is None
    assert p["earned"] == Decimal("40000.00")
    assert p["over_planned"] is False


def test_unpriced_line_earns_nothing_not_zero():
    p = line_progress(_line("100"), Decimal("8"))
    assert p["earned"] is None and p["earned_labour"] is None


def test_more_done_than_planned_is_said_not_hidden():
    p = line_progress(_line("10", labour="100"), Decimal("12"))
    assert p["over_planned"] is True
    assert p["remaining_quantity"] == Decimal("0")
    assert p["earned"] == Decimal("1200.00")


def test_totals_add_earned_only_when_lines_carry_it():
    a = {**line_amounts(_line("100", labour="10")), **line_progress(_line("100", labour="10"), Decimal("5"))}
    b = {**line_amounts(_line("50")), **line_progress(_line("50"), Decimal("5"))}
    assert totals([a, b])["earned"] == Decimal("50.00")
    assert "earned" not in totals([line_amounts(_line("100", labour="10"))])


_SQFT, _CUM = "u-sqft", "u-cum"


def _boq_line(id_, work, unit, section="s1"):
    return {"id": id_, "work_type": work, "unit_id": unit, "work_package_id": section}


def test_suggestion_is_the_same_unit_line_sharing_most_words():
    lines = [
        _boq_line("plaster-int", "Internal plastering 12 mm", _SQFT),
        _boq_line("plaster-ext", "External plastering 20 mm", _SQFT),
        _boq_line("concrete", "M20 concrete in columns", _CUM),
    ]
    assert suggest_line("internal plastering first floor", _SQFT, "s1", lines) == "plaster-int"
    assert suggest_line("M20 concrete slab", _CUM, "s1", lines) == "concrete"


def test_no_suggestion_across_units_or_on_a_tie_or_no_shared_word():
    lines = [
        _boq_line("a", "Plastering ceiling", _SQFT, "s1"),
        _boq_line("b", "Plastering walls", _SQFT, "s1"),
    ]
    assert suggest_line("plastering", _CUM, "s1", lines) is None  # another unit: never
    assert suggest_line("plastering", _SQFT, "s1", lines) is None  # tie: never a guess
    assert suggest_line("brickwork", _SQFT, "s1", lines) is None


def test_the_activitys_own_section_breaks_a_tie():
    lines = [_boq_line("gf", "Plastering", _SQFT, "ground"), _boq_line("ff", "Plastering", _SQFT, "first")]
    assert suggest_line("plastering", _SQFT, "first", lines) == "ff"


# -- BOQ-01: the lines offered for one tap when no line is clear ------------------------------------------------------

from mesiri.domains.progress.boq import line_choices  # noqa: E402


def test_choices_on_a_tie_are_the_tied_lines_own_section_first():
    lines = [
        _boq_line("a", "Plastering ceiling", _SQFT, "s1"),
        _boq_line("b", "Plastering walls", _SQFT, "s2"),
        _boq_line("d", "Plastering beams", _SQFT, "s2"),
        _boq_line("c", "M20 concrete", _CUM, "s2"),
    ]
    assert suggest_line("plastering", _SQFT, "s2", lines) is None  # b and d tie in the section: no guess
    assert line_choices("plastering", _SQFT, "s2", lines) == ["b", "d", "a"]


def test_choices_never_cross_units_and_most_words_come_first():
    lines = [
        _boq_line("w", "Plastering walls internal", _SQFT, "s1"),
        _boq_line("c", "Plastering ceiling", _SQFT, "s1"),
        _boq_line("x", "Plastering walls internal", _CUM, "s1"),
    ]
    assert line_choices("internal walls plastering", _SQFT, "s1", lines)[0] == "w"
    assert "x" not in line_choices("internal walls plastering", _SQFT, "s1", lines)


def test_no_shared_word_offers_a_short_boq_whole_but_never_a_long_list():
    short = [_boq_line("a", "Brickwork", _SQFT, "s1"), _boq_line("b", "Tiling", _SQFT, "s1")]
    assert sorted(line_choices("finishing", _SQFT, "s1", short)) == ["a", "b"]
    long = [_boq_line(str(i), f"Item {i}", _SQFT, "s1") for i in range(5)]
    assert line_choices("finishing", _SQFT, "s1", long) == []
    assert line_choices("anything", _CUM, "s1", short) == []  # nothing in the unit: nothing offered


def test_choices_stop_at_three():
    lines = [_boq_line(str(i), f"Plastering {i}", _SQFT, "s1") for i in range(6)]
    assert len(line_choices("plastering", _SQFT, "s1", lines)) == 3


# -- BOQ-01b: filler words never decide the line ----------------------------------------------------------------------


def test_filler_words_never_decide_the_line():
    lines = [_boq_line("slab", "Shuttering for slab", _SQFT, "s1"), _boq_line("col", "Shuttering to columns", _SQFT, "s1")]
    assert suggest_line("Shuttering for column", _SQFT, "s1", lines) is None  # "for" no longer tips it to the slab
    assert suggest_line("shuttering slab done", _SQFT, "s1", lines) == "slab"  # the place word still decides


def test_guard_a_number_or_grade_still_counts():
    lines = [_boq_line("m20", "M20 concrete", _CUM, "s1"), _boq_line("m25", "M25 concrete", _CUM, "s1")]
    assert suggest_line("m25 concrete done", _CUM, "s1", lines) == "m25"
