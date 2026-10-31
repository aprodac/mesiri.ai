"""Request 162: "I didn't say workers" takes the line away; an old button never acts as a fresh one.

Live 31 Oct, Adarsh (PROJECT_MANAGER): a card carried "10 workers (10 mason)" he never said.
He cancelled it and said he never mentioned workers; the model, still primed by the card's
material question, read his sentence as a material name. He then tapped buttons of the
cancelled card and each answered whatever was open "now". Now code reads the removal, rebuilds
the cancelled card without the line (Save asked again), and an old tap is applied to the same
line of the open card or says the card was cancelled.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
from tests.replay.test_agent_replay import _make_world, _MemoryRedis
from tests.replay.test_draft_per_message_p1 import CEMENT, LABOUR, open_items, titles

from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import corrections
from runtime.agent import draft as dr
from runtime.agent.cards import CardStore
from runtime.agent.draft_store import MemoryDraftStore
from runtime.agent.journal import MemoryJournalStore
from runtime.agent.turn import _code_correction

EXPENSE = ("save_expense", {"amount": 140, "description": "tea"})
SAID = "50 bag cement vannu, 3 mason 12 helper"
NEVER = "there's only cement, I didn't say anything about workers"
LATER = (dt.date.today() + dt.timedelta(days=61)).isoformat()


@pytest.fixture
async def world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    world.cards = CardStore(_MemoryRedis())
    world.journal = MemoryJournalStore()
    return world


async def _card(world, *calls, text=SAID):  # noqa: ANN001, ANN202
    return await world.say(FakeToolCallingProvider([list(calls), "Check it."]), text)


async def _open(world):  # noqa: ANN001, ANN202
    return await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)


async def _said(world, text):  # noqa: ANN001, ANN202
    return await corrections.correct(world.gateway(text), text)


def _card_of(reply) -> str:  # noqa: ANN001
    """The card under the words: what would be saved."""
    return reply.text.partition("To save")[2].casefold()


# -- the words ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kinds"),
    [
        ("there's only M sand and P sand, I didn't say anything about workers", ["labour"]),
        ("workers venda", ["labour"]),
        ("remove the labour", ["labour"]),
        ("expense venda", ["expense"]),
        ("തൊഴിലാളി വേണ്ട", ["labour"]),
        ("labour ozhivaakku", ["labour"]),
        ("alla, 6 mason aanu", []),  # a correction of a count, never a removal
        ("6 mason aanu", []),
        ("cement not received", []),
        ("3 mason 12 helper vannu", []),
    ],
)
def test_the_words_that_take_something_away(text, kinds):
    assert corrections.removal_kinds(text) == kinds


# -- the open card ---------------------------------------------------------------------------


async def test_the_line_they_never_said_is_taken_off_the_open_card(world):
    await _card(world, CEMENT, LABOUR)
    assert {i.kind for i in await open_items(world)} == {dr.KIND_MATERIAL_IN, dr.KIND_LABOUR}
    reply = await _said(world, NEVER)
    assert [i.kind for i in await open_items(world)] == [dr.KIND_MATERIAL_IN]
    assert "cement" in _card_of(reply) and "mason" not in _card_of(reply) and "✅ Save" in titles(reply)
    assert not world.dispatcher.dispatched  # nothing is saved without Save


async def test_an_expense_is_taken_off_by_the_same_path(world):
    await _card(world, CEMENT, EXPENSE, text="paid 140 for tea, 50 bag cement vannu")
    reply = await _said(world, "expense venda")
    assert [i.kind for i in await open_items(world)] == [dr.KIND_MATERIAL_IN]
    assert "tea" not in _card_of(reply) and "cement" in _card_of(reply)


async def test_a_named_material_is_taken_off_and_the_rest_stays(world):
    await _card(world, CEMENT, LABOUR)
    await _said(world, "cement venda")
    assert [i.kind for i in await open_items(world)] == [dr.KIND_LABOUR]


async def test_the_only_line_removed_leaves_nothing_open(world):
    await _card(world, LABOUR, text="3 mason 12 helper vannu")
    reply = await _said(world, "workers venda")
    assert await _open(world) is None and "✅ Save" not in titles(reply)


async def test_a_count_correction_is_not_a_removal(world):
    await _card(world, CEMENT, LABOUR)
    assert await _said(world, "alla, 6 mason aanu") is None
    assert len(await open_items(world)) == 2


async def test_words_that_match_no_line_go_to_the_model(world):
    await _card(world, CEMENT)
    assert await _said(world, "workers venda") is None


# -- after Cancel: the card is rebuilt, not guessed ------------------------------------------


async def test_after_cancel_the_card_comes_back_without_the_line_and_asks_save(world):
    await _card(world, CEMENT, LABOUR)
    old = await _open(world)
    await world.gateway("cancel").cancel_draft(old)
    assert await _open(world) is None
    reply = await _said(world, NEVER)
    (fresh,) = [d for d in [await _open(world)] if d]
    assert fresh.id != old.id and [i.kind for i in fresh.items] == [dr.KIND_MATERIAL_IN]
    assert "✅ Save" in titles(reply) and "cement" in _card_of(reply) and "mason" not in _card_of(reply)
    assert not world.dispatcher.dispatched


async def test_the_whole_sentence_is_never_a_material_name(world):
    """The live failure: the model asked "what is this material's correct name?" for the sentence."""
    await _card(world, CEMENT, LABOUR)
    await world.gateway("cancel").cancel_draft(await _open(world))
    reply = await _said(world, NEVER)
    assert "correct name" not in reply.text and "sentence" not in reply.text and "didn't say" not in reply.text


async def test_the_pre_model_hook_answers_it_in_code(world):
    await _card(world, CEMENT, LABOUR)
    await world.gateway("cancel").cancel_draft(await _open(world))
    message = SimpleNamespace(metadata={}, modality=dr and __import__("mesiri_contracts.assistant.enums", fromlist=["x"]).InputModality.TEXT)
    gateway = world.gateway(NEVER)
    reply = await _code_correction(message, gateway, world.context(()), NEVER)
    assert reply is not None and "✅ Save" in titles(reply)


# -- after Save: an undo with a confirm, never a silent delete -----------------------------------


async def test_after_save_a_removal_offers_the_undo_with_a_confirm(world):
    await _card(world, CEMENT, LABOUR)
    await world.gateway("save").save_draft(await _open(world))
    saved_before = len(world.dispatcher.dispatched)
    reply = await _said(world, "workers venda")
    assert reply is not None and any("remove" in t.lower() for t in titles(reply))
    assert len(world.dispatcher.dispatched) == saved_before  # asked, nothing removed yet


# -- old buttons --------------------------------------------------------------------------------


async def test_an_old_save_tap_on_a_cancelled_card_never_saves(world):
    await _card(world, CEMENT)
    old = await _open(world)
    await world.gateway("cancel").cancel_draft(old)
    reply = await corrections.old_card_tap(world.gateway("Save"), old, dr.SAVE, ())
    assert not world.dispatcher.dispatched and await _open(world) is None
    assert "cancelled" in reply.text and "Save" not in titles(reply)


async def test_an_old_tap_shows_the_card_that_is_open_now(world):
    await _card(world, CEMENT, LABOUR)
    old = await _open(world)
    await world.gateway("cancel").cancel_draft(old)
    await _said(world, NEVER)
    reply = await corrections.old_card_tap(world.gateway("Save"), old, dr.SAVE, ())
    assert not world.dispatcher.dispatched
    assert "cancelled" in reply.text and "cement" in _card_of(reply) and "✅ Save" in titles(reply)


async def test_an_old_answer_goes_to_the_same_line_of_the_open_card(world):
    dated = ("save_material_receipt", {**CEMENT[1], "date": LATER})
    await _card(world, dated, LABOUR)
    old = await _open(world)
    asking = next(i for i in old.items if i.state == dr.NEEDS_ANSWER)
    keep = asking.options.index(next(o for o in asking.options if o not in ("Today", "Another date")))
    await world.gateway("cancel").cancel_draft(old)
    await _said(world, NEVER)
    await corrections.old_card_tap(world.gateway("tap"), old, dr.ANSWER, (asking.id, str(keep)))
    (item,) = await open_items(world)
    assert item.id == asking.id and item.state == dr.OK  # applied there, not asked again


async def test_a_tap_on_a_card_that_is_gone_says_so_in_their_language(world):
    await _card(world, CEMENT)
    old = await _open(world)
    await world.gateway("cancel").cancel_draft(old)
    gateway = world.gateway("x")
    gateway.wording_language = "malayalam"
    reply = await corrections.old_card_tap(gateway, old, dr.SAVE, ())
    assert "ക്യാൻസൽ" in reply.text


def test_an_option_button_of_an_earlier_question_is_stale():
    last = "Only cement. Save?\n[options: ✅ Save / ❌ Cancel]"
    assert corrections.is_stale_option_tap("agent_opt_1", "M sand", last)
    assert not corrections.is_stale_option_tap("agent_opt_1", "Save", last.replace("✅ ", ""))
    assert not corrections.is_stale_option_tap("agent_opt_1", "M sand", "Which one?\n[options: M sand / P sand]")
    assert not corrections.is_stale_option_tap("agent_opt_1", "M sand", "Which one?")  # unknown: the model reads it
    assert not corrections.is_stale_option_tap("agd:ans:x", "M sand", last)


# -- the staging guard: the 10 workers cannot reappear ---------------------------------------------------


async def test_a_labour_line_is_not_staged_from_a_message_that_never_said_it(world):
    await world.say(FakeToolCallingProvider([[CEMENT, LABOUR], "Done."]), "Received")
    assert [i.kind for i in await open_items(world)] == [dr.KIND_MATERIAL_IN]


async def test_a_labour_line_is_staged_when_the_message_says_it(world):
    await world.say(FakeToolCallingProvider([[LABOUR], "Done."]), "3 mason 12 helper vannu")
    assert [i.kind for i in await open_items(world)] == [dr.KIND_LABOUR]


@pytest.mark.parametrize("text", ["ഇന്ന് 4 മേസൺ വന്നു", "aaj mazdoor aaye", "randu helper vannu", "workers came", "ഇന്ന് 6 പേർ", "8 log aaye"])
def test_what_counts_as_saying_labour(text):
    assert corrections.labour_was_said(text)


@pytest.mark.parametrize("text", ["M sand", "Received", "Green Villa"])
def test_what_does_not(text):
    assert not corrections.labour_was_said(text)
