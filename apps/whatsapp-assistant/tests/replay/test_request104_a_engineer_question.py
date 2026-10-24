"""Request 104, A2: "Ask the engineer when the 2nd floor drawings will come".

It used to answer "I've passed your question to the engineer" while only a
low-severity open issue was saved and nobody was messaged. Now it is a card,
"Send to engineer: <question>"; the Send tap WhatsApps the site's engineer(s)
(else the project's managers) through the notification queue and the reply says
who got it. It is not an issue: nothing is written to the site issues.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")

from tests.replay.test_agent_replay import _make_world  # noqa: E402
from tests.unit.request104_fakes import ENGINEER, MANAGER, FakeActions, MemoryRedis  # noqa: E402

from context import seed  # noqa: E402
from mesiri_ai.fakes import FakeToolCallingProvider  # noqa: E402
from runtime.agent import save_button as sb  # noqa: E402
from runtime.agent.cards import CardStore  # noqa: E402

ASK = "Ask the engineer when the 2nd floor drawings will come"
QUESTION = "When will the 2nd floor drawings come?"


async def _prepared(people, outcomes=None):  # noqa: ANN001, ANN202
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.actions = FakeActions(people=people, outcomes=outcomes)
    provider = FakeToolCallingProvider(
        [[("note_for_engineer", {"question": QUESTION})], "I can send your question about the drawings. Check it and tap Send."]
    )
    result = await world.say(provider, ASK)
    return world, result


def _tap(world, action):  # noqa: ANN001, ANN202
    facts = world.last_gateway.action_facts()
    return SimpleNamespace(metadata={"interactive_reply_id": sb.tap_id(action, facts)})


async def test_the_question_is_a_send_card_and_nothing_goes_before_the_tap():
    world, result = await _prepared([ENGINEER])
    assert "📝 Send to engineer: " + QUESTION in result.reply.text
    assert "passed" not in result.reply.text.lower() and "Saved" not in result.reply.text
    assert world.actions.delivered == []
    # Nothing is written as an issue.
    assert world.dispatcher.dispatched == []
    assert len(world.last_gateway.action_items) == 1
    spec = sb.with_save_buttons(result.reply, world.last_gateway.action_facts(), save_title=sb.SEND_TITLE)
    assert [row.title for row in spec.buttons] == ["✅ Send", "❌ Cancel"]


async def test_send_messages_the_engineer_and_the_reply_says_who():
    world, _ = await _prepared([ENGINEER, MANAGER])
    reply = await sb.handle_tap(
        _tap(world, sb.SAVE), world.actor, world.handler, actions=world.actions, sender=object()
    )
    assert [p["name"] for p in world.actions.delivered] == ["Ravi", "Priya"]
    assert "Ravi (site engineer)" in reply.text and "Priya (project manager)" in reply.text
    assert reply.text.startswith("✅ Sent to")
    assert "When will the 2nd floor drawings come?" in world.actions.sent_text[0]


async def test_a_second_tap_sends_nothing_more():
    world, _ = await _prepared([ENGINEER])
    tap = _tap(world, sb.SAVE)
    await sb.handle_tap(tap, world.actor, world.handler, actions=world.actions, sender=object())
    again = await sb.handle_tap(tap, world.actor, world.handler, actions=world.actions, sender=object())
    assert len(world.actions.delivered) == 1
    assert again.text == sb.ALREADY_DONE


async def test_cancel_sends_nothing():
    world, _ = await _prepared([ENGINEER])
    reply = await sb.handle_tap(
        _tap(world, sb.CANCEL), world.actor, world.handler, actions=world.actions, sender=object()
    )
    assert world.actions.delivered == []
    assert reply.text == sb.CANCELLED_DONE


async def test_someone_who_cannot_receive_it_is_named_not_claimed():
    """Outside WhatsApp's 24 h window the queue skips the row: the reply never
    says "sent" for it."""
    world, _ = await _prepared(
        [ENGINEER, MANAGER], outcomes={MANAGER["user_id"]: "outside_whatsapp_session_window_needs_template"}
    )
    reply = await sb.handle_tap(
        _tap(world, sb.SAVE), world.actor, world.handler, actions=world.actions, sender=object()
    )
    assert reply.text.startswith("✅ Sent to Ravi (site engineer).")
    assert "Not delivered: Priya hasn't messaged Mesiri in the last 24 hours" in reply.text


async def test_nobody_reachable_is_said_plainly_with_no_card():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.actions = FakeActions(people=[])
    provider = FakeToolCallingProvider(
        [[("note_for_engineer", {"question": QUESTION})], "I've passed your question to the engineer."]
    )
    result = await world.say(provider, ASK)
    assert world.last_gateway.action_items == []
    assert "nobody to send it to" in result.reply.text.lower()
    assert "passed" not in result.reply.text.lower()
    assert result.reply.buttons is None


async def test_the_card_is_kept_so_undo_cancels_it_before_the_tap():
    world, _ = await _prepared([ENGINEER])
    cards = CardStore(MemoryRedis())
    gateway = world.last_gateway
    from runtime.agent.cards import OPEN, new_card

    gateway.cards = cards
    await cards.put(world.actor, new_card(OPEN, list(gateway.card_items)))
    step = await gateway.undo_card([])
    assert step.status == "undone"
    again = await sb.handle_tap(
        _tap(world, sb.SAVE), world.actor, world.handler, cards, actions=world.actions, sender=object()
    )
    assert world.actions.delivered == []
    assert again.text == sb.ALREADY_DONE
