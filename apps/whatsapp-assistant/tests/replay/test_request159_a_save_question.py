"""Request 159 (A): a question a workflow asks at Save is asked on the card's line,
and the answer finishes the Save the sender already tapped.

Live 30 Oct (Ilan, ADMIN): a ₹140 tea bill, Save -> "Nothing was saved. Couldn't save
Expense ₹140: Which account did you pay from? ... or just t" as an error; "Office
cash" typed -> a SECOND ₹140 line; Save -> the same error, twice more.

The class: any workflow that stops at Save to ask (expense account, a vendor to
add, a duplicate to confirm ...). The test drives it with the material receipt
workflow, whose start is made to ask once, as the expense workflow did; the
journey after it is the real one.
"""

from __future__ import annotations

import pytest
from tests.replay.test_agent_replay import _make_world, _MemoryRedis
from tests.replay.test_draft_per_message_p1 import open_items, titles

from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import draft as dr
from runtime.agent import draft_answer
from runtime.agent.cards import CardStore
from runtime.agent.draft_flow import _clean, question_title
from runtime.agent.draft_store import MemoryDraftStore
from workflows.runtime import WorkflowRunResult
from workflows.slots import RETRY_PREFIX, SlotCandidate

CEMENT = ("save_material_receipt", {"material": "cement", "quantity": 50, "unit": "bags"})
ACCOUNTS = ("Office Cash", "Operational Cash Account", "Site Cash", "Site Petty Cash Float", "My own pocket")
QUESTION = "Which account did you pay from?"
PROMPT = "\n".join([QUESTION, "", *(f"{n}. {a}" for n, a in enumerate(ACCOUNTS, 1)), "", "Reply with a number, or just tell me which one."])


@pytest.fixture
async def world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    world.cards = CardStore(_MemoryRedis())
    return world


def _asking(decision):
    return WorkflowRunResult.awaiting_input(
        workflow_key=decision.workflow_key,
        correlation_id="cor_agent_replay",
        workflow_instance_id="wf",
        pending_prompt=PROMPT,
        slot_options=tuple(SlotCandidate(value=a, label=a) for a in ACCOUNTS),
    )


def _asks_once(world, *, asks: int = 1) -> list[str]:
    """The workflow's start asks QUESTION; each answer fed back is recorded, and
    the ``asks``-th answer lets the workflow go on (the real start runs then, as
    the workflow resumed by the answer does). Every answer, over all Saves."""
    real_start = world.runtime.start
    answered: list[str] = []
    started: list = []

    async def start(decision, event):
        started[:] = [(decision, event)]
        return _asking(decision)

    async def answer(text):
        answered.append(text)
        decision, event = started[0]
        if len(answered) < asks:
            return _asking(decision)
        return await real_start(decision, event)

    world.runtime.start = start
    make = world.gateway

    def gateway(text, *a, **kw):
        gw = make(text, *a, **kw)
        gw.answer_question = answer
        return gw

    world.gateway = gateway
    return answered


async def _tap(world, reply, title):
    rows = [*(reply.buttons or ()), *(reply.list_rows or ())]
    row = next(r for r in rows if r.title.startswith(title))
    action, draft_id, extra = dr.parse_tap(row.id)
    draft = await world.drafts.get(draft_id, world.actor.organization_id, world.actor.user_id)
    gw = world.gateway("tap")
    if action == dr.SAVE:
        return await gw.save_draft(draft)
    return await gw.answer_draft(draft, extra[0], int(extra[1]))


async def _card_then_save(world):
    result = await world.say(FakeToolCallingProvider([[CEMENT], "Check it."]), "50 bag cement vannu")
    return await _tap(world, result.reply, "✅ Save")


async def test_the_question_is_on_the_line_with_its_options_as_buttons_not_an_error(world):
    _asks_once(world)
    card = await _card_then_save(world)

    assert "Nothing was saved" not in card.text and dr.CANT_READ not in card.text
    assert f"Cement in: 50 bags (❓ {QUESTION})" in card.text
    assert card.text.count(QUESTION) == 1
    assert [t for t in titles(card) if t in ACCOUNTS] == list(ACCOUNTS)
    assert world.dispatcher.dispatched == []  # nothing written yet
    (item,) = await open_items(world)
    assert item.asked_at_save and item.state == dr.NEEDS_ANSWER


async def test_a_tap_on_the_answer_finishes_the_save_with_that_answer(world):
    answered = _asks_once(world)
    card = await _card_then_save(world)

    saved = await _tap(world, card, "Office Cash")
    assert answered == ["Office Cash"]
    assert saved.text.startswith("✅ *Saved*") and "Cement in: 50 bags" in saved.text
    assert len(world.dispatcher.dispatched) == 1  # one entry, never two


async def test_a_typed_answer_is_read_by_code_and_never_becomes_a_second_line(world):
    answered = _asks_once(world)
    await _card_then_save(world)
    draft = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)

    saved = await world.gateway("Office cash").answer_draft_typed(draft, "Office cash")
    assert saved is not None and saved.text.startswith("✅ *Saved*")
    assert answered == ["Office Cash"]
    assert len(world.dispatcher.dispatched) == 1


async def test_a_second_question_replaces_the_first_on_the_same_line(world):
    answered = _asks_once(world, asks=2)
    card = await _card_then_save(world)
    again = await _tap(world, card, "Site Cash")
    # The workflow asked once more: still one line, asking again, nothing written.
    assert again.text.count("Cement in: 50 bags") == 1 and QUESTION in again.text
    assert world.dispatcher.dispatched == []
    done = await _tap(world, again, "Site Cash")
    assert done.text.startswith("✅ *Saved*")
    assert answered == ["Site Cash", "Site Cash"]


async def test_the_answers_survive_the_store():
    item = dr.DraftItem(kind=dr.KIND_EXPENSE, tool="save_expense", args={}, answers={QUESTION: "Office Cash"})
    assert dr.DraftItem.from_json(item.to_json()).answers == {QUESTION: "Office Cash"}


# -- the pure parts -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("said", "picked"),
    [
        ("Office cash", "Office Cash"),
        ("office cash", "Office Cash"),
        ("1", "Office Cash"),
        ("5", "My own pocket"),
        ("own pocket", "My own pocket"),
        ("petty", "Site Petty Cash Float"),
    ],
)
def test_a_short_typed_reply_picks_the_one_option_it_names(said, picked):
    assert draft_answer.option_answer(said, list(ACCOUNTS)) == picked


@pytest.mark.parametrize("said", ["cash", "9", "", "paid 1500 for the tractor and 3 mason came today ok"])
def test_an_unclear_or_long_reply_picks_nothing(said):
    assert draft_answer.option_answer(said, list(ACCOUNTS)) is None


def test_the_question_title_drops_the_options_and_the_retry_preface():
    assert question_title(PROMPT) == QUESTION
    assert question_title(f"{RETRY_PREFIX} {PROMPT}") == QUESTION


def test_a_long_reason_is_cut_at_a_word_never_mid_word():
    cut = _clean(PROMPT)
    assert len(cut) <= 160 and cut.endswith("or just…")
    assert _clean("short reason") == "short reason"


# -- a day after today is asked about, on any kind of line ---------------------------


def test_a_day_after_today_is_doubted_on_every_kind_and_today_is_not():
    import datetime as dt

    from runtime.agent import checks

    today = dt.date(2026, 10, 30)
    for kind in (dr.KIND_EXPENSE, dr.KIND_MATERIAL_IN, dr.KIND_LABOUR, dr.KIND_WORK):
        found = checks.doubt(kind, {}, {"occurred_date": "2026-12-30"}, None, today=today)
        assert found is not None and found.key == "check.future_date"
        assert found.values == {"day": "30 Dec", "today": "30 Oct"}
        # The pipeline filed it as today; the date as said is still asked about.
        said = checks.doubt(kind, {"date": "2026-12-30"}, {"occurred_date": "2026-10-30"}, None, today=today)
        assert said is not None and said.key == "check.future_date"
    assert checks.doubt(dr.KIND_EXPENSE, {}, {"occurred_date": "2026-10-30"}, None, today=today) is None
    assert checks.doubt(dr.KIND_EXPENSE, {}, {"occurred_date": "2026-10-29"}, None, today=today) is None
    assert checks.doubt(dr.KIND_EXPENSE, {}, {}, None, today=today) is None


async def test_a_line_dated_after_today_waits_on_the_date_question(world):
    import datetime as dt

    later = (dt.date.today() + dt.timedelta(days=61)).isoformat()
    cement = ("save_material_receipt", {**CEMENT[1], "date": later})
    result = await world.say(FakeToolCallingProvider([[cement], "Check it."]), "50 bag cement vannu")
    # The question sits on the line it is about.
    assert "Cement in: 50 bags (❓ 📅 " in result.reply.text
    assert {"Today", "Another date"} <= set(titles(result.reply))
    (item,) = await open_items(world)
    assert item.state == dr.NEEDS_ANSWER
