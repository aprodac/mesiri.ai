"""CC-11: the evening cost card's words (domains/costing/reminders.py)."""

from __future__ import annotations

import datetime

from mesiri.domains.costing.reminders import _past_cutoff, _rs, card_message

DAY = datetime.date(2026, 11, 7)


def _line(work, colour, reason, **kw):
    base = {"work": work, "unit": "cum", "colour": colour, "reason": reason, "done_quantity": "0", "labour_cost": None,
            "cost_per_unit": None, "labour_rate": None}
    return {**base, **kw}


def _variance(lines, summary=None, left="0"):
    return {"lines": lines, "summary": summary or {"colour": "red", "earned_labour": "4680.00", "labour_cost": "8800.00",
                                                   "difference": "-4120.00"},
            "labour": {"not_on_a_line": {"cost": left, "man_days": "2"}}}


def test_the_card_names_the_colour_the_worst_lines_and_the_labour_on_no_line():
    v = _variance([
        _line("Brickwork 230mm", "red", "over_budget", done_quantity="2.6", labour_cost="8800.00",
              cost_per_unit="3384.62", labour_rate="1800.00"),
        _line("M20 slab", "grey", "no_labour_rate"),
    ], left="2000.00")
    card = card_message("Villa Kakkanad", DAY, v, [])
    assert card.splitlines()[0] == "🚦 *Villa Kakkanad*: today's cost (Sat 7 Nov)"
    assert "🔴 *Red*: ₹4,680 of work earned for ₹8,800 of labour, ₹4,120 over." in card
    assert "• 🔴 Brickwork 230mm: ₹8,800 of labour for 2.6 cum (₹3,385/cum, budget ₹1,800)" in card
    assert "• ⚪ M20 slab: no labour rate in the BOQ" in card
    assert "Labour not on a BOQ line: ₹2,000 (2 man-days)" in card


def test_nothing_measured_and_no_labour_on_a_line_sends_nothing():
    assert card_message("Villa", DAY, _variance([]), []) is None


def test_only_grey_lines_say_there_is_nothing_to_colour_never_a_colour():
    v = _variance([_line("Plastering", "grey", "no_labour", done_quantity="300", unit="sqft")],
                  summary={"colour": "grey", "earned_labour": None, "labour_cost": None, "difference": None})
    card = card_message("Villa", DAY, v, [])
    assert "Nothing to colour yet" in card and "🔴" not in card and "🟢" not in card


def test_several_sites_get_one_colour_each_and_rupees_are_indian():
    a, b = _variance([_line("x", "red", "labour_no_work", labour_cost="100")]), _variance([])
    a2 = {**a, "summary": {**a["summary"], "colour": "green"}}
    card = card_message("Villa", DAY, a, [("Block A", a2), ("Block B", a)])
    assert "Sites: Block A 🟢, Block B 🔴" in card
    assert _rs("1234567") == "₹12,34,567" and _rs("-950") == "-₹950"


def test_the_card_waits_for_the_project_cut_off_in_its_zone():
    at = datetime.datetime(2026, 11, 7, 12, 0, tzinfo=datetime.UTC)  # 17:30 in India
    assert not _past_cutoff("18:00", "Asia/Kolkata", at)
    assert _past_cutoff("18:00", "Asia/Kolkata", at + datetime.timedelta(hours=1))
    assert _past_cutoff(None, "Asia/Kolkata", at + datetime.timedelta(hours=1))  # 18:00 when unset
