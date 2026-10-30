"""Request 159 (C): the same line sent again after it was saved asks "already saved
at 11:05. Save again?" instead of saving it twice.

Live 30 Oct (midlaj): 100 bags in, 20 used saved at 11:05; the same message again with
the cost at 11:09 put the same lines on the card and saved them again (stock: 200 in,
40 used). One answer settles every repeated line; a real second delivery is one tap.
"""

from __future__ import annotations

import pytest
from tests.replay.test_agent_replay import _make_world, _MemoryRedis
from tests.replay.test_draft_per_message_p1 import open_items, press, titles

from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import checks
from runtime.agent import draft as dr
from runtime.agent.cards import CardStore
from runtime.agent.draft_store import MemoryDraftStore
from runtime.agent.journal import JournalEntry, JournalFact, MemoryJournalStore

IN = ("save_material_receipt", {"material": "cement", "quantity": 100, "unit": "bags"})
USED = ("save_material_usage", {"material": "cement", "quantity": 20, "unit": "bags"})


@pytest.fixture
async def world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    world.cards = CardStore(_MemoryRedis())
    world.journal = MemoryJournalStore()
    return world


async def _send_and_save(world):
    result = await world.say(FakeToolCallingProvider([[IN, USED], "Check it."]), "100 bags cement came, 20 bags used")
    saved, _ = await press(world, result.reply, "✅ Save")
    assert saved.text.startswith("✅ *Saved*")


async def _again(world):
    result = await world.say(
        FakeToolCallingProvider([[IN, USED], "Check it."]), "100 bags cement for 10000 rupees, 20 bags used"
    )
    return result.reply


async def test_the_same_lines_sent_again_ask_once_instead_of_saving_twice(world):
    await _send_and_save(world)
    card = await _again(world)

    assert card.text.count("already saved at") == 2  # on each line it is about
    assert "Cement in: 100 bags (❓ already saved at" in card.text
    assert titles(card)[-2:] == checks.REPEAT_OPTIONS and "✅ Save" not in titles(card)
    assert len(world.dispatcher.dispatched) == 2  # only the first Save wrote


async def test_remove_takes_every_repeated_line_off_in_one_tap(world):
    await _send_and_save(world)
    card = await _again(world)
    after, _ = await press(world, card, checks.REMOVE)
    assert "not saved twice" in after.text
    assert await open_items(world) == []
    assert len(world.dispatcher.dispatched) == 2


async def test_save_again_keeps_them_for_a_real_second_delivery(world):
    await _send_and_save(world)
    card = await _again(world)
    after, _ = await press(world, card, checks.AGAIN)
    assert [i.state for i in await open_items(world)] == [dr.OK, dr.OK]
    saved, _ = await press(world, after, "✅ Save")
    assert saved.text.startswith("✅ *Saved*") and len(world.dispatcher.dispatched) == 4


async def test_a_different_figure_is_a_new_line_not_a_repeat(world):
    await _send_and_save(world)
    other = ("save_material_receipt", {"material": "cement", "quantity": 50, "unit": "bags"})
    result = await world.say(FakeToolCallingProvider([[other], "Check it."]), "50 more bags cement came")
    assert "already saved" not in result.reply.text
    assert "✅ Save" in titles(result.reply)


def test_another_site_or_day_is_not_a_repeat():
    entry = JournalEntry("o", "u", [JournalFact("material_receipt", "f1", IN[0], {**IN[1], "site": "A"})], site_id="s1", day="2026-10-30")
    assert checks.already_saved(IN[0], {**IN[1], "site": "a "}, "2026-10-30", "s1", [entry]) is not None
    assert checks.already_saved(IN[0], IN[1], "2026-10-29", "s1", [entry]) is None
    assert checks.already_saved(IN[0], IN[1], "2026-10-30", "s2", [entry]) is None
    assert checks.already_saved(USED[0], IN[1], "2026-10-30", "s1", [entry]) is None
