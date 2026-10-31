"""Request 164: local unit words, amounts kept, loss sheet, severity from value."""

from __future__ import annotations

from decimal import Decimal

import pytest

from runtime.agent import amount_check
from runtime.agent import draft as dr
from runtime.agent.draft_answer import amount_answer
from runtime.agent.tools import wage_per_person
from runtime.loss_rules import loss_line, severity_for_value
from runtime.unit_words import canonical_unit


@pytest.mark.parametrize(
    "word,unit",
    [("chaakku", "bags"), ("Chaak", "bags"), ("ചാക്ക്", "bags"), ("lod", "load"), ("adi", "ft"),
     ("അടി", "ft"), ("kilo", "kg"), ("ennam", "nos"), ("എണ്ണം", "nos"), ("tonne", "tons")],
)
def test_local_unit_words_resolve(word, unit):
    assert canonical_unit(word) == unit


def test_unknown_word_is_not_a_unit():
    assert canonical_unit("rod") is None


def test_typed_unit_answer_uses_the_same_table():
    assert amount_answer("100 ചാക്ക്", {"unit": "chaakku", "quantity": 100}, "bags") == Decimal(100)
    assert amount_answer("oru rod 12 kg", {"unit": "rod", "quantity": 20}, "kg") == Decimal(240)


def test_said_amounts_need_a_currency_cue():
    text = "Tower 2 2nd floor 31 Oct, 100 bag cement-inu motham ₹10000 aayi"
    assert amount_check.said_amounts(text) == [Decimal(10000)]
    assert amount_check.said_amounts("Rs. 1,500 and 300 rupees") == [Decimal(1500), Decimal(300)]
    assert amount_check.said_amounts("Tower 2, 2nd floor, 30 workers") == []


def test_unkept_amount_is_found_and_kept_one_is_not():
    said = "30 per vannu, motham kooli ₹3000"
    assert amount_check.unkept(said, {"workers": [{"headcount": 30}]}) == [Decimal(3000)]
    assert amount_check.unkept(said, {"workers": [{"headcount": 30, "daily_wage": 100}]}) == []
    assert amount_check.unkept("₹10000 cement", {"total_cost": 10000}) == []


def _item(kind, tool, args, said, **kw):
    return dr.DraftItem(kind=kind, tool=tool, args=args, summary="Cement in: 100 bags", said=said, **kw)


def test_card_shows_not_kept_and_guard_unchanged_card_is_silent():
    said = "100 bag cement vannu, motham ₹10000 aayi"
    draft = dr.MessageDraft.new(organization_id="o", user_id="u")
    draft.items.append(_item(dr.KIND_MATERIAL_IN, "save_material_receipt", {"material": "Cement", "quantity": 100}, said))
    assert "Not kept: ₹10000 (cost of cement?)" in dr.card_text(draft)
    draft.items[0].args["total_cost"] = 10000
    assert "Not kept" not in dr.card_text(draft)


def test_total_wage_becomes_each_persons_wage():
    out = wage_per_person([{"trade": "helper", "headcount": 30, "total_wage": 3000}])
    assert out == [{"trade": "helper", "headcount": 30, "daily_wage": 100}]
    each = wage_per_person([{"headcount": 5, "daily_wage": 500}])
    assert each == [{"headcount": 5, "daily_wage": 500}]


def test_severity_comes_from_value_and_never_lowers():
    assert severity_for_value(8000, "LOW") == "HIGH"
    assert severity_for_value(500, "LOW") == "LOW"
    assert severity_for_value(2000, "") == "MEDIUM"
    assert severity_for_value(8000, "CRITICAL") == "CRITICAL"


def test_loss_line():
    fmt = lambda v: f"{v:g}"  # noqa: E731
    assert loss_line("cement", "bags", 100, 20, 100, fmt) == "Cement: 100 bags in · 20 used · 80 wasted · ₹100/bag · ₹8000 loss"
    assert "no cost recorded" in loss_line("sand", "load", 10, 2, None, fmt)
