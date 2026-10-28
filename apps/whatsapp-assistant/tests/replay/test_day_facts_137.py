"""Request 137: one rule for saved work. A newer percentage for work already saved is
a new line, never a correction; an explicit correction edits the saved line by its
fact id; a failed correction is answered by the code's template, not the model's words.

The model is scripted (the 28 Oct re-test messages); everything after it is the real
journey, as in ``test_draft_per_message_p2``.
"""

from __future__ import annotations

import pytest
from tests.replay.test_agent_replay import _make_world, _MemoryRedis
from tests.replay.test_draft_per_message_p1 import press, titles
from tests.replay.test_draft_per_message_p2 import _Undo

from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent.cards import CardStore
from runtime.agent.draft_store import MemoryDraftStore

TILING = {"narrative": "ground floor tiling", "work_type": "tiling", "location": "ground floor"}


def tiling(percent: int) -> tuple[str, dict]:
    return ("save_work_done", {**TILING, "progress_percent": percent})


def correct(value: int, unit: str | None = None) -> tuple[str, dict]:
    return ("correct_work_quantity", {"new_quantity": value, **({"unit": unit} if unit else {})})


@pytest.fixture
async def world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    world.cards = CardStore(_MemoryRedis())
    world.undo_facts = _Undo()
    return world


async def _saved_70(world) -> None:
    result = await world.say(FakeToolCallingProvider([[tiling(70)], "Check it."]), "ground floor tiling 70% aayi")
    await press(world, result.reply, "✅ Save")
    assert len(world.dispatcher.dispatched) == 1


async def test_a_newer_percent_after_a_saved_one_is_a_new_line_not_a_correction(world):
    """F1 (28 Oct, #4842): "Green Villa ground floor tiling 80% aayi" after 70% was saved
    got "Sorry, tiling work-inte percentage maattan kazhinjilla" and no card."""
    await _saved_70(world)
    provider = FakeToolCallingProvider([[correct(80)], [tiling(80)], "Check it."])
    result = await world.say(provider, "Green Villa ground floor tiling 80% aayi")

    assert "Sorry" not in result.reply.text and "kazhinjilla" not in result.reply.text
    assert "Tiling, ground floor: 80%" in result.reply.text
    assert titles(result.reply) == ["✅ Save", "❌ Cancel"]
    assert world.undo_facts.asked == []  # the saved 70% was not taken back

    await press(world, result.reply, "✅ Save")
    assert len(world.dispatcher.dispatched) == 2


async def test_an_explicit_percent_correction_edits_the_saved_line(world):
    await _saved_70(world)
    provider = FakeToolCallingProvider([[correct(75, "%")], "Sheri."])
    result = await world.say(provider, "alla, 75%")

    assert "75%" in result.reply.text
    assert titles(result.reply) == ["✅ Save", "❌ Cancel"]
    await press(world, result.reply, "✅ Save")
    (taken_back,) = world.undo_facts.asked
    assert taken_back[0] == "activity"


async def test_a_failed_correction_is_answered_by_the_code_not_the_model(world):
    """Nothing saved, nothing to change: the model's apology never goes out."""
    result = await world.say(
        FakeToolCallingProvider([[correct(80, "%")], "Sorry, percentage maattan kazhinjilla."]),
        "tiling 80% aayi",
    )
    assert "kazhinjilla" not in result.reply.text
