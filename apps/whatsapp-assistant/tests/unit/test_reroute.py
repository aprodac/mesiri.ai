"""runtime/agent/reroute.py: the one place where the code makes the call it knows
is right instead of the model's (live 29 Oct). A new case is a new entry in RULES."""

from __future__ import annotations

import pytest

from runtime.agent import reroute


def test_every_rule_has_its_own_name_and_a_fallback_for_the_model():
    names = [r.name for r in reroute.RULES]
    assert len(names) == len(set(names))
    assert all(r.instruction and r.reason for r in reroute.RULES)


@pytest.mark.parametrize(
    "text,said",
    [
        ("nale 50 bag cement order cheyyanam", {"material": "cement", "quantity": 50, "unit": "bag"}),
        ("cement vannu 50 bag", {"material": "cement", "quantity": 50, "unit": "bag"}),
        ("100 bags cement arrived", {"material": "cement", "quantity": 100, "unit": "bags"}),
        ("cement vannu", None),  # no figure
        ("50 bag cement, 20 bag sand", None),  # two of each: not guessed
    ],
)
def test_the_material_their_words_give(text, said):
    got = reroute.said_material(text)
    assert (got and {**got, "material": got["material"].lower()}) == said


def test_a_used_save_for_arrived_material_becomes_the_receipt_with_the_same_figures():
    args = {"material": "cement", "quantity": 50, "unit": "bags"}
    made = reroute.before("save_material_usage", args, "50 bags cement arrived")
    assert (made.tool, made.args) == ("save_material_receipt", args)
    assert reroute.before("save_material_usage", args, "50 bags cement used for slab") is None


def test_an_order_filed_as_an_issue_is_the_request_with_its_day():
    made = reroute.before("report_issue", {"narrative": "x"}, "nale 50 bag cement order cheyyanam")
    assert made.tool == "request_material" and made.args["needed_by"] == "tomorrow"
    # It ran out and work stopped: a real problem on site, filed as asked.
    assert reroute.before("report_issue", {}, "cement theernnu, pani ninnu, 50 bag venam") is None


def test_when_the_words_do_not_hold_the_call_the_model_is_told():
    made = reroute.before("report_issue", {}, "10 bag cement balance und, kooduthal venam")
    assert made.tool is None and "request_material" in made.instruction


def test_an_add_on_after_a_refused_correction_is_its_save():
    changes = {"workers": [{"trade": "helper", "headcount": 10}]}
    made = reroute.after("update_pending_card", {"changes": changes}, "10 helper-um vannu", "not_a_correction")
    assert (made.tool, made.args) == ("save_labour", changes)
    assert reroute.after("update_pending_card", {"changes": changes}, "10 helper-um vannu", "saved") is None
    assert reroute.after("update_pending_card", {"changes": changes}, "alla, 10 helper aanu", "not_a_correction").tool is None
