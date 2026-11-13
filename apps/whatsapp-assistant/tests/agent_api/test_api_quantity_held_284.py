"""WA-284 (live test on Mesiri Test Builders, 13 Nov 2026): "Site B il 10 bag cement vannu, steel um vannu, 2 mason
undu". The model prepared steel with ``quantity: 1`` and a line of its own with no number ("steel, Site B"); the code
then asked "1 Numbers Steel-il ethra Kilograms undu?" about a number nobody said, and "Ariyilla" held that made-up line
as a size request that saves by itself when the admin answers.

Root cause: the check for a quantity nobody said ([248] ``made_up``) reads only lines with a rate; a rate-less material
line went through with whatever number the model put in.
Fix: the WA-280 hold, a fifth gap: a material line whose own card line has no number, with a quantity that is not in
their words, is kept and the code asks how much (with the unit). The answer ("2 ton") is put in by the code, which
reads the unit from it and prepares the line itself; the other lines of the message go on as they were.
Guards: "50 bags cement" and a number said as a word ("oru bag", the line says "1 bag") are never held; a message
that is not an answer asks again; a held line never reaches the size question.
"""

from __future__ import annotations

from tests.agent_api.test_api_held_280 import BAGS, CEMENT, _run, receipt

from agent_api.agent import GAP_QUANTITY, answer_to_hold, filled_call, quantity_not_said
from agent_api.tools import CONFIRM_ARG, MATERIAL_SAID
from runtime.agent.wording import LANGUAGES, say

SAID = "Annex il 10 bag cement vannu, cement um vannu, 2 mason undu"
#: The model's call, live: no number in its line, a 1 it made up.
NO_NUMBER = receipt(CEMENT, "cement", "cement, Annex", quantity=1, unit=BAGS)
TEN_BAGS = receipt(CEMENT, "cement", "10 bags cement, Annex", quantity=10, unit=BAGS)


async def test_the_reported_line_is_held_and_the_code_asks_how_much() -> None:
    turn, _ = await _run([[TEN_BAGS, NO_NUMBER], "Sheri."], SAID)
    assert [e.body["quantity"] for e in turn.pending] == [10]  # the clear line goes on
    assert [(h["gap"], h["field"]) for h in turn.held] == [(GAP_QUANTITY, "quantity")]
    assert turn.question == "Cement ethra? (unit koode parayu, eg 2 ton, 50 bags)"
    assert turn.options == []  # a free answer, never buttons with made-up amounts
    assert all("1 nos" not in e.summary and "Numbers" not in e.summary for e in turn.pending)


async def test_the_answer_with_its_unit_prepares_the_line_with_no_model() -> None:
    first, _ = await _run([[NO_NUMBER], "Sheri."], "cement um vannu")
    turn, model = await _run(["never read"], "50 bags", holds=first.held)
    assert model.prompts == []
    assert [(e.body["quantity"], e.body["unit_id"]) for e in turn.pending] == [(50, BAGS)]
    assert turn.held == [] and turn.question == ""


def test_the_answer_is_put_in_the_line_and_a_said_unit_replaces_the_guess() -> None:
    hold = {"tool": "record_receipt", "arguments": dict(NO_NUMBER[1]), "gap": GAP_QUANTITY, "field": "quantity"}
    _name, args = filled_call(hold, "2 ton", [])
    assert args["quantity"] == 2 and "unit_id" not in args and args[CONFIRM_ARG] == "2 ton cement, Annex"
    _name, bare = filled_call(hold, "50", [])
    assert bare["quantity"] == 50 and bare["unit_id"] == BAGS and bare[CONFIRM_ARG] == "50 cement, Annex"
    _name, half = filled_call(hold, "2.5 ton", [])
    assert half["quantity"] == 2.5


def test_what_answers_how_much() -> None:
    hold = {"gap": GAP_QUANTITY, "options": []}
    assert answer_to_hold("2 ton", hold, None) == "2 ton" and answer_to_hold("50", hold, None) == "50"
    for no in ("ok", "ariyilla", "ethra venam?", "nale parayam", "cancel"):
        assert answer_to_hold(no, hold, None) is None, no


def test_guard_a_said_number_is_never_held() -> None:
    body = {"material_id": CEMENT, "quantity": 50}
    assert not quantity_not_said("50 bags cement vannu", body, {CONFIRM_ARG: "50 bags cement", MATERIAL_SAID: "cement"})
    # "oru bag" (one) is not in digits, but the model's line carries it: never held.
    assert not quantity_not_said("oru bag cement vannu", {**body, "quantity": 1}, {CONFIRM_ARG: "1 bag cement"})
    # A line the model wrote without a number, with a number they did say, is theirs: not held.
    assert not quantity_not_said("50 cement vannu", body, {CONFIRM_ARG: "cement"})
    # The reported case.
    assert quantity_not_said("steel um vannu", {**body, "quantity": 1}, {CONFIRM_ARG: "steel, Site B"})
    # No card line to read, or not a material line: nothing to tell from.
    assert not quantity_not_said("x", {**body, "quantity": 1}, {})
    assert not quantity_not_said("x", {"headcount": 2}, {CONFIRM_ARG: "mason"})


def test_the_question_exists_in_every_language() -> None:
    for language in LANGUAGES:
        assert "{word}" not in say("api.how_much", language, word="Steel")
        assert "Steel" in say("api.how_much", language, word="Steel")
