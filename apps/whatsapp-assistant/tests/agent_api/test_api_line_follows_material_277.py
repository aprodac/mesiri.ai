"""WA-277 round 2: a card line never names one material and saves on another.

Round 2 on the real model (11 Nov, 12 hardest saved conversations, 11 right): "20 bags cement used, then 30 hollow
bricks used" was held as "30 nos Solid Blocks". Two things were wrong, neither of them the model alone:

- the code's material check moves a line to the material the person named (a listed one, or a new one it prepares),
  but the line's text stayed the model's: production's own card on 7 Nov read "New material: Hollow Bricks" above
  "30 nos Solid Blocks ... upayogichu". The record was right and the card was not;
- the replay answered the code's read of the material list with nothing, which switches that check off, so the
  real model was judged without it (fixed in replaykit: ``facts_catalogue``).

The class: every way the code changes a line's material (a new material, another listed one by name, a trade
name) rewrites the name in the line. Guards: a line whose material the code did not change is untouched; a line
written in the person's own word, with no listed name in it, is untouched; a name inside a longer word is not cut.
"""

from __future__ import annotations

import pytest
from tests.agent_api import replaykit as rk

from agent_api.agent import ApiAgent, line_on
from agent_api.tools import CONFIRM_ARG, MATERIAL_SAID
from mesiri_ai.fakes import FakeToolCallingProvider

PROJECT = "fbbf8d3e-e9f2-4dd3-937a-e0df5bd1a6b0"
SITE = "54720c70-a526-44e8-88dd-350ccef42805"
NOS = "ebc540c6-e1fd-452f-8a89-fa304d89fb40"
BRICKS = "39b13c0c-b97e-4cec-8a8f-7bc99564ad1b"
SOLID = "64594c8e-a829-45fa-b600-63e0c95ad162"
FACTS = (f"The person's projects and sites (use these ids):\n- project Green villa (project_id {PROJECT})\n"
         f"  - site Green villa (site_id {SITE})\nOnly one site: Green villa. Use it; never ask which site.\n\n"
         f"Units (unit_id): nos ({NOS})\nMaterials (material_id, default unit):\n"
         f"- Bricks ({BRICKS}, nos)\n- Solid Blocks ({SOLID}, nos)")


def _usage(material_id: str, said: str, line: str) -> tuple[str, dict]:
    return ("record_usage", {"project_id": PROJECT, "site_id": SITE, "material_id": material_id, "unit_id": NOS,
                             "quantity": 30, "occurred_date": "2026-11-07", MATERIAL_SAID: said, CONFIRM_ARG: line})


async def _lines(call: tuple[str, dict], text: str) -> list[str]:
    api = rk.RecordedApi(catalogue=rk.facts_catalogue(FACTS))
    turn = await ApiAgent(FakeToolCallingProvider([[call], "ok"]), rk._real_tools()).run(api, text, facts=FACTS)  # type: ignore[arg-type]
    return [e.summary for e in turn.pending]


async def test_a_new_material_line_names_the_new_material() -> None:
    lines = await _lines(_usage(SOLID, "Hollow Bricks", "30 nos Solid Blocks Green villa-il upayogichu"),
                         "30 hollow bricks use cheythu")
    assert lines == ["New material: Hollow Bricks", "30 nos Hollow Bricks Green villa-il upayogichu"]


async def test_a_line_moved_to_another_listed_material_names_it() -> None:
    lines = await _lines(_usage(BRICKS, "solid blocks", "30 nos Bricks, Green villa"), "30 solid blocks use cheythu")
    assert lines == ["30 nos Solid Blocks, Green villa"]


async def test_a_line_the_code_did_not_move_is_left_alone() -> None:
    lines = await _lines(_usage(SOLID, "solid blocks", "30 solid block, Green villa"), "30 solid blocks use cheythu")
    assert lines == ["30 solid block, Green villa"]


async def test_a_line_in_their_own_word_is_left_alone() -> None:
    lines = await _lines(_usage(SOLID, "Hollow Bricks", "30 hollow katta, Green villa"), "30 hollow bricks use cheythu")
    assert lines == ["New material: Hollow Bricks", "30 hollow katta, Green villa"]


@pytest.mark.parametrize(("line", "wrong", "right", "out"), [
    ("30 nos solid blocks, Villa", "Solid Blocks", "Hollow Bricks", "30 nos Hollow Bricks, Villa"),
    ("5 kg Steel", "Steel", "TMT Steel", "5 kg TMT Steel"),
    ("10 Stainless Steelwork", "Steel", "TMT Steel", "10 Stainless Steelwork"),
    ("5 kg Steel", "Steel", "steel", "5 kg Steel"),
    ("", "Steel", "TMT Steel", ""),
    ("5 kg Steel", "", "TMT Steel", "5 kg Steel"),
])
def test_line_on(line: str, wrong: str, right: str, out: str) -> None:
    assert line_on(line, wrong, right) == out


# --- WA-277 round 5: a thing made by name is prepared once a turn ----------------------------------------------------

def test_same_named_finds_the_twin_and_only_the_twin() -> None:
    from agent_api.agent import ONE_PER_NAME, PendingWrite, same_named

    def held(tool: str, name: str) -> PendingWrite:
        return PendingWrite(tool=tool, method="POST", path="/projects", params={}, body={"name": name},
                            summary=f"New project {name}", idempotency_key=name)

    hospital = held("create_project", "Hospital")
    assert same_named([hospital], "create_project", {"name": " hospital "}) is hospital
    assert same_named([hospital], "create_project", {"name": "Hospital Block B"}) is None
    assert same_named([hospital], "add_material", {"name": "Hospital"}) is None
    assert same_named([hospital], "create_project", {}) is None
    assert {"create_project", "add_material", "add_site"} <= ONE_PER_NAME
    assert "record_receipt" not in ONE_PER_NAME  # two deliveries of one material in a message are two lines


async def test_a_project_prepared_twice_in_one_turn_is_on_the_card_once() -> None:
    project = ("create_project", {"name": "Hospital", CONFIRM_ARG: "New project Hospital"})
    api = rk.RecordedApi()
    turn = await ApiAgent(FakeToolCallingProvider([[project, project], "ok"]), rk._real_tools()).run(api, "add project Hospital")  # type: ignore[arg-type]
    assert [e.tool for e in turn.pending] == ["create_project"]
    assert "already prepared in this turn" in str(turn.calls[1]["result"])
