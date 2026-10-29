"""Live 29 Oct (screenshots): the first card was saved and closed (10 plasterer, 5
carpenter); "10 helper-um vannu" swiped on it went to the model as a correction of a
line the code could not match. The code said "nothing to correct, this is new" and
asked the model to save it; the model apologised instead ("I tried to correct an
item...") and nothing was saved until a second message. Now a correction that is new
information is saved by the code -- unless their words say a figure was wrong."""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")

from tests.replay.test_agent_replay import _make_world, _MemoryRedis  # noqa: E402
from tests.replay.test_draft_per_message_p1 import open_items, press  # noqa: E402
from tests.replay.test_draft_per_message_p2 import _Undo  # noqa: E402

from context import seed  # noqa: E402
from mesiri_ai.fakes import FakeToolCallingProvider  # noqa: E402
from runtime.agent.cards import CardStore  # noqa: E402
from runtime.agent.draft_store import MemoryDraftStore  # noqa: E402
from runtime.agent.reroute import Call  # noqa: E402
from runtime.agent.reroute import as_new_entry as _as_new  # noqa: E402


def as_new_entry(tool, args, text=""):  # noqa: ANN001, ANN201
    return _as_new(Call(tool, args, text)) if tool == "update_pending_card" else None

CREW = ("save_labour", {"workers": [{"trade": "plasterer", "headcount": 10}, {"trade": "carpenter", "headcount": 5}]})
HELPERS = {"workers": [{"trade": "helper", "headcount": 10}]}


@pytest.fixture
async def world():  # noqa: ANN201
    """A draft_v2 sender whose saved card is kept (as in production)."""
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2, world.drafts = True, MemoryDraftStore()
    world.cards, world.undo_facts = CardStore(_MemoryRedis()), _Undo()
    return world


# The live model's words after the refused correction: they must never be the answer.
APOLOGY = "Ayyo, ee card-il oru item maatri correct cheyyan njan sremichu, pakshe athu puthiya oru entry aayittaanu."


async def _saved_crew(world):  # noqa: ANN001, ANN202
    first = await world.say(FakeToolCallingProvider([[CREW], "x"]), "10 plasterer 5 carpenter vannu")
    await press(world, first.reply, "✅ Save")
    return await world.cards.get(world.actor)


def _correction(card_id: str, item: int, changes: dict):  # noqa: ANN202
    call = ("update_pending_card", {"card_id": card_id, "item_index": item, "changes": changes})
    return FakeToolCallingProvider([[call], APOLOGY])


async def test_an_add_on_the_code_cannot_match_is_saved_in_the_same_message(world):
    saved = await _saved_crew(world)

    result = await world.say(_correction(saved.id, 3, HELPERS), "10 helper-um vannu")

    (call,) = result.run.calls
    assert call.outcome.content["status"] == "waiting_for_save"
    assert [i.line for i in await open_items(world)] == ["10 workers (10 helper)"]
    assert "sremichu" not in result.reply.text


async def test_an_add_on_on_the_saved_line_is_a_change_with_the_new_total(world):
    saved = await _saved_crew(world)

    await world.say(_correction(saved.id, 1, HELPERS), "10 helper-um vannu")

    assert [i.line for i in await open_items(world)] == ["Change today's labour: helper 0 → 10 (total 25)"]


async def test_a_correction_is_never_saved_as_more_workers(world):
    saved = await _saved_crew(world)

    await world.say(_correction(saved.id, 3, {"workers": [{"trade": "plasterer", "headcount": 6}]}), "alla, 6 plasterer aanu")

    assert await open_items(world) == []


def test_only_a_whole_entry_is_saved_by_the_code():
    assert as_new_entry("update_pending_card", {"changes": HELPERS}, "10 helper-um vannu") == ("save_labour", HELPERS)
    work = {"quantities": [{"work_type": "plastering", "quantity": 50, "unit": "sqft"}]}
    assert as_new_entry("update_pending_card", {"changes": work})[0] == "save_work_done"
    # A bare percent or a material figure (received or used?) stays the model's to word.
    assert as_new_entry("update_pending_card", {"changes": {"progress_percent": 70}}) is None
    assert as_new_entry("update_pending_card", {"changes": {"quantity": 20}}) is None
    assert as_new_entry("update_pending_card", {"changes": HELPERS}, "alla, 10 helper aanu") is None
    assert as_new_entry("save_labour", {"changes": HELPERS}) is None
