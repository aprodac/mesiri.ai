"""Request 196 (Paraclette, 1 Nov, read with the ops token): on every message with more than one
part the reply carried only one thing.

Root causes (both code, both on every wording):
1. Above a card the reply was the code's one sentence ("👍 Kitti. ✅ Save tap cheyyu"), and the
   model's words were dropped (runner._code_card), or cut to one sentence (_one_sentence): the
   greeting, the weather answer and "who else reported" never reached them (cor_56422078, 14:12).
2. ``ask`` took ``other_parts`` and parked them "for later", so a clear labour report waited
   behind an unneeded question and was then lost (cor_570c71ae, 13:26).
Fix: v2 keeps the model's words above the card (the code still draws the lines and filters
claims); v2's ``ask`` has no ``other_parts``: every other part is done in the same turn.
Guard: today's agent (classic, every real customer) is unchanged.
"""

from __future__ import annotations

from dataclasses import replace

from tests.agent_v2.evalkit import _Books
from tests.replay.test_agent_replay import _Catalog, _make_world
from tests.replay.test_draft_per_message_p1 import open_items

from agent_v2.agents.main import all_specs
from agent_v2.runner import V2Runner
from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import draft as dr
from runtime.agent.draft_store import MemoryDraftStore
from runtime.agent.runner import AgentRunner

STEEL = ("draft_receipt", {"material": "steel", "quantity": 20, "unit": "nos", "figures_placed": [20]})
LOG = ("query_work_log", {"date": "today"})
LABOUR = ("save_labour", {"workers": [
    {"trade": "electrician", "headcount": 20}, {"trade": "carpenter", "headcount": 10}, {"trade": "helper", "headcount": 20},
]})


async def _world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2, world.drafts, world.catalog, world.inventory = True, MemoryDraftStore(), _Catalog(), _Books()
    world.actor = replace(world.actor, role="PROJECT_MANAGER")
    return world


async def _say(world, text: str, script: list):  # noqa: ANN001
    runner = V2Runner(FakeToolCallingProvider(script), AgentRunner(FakeToolCallingProvider(["x"])))
    return await runner.run(
        ctx=world.context(), user_text=text, gateway=world.gateway(text), scope=world.scope(), correlation_id="cor_196",
    )


async def test_the_greeting_and_the_answers_stay_above_the_card():
    world = await _world()
    words = "Sugham aanu! Mesiri-kku weather data illa. Innu vere aarum report cheythittilla. TMT thazhe und."
    result = await _say(
        world, "Yo, enthokke und? Innu 20 TMT steel vannu. Innathe weather enthaa, vere aarenkilum report cheytho?",
        [[STEEL, LOG], words],
    )
    text = result.reply.text
    assert "Sugham" in text and "weather" in text and "report" in text  # every part reaches them
    assert [i.kind for i in await open_items(world)] == [dr.KIND_MATERIAL_IN]
    assert "Steel" in text or "steel" in text  # the code still draws the line


async def test_with_no_words_from_the_model_the_code_sentence_is_still_there():
    world = await _world()
    result = await _say(world, "Innu 20 TMT steel vannu", [[STEEL], ""])
    assert result.reply is not None and "Save" in result.reply.text


def test_v2_ask_has_no_other_parts_to_park():
    ask = next(s for s in all_specs() if s.name == "ask")
    assert "other_parts" not in ask.parameters.get("properties", {})


async def test_a_question_never_holds_back_a_clear_record():
    world = await _world()
    ask = ("ask", {"question": "Weather record cheyyano?", "options": ["Yes", "No"], "other_parts": [{"tool": "save_labour", "what": "50 per"}]})
    await _say(world, "Weather enthaa? Innu 50 per vannu, 20 electrician, 10 carpenter, baakki helper", [[ask, LABOUR], "ok"])
    kinds = [i.kind for i in await open_items(world)]
    assert dr.KIND_LABOUR in kinds  # the labour is on the card now, not "later"


async def test_guard_honesty_still_holds_in_v2s_own_reply():
    world = await _world()
    result = await _say(
        world, "Sugham? Innu 20 TMT steel vannu",
        [[STEEL], "Sugham! Saved 20 nos steel. Stock is now 75 nos."],
    )
    text = result.reply.text
    assert "Sugham" in text  # the greeting stays
    assert "Saved 20" not in text  # nothing is saved before the Save tap
    assert "75" not in text  # a figure in no message and no tool result never goes out
    assert "Steel in: 20 nos" in text  # the line is drawn by the code


def test_todays_agent_keeps_its_own_composer():
    """Real customers run today's agent: its reply code is not touched by v2's."""
    import inspect

    from runtime.agent import runner

    assert "keep_model_words" not in inspect.getsource(runner)
