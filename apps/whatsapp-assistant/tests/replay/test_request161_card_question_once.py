"""Request 161: a card item is never both a question and "Couldn't read"; cards saved
before request 159 heal when read; a day after today is asked on any kind of line.

Live 30 Oct (Ilan, ADMIN): Save on the morning's tea-bill card showed
"(❓ Which account did you pay from?)" AND "Couldn't read: Expense ₹140 ...", the bill
still dated 30 Dec on 30 Oct. The card was made before request 159, which marked the
item unreadable with the workflow's question as its reason; that state was stored.
"""

from __future__ import annotations

import datetime as dt

import pytest
from tests.replay.test_agent_replay import _make_world, _MemoryRedis
from tests.replay.test_draft_per_message_p1 import LABOUR, open_items, titles
from tests.replay.test_request159_a_save_question import (
    ACCOUNTS,
    CEMENT,
    QUESTION,
    _asks_once,
    _card_then_save,
    _tap,
)

from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import draft as dr
from runtime.agent.cards import CardStore
from runtime.agent.draft_store import MemoryDraftStore

TEXT = {"save_material_receipt": "50 bag cement vannu", "save_labour": "3 mason 12 helper vannu", "save_expense": "paid 140 for tea"}
LATER = (dt.date.today() + dt.timedelta(days=61)).isoformat()


@pytest.fixture
async def world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    world.cards = CardStore(_MemoryRedis())
    return world


def _as_before_159(world, draft_id: str) -> None:
    """The stored row as request 142 left it: unreadable, the question its reason."""
    (item,) = world.drafts.rows[draft_id].items
    item.state, item.reason = dr.UNREADABLE, QUESTION
    item.awaiting, item.question, item.options = "", "", []


async def test_an_old_card_heals_to_one_question_and_saves_once(world):
    answered = _asks_once(world)
    card = await _card_then_save(world)
    (item,) = await open_items(world)
    _as_before_159(world, item_draft := (await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)).id)
    assert item_draft

    draft = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
    (healed,) = draft.items
    assert healed.state == dr.NEEDS_ANSWER and healed.question == QUESTION and healed.reason == ""
    text = dr.card_reply(draft).text
    assert text.count(QUESTION) == 1 and dr.CANT_READ not in text

    # Save re-asks through the workflow, now with its buttons; the answer saves one entry.
    asked = await world.gateway("tap").save_draft(draft)
    assert dr.CANT_READ not in asked.text and asked.text.count(QUESTION) == 1
    assert [t for t in titles(asked) if t in ACCOUNTS] == list(ACCOUNTS)
    saved = await _tap(world, asked, "Office Cash")
    assert answered == ["Office Cash"] and saved.text.startswith("✅ *Saved*")
    assert len(world.dispatcher.dispatched) == 1
    assert card  # the card the tap started from


def test_a_real_read_failure_stays_couldnt_read():
    unprepared = dr.DraftItem(kind=dr.KIND_EXPENSE, tool="save_expense", args={}, state=dr.UNREADABLE, reason="nothing readable in it")
    prepared_failed = dr.DraftItem(
        kind=dr.KIND_EXPENSE, tool="save_expense", args={}, state=dr.UNREADABLE, ready={"event": {}}, reason="the day is already confirmed."
    )
    for item in (unprepared, prepared_failed):
        again = dr.DraftItem.from_json(item.to_json())
        assert again.state == dr.UNREADABLE and again.reason == item.reason
    draft = dr.MessageDraft.new(organization_id="o", user_id="u")
    draft.items = [dr.DraftItem.from_json(unprepared.to_json())]
    assert dr.CANT_READ in dr.card_reply(draft).text


def test_a_normal_card_renders_as_before():
    ok = dr.DraftItem(kind=dr.KIND_EXPENSE, tool="save_expense", args={}, summary="Expense ₹140")
    assert dr.DraftItem.from_json(ok.to_json()).state == dr.OK


@pytest.mark.parametrize("call", [CEMENT, LABOUR, ("save_expense", {"amount": 140, "description": "tea"})])
async def test_a_day_after_today_is_asked_with_today_the_day_and_another_date(world, call):
    tool, args = call
    result = await world.say(FakeToolCallingProvider([[(tool, {**args, "date": LATER})], "Check it."]), TEXT[tool])
    (item,) = await open_items(world)
    assert item.state == dr.NEEDS_ANSWER and item.options[0] == "Today" and item.options[2] == "Another date"
    later, now = dt.date.fromisoformat(LATER), dt.date.today()
    assert f"{later.day} {later:%b}" in item.question and f"{now.day} {now:%b}" in item.question
    assert item.options[1] == f"{later.day} {later:%b}"
    assert set(item.options) <= set(titles(result.reply))


async def test_the_date_answers(world):
    cement = ("save_material_receipt", {**CEMENT[1], "date": LATER})

    async def asked():
        for _ in await open_items(world):
            pass
        return await world.say(FakeToolCallingProvider([[cement], "Check it."]), "50 bag cement vannu")

    result = await asked()
    today = await _tap(world, result.reply, "Today")
    (item,) = await open_items(world)
    assert item.state == dr.OK and dr.CANT_READ not in today.text and "📅" not in today.text

    # Another date: the line is off the card.
    await world.drafts.discard((await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)).id)
    result = await asked()
    gone = await _tap(world, result.reply, "Another date")
    assert "right date" in gone.text and await open_items(world) == []


@pytest.mark.parametrize("day", [dt.date.today().isoformat(), (dt.date.today() - dt.timedelta(days=3)).isoformat()])
async def test_today_and_past_dates_are_not_asked(world, day):
    await world.say(FakeToolCallingProvider([[("save_material_receipt", {**CEMENT[1], "date": day})], "Check it."]), "50 bag cement vannu")
    (item,) = await open_items(world)
    assert item.state == dr.OK
