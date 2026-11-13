"""WA-280: the code owns the draft across turns, part 1 for the rest: one hold for the site, a material, a unit, a person.

WA-278 (12 Nov) kept a line refused for its site and prepared it itself when the site was answered. The same loss went
on everywhere else a line needed one answer from the person: "10 bags metal came" (Aggregate 20mm or 40mm, both listed),
a unit nobody could place, a person two names could mean, and a correction to one of those ("make it metal"). Each was
refused, the model was told to ask with `ask`, and after the answer the model had to prepare the line again from the
conversation: a new reading each time, and a tap carries nothing of what it answers.

The class, held here (one mechanism, ``hold_line``; ``ApiTurn.held`` is {tool, arguments, gap, field, options, word}):
- the line is kept with the call the model made; nothing is prepared or said to be;
- the question is the code's line and the code's buttons, in the person's language;
- the answer (the tap, the option typed short, or said inside a longer message) is put in the call by the code, which
  prepares the line itself; a bare answer runs no model;
- a message that is not the answer drops nothing; the question is asked again;
- a correction is found again by its line's key, so a moved number never changes the wrong line.

Guards: a miswritten unit id whose line names its unit is fixed, never asked; "ok" / a word that fits both buttons
answers nothing; the site hold of WA-278 works as before (its own tests); a hold kept under the old key is still read.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from tests.agent_api import replaykit as rk

from agent_api import whatsapp as wa
from agent_api.agent import (
    CHANGE_READY,
    ApiAgent,
    PendingWrite,
    Places,
    answer_to_hold,
    filled_call,
    held_question,
    updates_not_saved,
)
from agent_api.client import ApiResponse, new_idempotency_key
from agent_api.tools import CONFIRM_ARG, MATERIAL_SAID
from mesiri_ai.fakes import FakeToolCallingProvider

PROJECT = "0431ae5c-8ced-4ffa-8edc-ef1736f1af80"
ANNEX = "d721d8d5-26ce-461c-bce0-4d86db53eab8"
CEMENT = "3f194e81-47cb-43ec-b0e9-d2aa0a3311c8"
AGG20 = "6a1d1e3c-6f0e-4c64-9d0e-3f0c2a9b2a20"
AGG40 = "6a1d1e3c-6f0e-4c64-9d0e-3f0c2a9b2a40"
BAGS = "03e5cbfa-43d6-4af5-b18a-61aa7f884af7"
CUM = "13e5cbfa-43d6-4af5-b18a-61aa7f884af8"
FACTS = (f"The person's projects and sites (use these ids):\n- project Green Villa (project_id {PROJECT})\n"
         f"  - site Annex (site_id {ANNEX})\n\n"
         f"Units (unit_id): bags ({BAGS}), cum ({CUM})\nMaterials (material_id, default unit):\n"
         f"- Cement ({CEMENT}, bags)\n- Aggregate 20mm ({AGG20}, cum)\n- Aggregate 40mm ({AGG40}, cum)")
PLACES = Places(sites=[(ANNEX, "Annex", PROJECT)], projects=[(PROJECT, "Green Villa")])
UNITS = {"items": [{"id": BAGS, "code": "bags", "display_name": "Bags", "is_active": True},
                   {"id": CUM, "code": "cum", "display_name": "Cubic metre", "is_active": True}]}


def receipt(material: str, said: str, line: str, quantity: int = 10, unit: str = CUM) -> tuple[str, dict]:
    return ("record_receipt", {"project_id": PROJECT, "site_id": ANNEX, "material_id": material, "unit_id": unit,
                               "quantity": quantity, "occurred_date": "2026-11-13", MATERIAL_SAID: said,
                               CONFIRM_ARG: line})


METAL = receipt(AGG20, "metal", "10 cum metal")


@dataclass
class Api(rk.RecordedApi):
    """The recorded API, with the company's units (the code's unit check reads them)."""

    async def call(self, method: str, path: str, **kwargs: Any) -> ApiResponse:  # noqa: ANN401
        if (method, path) == ("GET", "/materials/units-of-measure"):
            self.seen.append((method, path))
            return ApiResponse(status=200, body=UNITS)
        return await super().call(method, path, **kwargs)


class Counting(FakeToolCallingProvider):
    def __init__(self, script: list) -> None:
        super().__init__(script)
        self.prompts: list[str] = []

    async def run_tools(self, system_prompt, messages, tools, handler, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.prompts.append(system_prompt)
        return await super().run_tools(system_prompt, messages, tools, handler, **kwargs)


async def _run(script: list, text: str, **kwargs):  # noqa: ANN003, ANN202
    model = Counting(script)
    api = Api(catalogue=rk.facts_catalogue(FACTS))
    turn = await ApiAgent(model, rk._real_tools()).run(  # type: ignore[arg-type]
        api, text, facts=FACTS, places=PLACES, language="manglish", **kwargs)
    return turn, model


# --- a material the words cannot tell apart ("metal": 20mm or 40mm) ------------------------------------------------

async def test_metal_is_held_and_the_code_asks_which_with_both_buttons() -> None:
    turn, _ = await _run([[METAL], "Sheri."], "10 cum metal vannu")
    assert turn.pending == []
    assert [(h["gap"], h["field"]) for h in turn.held] == [("material", MATERIAL_SAID)]
    assert turn.held[0]["arguments"]["quantity"] == 10
    assert turn.question == "Ethu Metal aanu?" and turn.options == ["Aggregate 20mm", "Aggregate 40mm"]
    assert "error" not in turn.calls[0]["result"]
    assert "Sheri" not in turn.reply and turn.reply == "Ethu Metal aanu?"  # the code's question, never a "ready"


async def test_the_tap_prepares_the_kept_line_with_no_model() -> None:
    first, _ = await _run([[METAL], "Sheri."], "10 cum metal vannu")
    turn, model = await _run(["this must never be read"], "Aggregate 40mm", holds=first.held)
    assert model.prompts == []  # a bare answer runs no model
    assert [(e.body["material_id"], e.body["quantity"]) for e in turn.pending] == [(AGG40, 10)]
    assert turn.held == [] and turn.question == ""
    assert [e.summary for e in turn.pending] == ["10 cum Aggregate 40mm"]  # the line names what was chosen


async def test_the_option_typed_short_is_the_answer_too() -> None:
    first, _ = await _run([[METAL], "Sheri."], "10 cum metal vannu")
    turn, model = await _run(["never read"], "20mm", holds=first.held)
    assert model.prompts == [] and [e.body["material_id"] for e in turn.pending] == [AGG20]


async def test_the_answer_inside_a_longer_message_prepares_it_and_the_model_does_the_rest() -> None:
    first, _ = await _run([[METAL], "Sheri."], "10 cum metal vannu")
    turn, model = await _run(["Sheri."], "athu aggregate 40mm aanu, pinne cement ethra undu?", holds=first.held)
    assert len(model.prompts) == 1 and "The CODE already prepared these" in model.prompts[0]
    assert [e.body["material_id"] for e in turn.pending] == [AGG40]


async def test_a_message_that_is_not_the_answer_drops_nothing_and_asks_again() -> None:
    first, _ = await _run([[METAL], "Sheri."], "10 cum metal vannu")
    turn, model = await _run(["Njan Mesiri aanu."], "nee aaraanu?", holds=first.held)
    assert len(model.prompts) == 1
    assert turn.held == first.held and turn.pending == []
    assert turn.question == "Ethu Metal aanu?" and turn.options == ["Aggregate 20mm", "Aggregate 40mm"]


async def test_two_metal_lines_take_one_tap() -> None:
    other = receipt(AGG20, "metal", "5 cum metal", quantity=5)
    first, _ = await _run([[METAL, other], "Sheri."], "10 cum metal vannu, 5 cum metal koode")
    assert len(first.held) == 2
    turn, _ = await _run(["never read"], "Aggregate 20mm", holds=first.held)
    assert sorted(e.body["quantity"] for e in turn.pending) == [5, 10] and turn.held == []


# --- a unit nobody can place -----------------------------------------------------------------------------------------

async def test_an_unknown_unit_is_held_and_answered_in_words() -> None:
    call = receipt(CEMENT, "cement", "50 furlongs cement", quantity=50, unit="furlongs")
    first, _ = await _run([[call], "Sheri."], "50 furlongs cement vannu")
    assert [h["gap"] for h in first.held] == ["unit"] and first.question == "Ethu unit-il aanu?"
    turn, model = await _run(["never read"], "bags", holds=first.held)
    assert model.prompts == [] and [(e.body["unit_id"], e.body["quantity"]) for e in turn.pending] == [(BAGS, 50)]


async def test_guard_a_miswritten_unit_id_whose_line_names_it_is_fixed_never_asked() -> None:
    call = receipt(CEMENT, "cement", "50 bags cement", quantity=50, unit="not-a-unit-id")
    turn, _ = await _run([[call], "Sheri."], "50 bags cement vannu")
    assert turn.held == [] and [e.body["unit_id"] for e in turn.pending] == [BAGS]


# --- a correction to a waiting line ----------------------------------------------------------------------------------

def _waiting_cement() -> PendingWrite:
    tool, args = receipt(CEMENT, "cement", "10 cum cement")
    body = {k: v for k, v in args.items() if k not in (CONFIRM_ARG, MATERIAL_SAID)}
    return PendingWrite(tool=tool, method="POST", path="/materials/inflows", params={}, body=body,
                        summary="10 cum cement", idempotency_key=new_idempotency_key())


async def test_a_correction_to_metal_is_held_and_the_tap_changes_that_line_only() -> None:
    entry = _waiting_cement()
    change = (CHANGE_READY, {"number": 1, "changes": {MATERIAL_SAID: "metal"}, CONFIRM_ARG: "10 cum metal"})
    first, _ = await _run([[change], "Sheri."], "alla, metal aanu", ready=[entry])
    assert [(h["gap"], h["entry_key"]) for h in first.held] == [("material", entry.idempotency_key)]
    assert [e.body["material_id"] for e in first.pending] == [CEMENT]  # unchanged until answered
    turn, model = await _run(["never read"], "Aggregate 20mm", holds=first.held, ready=first.pending)
    assert model.prompts == []
    assert [e.body["material_id"] for e in turn.pending] == [AGG20]  # changed in place: one line, never two
    assert [e.summary for e in turn.pending] == ["10 cum Aggregate 20mm"]


def test_a_correction_whose_line_is_gone_is_let_go() -> None:
    hold = {"tool": CHANGE_READY, "arguments": {"number": 1, "changes": []}, "gap": "material",
            "field": MATERIAL_SAID, "options": ["Aggregate 20mm", "Aggregate 40mm"], "word": "metal",
            "entry_key": "gone"}
    assert filled_call(hold, "Aggregate 20mm", [_waiting_cement()]) is None


def test_a_correction_is_found_by_its_key_when_the_numbers_moved() -> None:
    a, b = _waiting_cement(), _waiting_cement()
    hold = {"tool": CHANGE_READY, "arguments": {"number": 1, "changes": [{"field": "quantity", "value": "12"}]},
            "gap": "unit", "field": "unit_id", "options": [], "word": "", "entry_key": b.idempotency_key}
    name, arguments = filled_call(hold, "bags", [a, b])  # type: ignore[misc]
    assert name == CHANGE_READY and arguments["number"] == 2
    assert arguments["changes"] == {"quantity": "12", "unit_id": "bags"}


# --- what is and is not an answer -------------------------------------------------------------------------------------

HOLD = {"tool": "record_receipt", "arguments": {}, "gap": "material", "field": MATERIAL_SAID,
        "options": ["Aggregate 20mm", "Aggregate 40mm"], "word": "metal"}


def test_guard_ok_or_a_word_both_buttons_share_answers_nothing() -> None:
    assert answer_to_hold("ok", HOLD, PLACES) is None
    assert answer_to_hold("aggregate", HOLD, PLACES) is None
    assert answer_to_hold("Aggregate 40mm", HOLD, PLACES) == "Aggregate 40mm"
    assert answer_to_hold("40 mm", HOLD, PLACES) == "Aggregate 40mm"  # spaced as said
    assert answer_to_hold("baby metal", HOLD, PLACES) is None  # neither button: asked again, never guessed


def test_a_unit_answer_is_taken_as_said_but_never_a_question() -> None:
    unit = {**HOLD, "gap": "unit", "field": "unit_id", "options": ["bags", "cum"]}
    assert answer_to_hold("chaakku", unit, PLACES) == "chaakku"  # the code's unit check decides
    assert answer_to_hold("ethu unit?", unit, PLACES) is None


def test_the_questions_are_the_codes_in_their_language() -> None:
    assert held_question(HOLD, "english") == "Which Metal is it?"
    assert held_question({**HOLD, "word": ""}, "malayalam") == "ഏതാണ്?"
    assert held_question({**HOLD, "gap": "person"}, "hinglish") == "Kaun sa person hai?"


def test_a_report_waits_while_a_material_line_is_held() -> None:
    assert updates_not_saved([HOLD], [], {}) == 1


# --- the chat keeps the holds ----------------------------------------------------------------------------------------

def test_the_chat_reads_the_holds_and_the_older_site_key() -> None:
    now = time.time()
    lines = [HOLD]
    assert wa._held({"held": {"lines": lines, "at": now - 60}}, now) == lines
    assert wa._held({"site_held": {"lines": lines, "at": now - 60}}, now) == lines  # kept by WA-278 before this
    assert wa._held({"held": {"lines": lines, "at": now - wa.HELD_SECONDS - 1}}, now) == []
