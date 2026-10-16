"""WA-02: a forwarded batch gets one summary reply instead of one each."""

from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import runtime.message_journey as mj
from channel.replies import ListRow
from mesiri.domains.organizations.guardrails import TRIAL_LIMIT_MESSAGE, TrialUsageVerdict
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from runtime import forward_batch
from runtime.forward_batch import BatchingSender, ForwardBatcher, compose

WA = "919876543210"
DRAFT = "Saved as a draft. You'll confirm it with tonight's report. Reply UNDO if it's wrong."


def _text(body):
    return {"kind": "text", "body": body}


def _question(body, row_id):
    return {"kind": "button", "body": body, "buttons": [{"id": row_id, "title": "Yes", "description": ""}]}


# --- the summary --------------------------------------------------------------


def test_one_forwarded_message_keeps_its_own_reply():
    entry = [_text(f"✅ Saved: Plastering, wall 2\n\n{DRAFT}")]
    assert compose([entry]) == entry


def test_several_become_one_summary():
    sends = compose(
        [
            [_text(f"✅ Saved: Plastering, wall 2 (40 sqm)\n\n{DRAFT}")],
            [_text(f"✅ Saved: 10 workers\n{DRAFT}")],
            [_text("I couldn't read that one.")],
        ]
    )
    (summary,) = sends
    assert summary["body"] == (
        "📥 Got 3 forwarded messages:\n"
        "• ✅ Saved: Plastering, wall 2 (40 sqm)\n"
        "• ✅ Saved: 10 workers\n"
        "• I couldn't read that one.\n"
        "\n"
        "Saved ones are drafts for today; you'll confirm them with tonight's report. "
        "Reply UNDO to remove the last one."
    )


def test_only_the_last_question_is_asked_the_rest_resent():
    first_q = _question("Which site is this for?", "site_a")
    last_q = _question("Is this cement OPC or PPC?", "opc")
    sends = compose([[first_q], [_text("✅ Saved: 10 workers")], [last_q]])
    summary, question = sends
    assert "• Which site is this for? _(not saved, send it again on its own)_" in summary["body"]
    assert "• Is this cement OPC or PPC? _(question below)_" in summary["body"]
    assert question == last_q


# --- the sender wrapper -------------------------------------------------------


async def test_wrapper_holds_back_only_while_capturing():
    inner = AsyncMock()
    sender = BatchingSender(inner)
    batcher = ForwardBatcher(redis=FakeRedis(), sender=inner, window_seconds=0.05)

    with batcher.capturing() as capture:
        assert forward_batch.is_capturing()
        await sender.send_text(WA, "held")
        await sender.send_button(WA, body="Pick", buttons=(ListRow("a", "A"),))
        await sender.send_image(WA, b"png")  # not a reply: goes now
    assert not forward_batch.is_capturing()
    assert [s["kind"] for s in capture.sends] == ["text", "button"]
    assert capture.sends[1]["buttons"] == [{"id": "a", "title": "A", "description": ""}]
    inner.send_text.assert_not_awaited()
    inner.send_image.assert_awaited_once()

    await sender.send_text(WA, "now")
    inner.send_text.assert_awaited_once_with(WA, "now")


async def test_a_burst_gets_exactly_one_summary():
    inner = AsyncMock()
    batcher = ForwardBatcher(redis=FakeRedis(), sender=inner, window_seconds=0.05)
    for i in range(3):
        await batcher.finish(WA, [_text(f"✅ Saved: item {i}")], known_sender=True)
    inner.send_text.assert_not_awaited()

    await asyncio.sleep(0.2)
    (call,) = inner.send_text.await_args_list
    assert call.args[1].startswith("📥 Got 3 forwarded messages:")


async def test_a_slow_message_still_joins_the_summary():
    """A voice note still being read when the quick ones finish."""
    inner = AsyncMock()
    batcher = ForwardBatcher(redis=FakeRedis(), sender=inner, window_seconds=0.05)
    for _ in range(3):
        await batcher.begin(WA)
    await batcher.finish(WA, [_text("✅ Saved: item 1")], known_sender=True)
    await batcher.finish(WA, [_text("✅ Saved: item 2")], known_sender=True)
    await asyncio.sleep(0.2)  # well past the window, but one is still in progress
    inner.send_text.assert_not_awaited()

    await batcher.finish(WA, [_text("✅ Saved: voice note")], known_sender=True)
    await asyncio.sleep(0.2)
    (call,) = inner.send_text.await_args_list
    assert call.args[1].startswith("📥 Got 3 forwarded messages:")


async def test_the_question_is_replayed_as_a_real_button():
    inner = AsyncMock()
    batcher = ForwardBatcher(redis=FakeRedis(), sender=inner, window_seconds=0.05)
    await batcher.finish(WA, [_text("✅ Saved: 10 workers")], known_sender=True)
    await batcher.finish(WA, [_question("OPC or PPC?", "opc")], known_sender=True)
    await asyncio.sleep(0.2)
    inner.send_text.assert_awaited_once()
    (button,) = inner.send_button.await_args_list
    assert button.kwargs["body"] == "OPC or PPC?"
    assert button.kwargs["buttons"] == [ListRow("opc", "Yes", "")]


async def test_someone_not_on_mesiri_is_answered_straight_away():
    inner = AsyncMock()
    batcher = ForwardBatcher(redis=FakeRedis(), sender=inner, window_seconds=60)
    await batcher.finish(WA, [_text("This number isn't registered.")], known_sender=False)
    inner.send_text.assert_awaited_once_with(WA, "This number isn't registered.")


async def test_a_lost_summary_goes_with_the_next_message():
    inner = AsyncMock()
    redis = FakeRedis()
    batcher = ForwardBatcher(redis=redis, sender=inner, window_seconds=0.05)
    # As if the process restarted: the batch is in Redis, no timer running.
    await redis.set_json(
        f"fwd_batch:{WA}",
        {"seq": 2, "entries": [[_text("a")], [_text("b")]], "last_at": 0},
    )
    assert await batcher.flush(WA, stale_only=True)
    assert inner.send_text.await_args.args[1].startswith("📥 Got 2 forwarded messages:")
    assert not await batcher.flush(WA, stale_only=True)  # gone


# --- through the message journey ----------------------------------------------


class _OverCap:
    async def check(self, organization_id):
        return TrialUsageVerdict(over_cap=True, reason="ai_cost")


def _journey(monkeypatch, *, registered=True, window=0.05):
    async def resolve(_reader, wa_id):
        if not registered:
            return None
        return SimpleNamespace(
            organization_id=uuid.uuid4(), org_active=True, user_id=uuid.uuid4(), full_name="Ravi", projects=[]
        )

    monkeypatch.setattr(mj, "resolve_sender", resolve)
    params = inspect.signature(mj.build_message_handlers).parameters
    deps = {name: AsyncMock() for name, p in params.items() if p.default is inspect.Parameter.empty}
    inner = deps["sender"]
    deps["sender"] = BatchingSender(inner)
    batcher = ForwardBatcher(redis=FakeRedis(), sender=inner, window_seconds=window)
    on_normalized, _ = mj.build_message_handlers(
        **deps, trial_usage_guard=_OverCap(), forward_batcher=batcher, signup_journey=None
    )
    return on_normalized, inner


def _message(i, *, forwarded=True):
    return NormalizedMessage(
        message_id=f"wamid.in.{i}",
        sender=SenderInfo(wa_id=WA, profile_name="Ravi"),
        timestamp=dt.datetime(2026, 10, 16, 6, tzinfo=dt.UTC),
        modality=InputModality.TEXT,
        text=f"update {i}",
        metadata={"forwarded": True} if forwarded else {},
    )


async def test_journey_forwarded_burst_gets_one_summary(monkeypatch):
    on_normalized, inner = _journey(monkeypatch)
    for i in range(3):
        await on_normalized(_message(i), {})
    inner.send_text.assert_not_awaited()  # nothing yet

    await asyncio.sleep(0.2)
    (call,) = inner.send_text.await_args_list
    assert call.args[1].startswith("📥 Got 3 forwarded messages:")
    assert TRIAL_LIMIT_MESSAGE.splitlines()[0][:40] in call.args[1]


async def test_journey_typed_messages_are_answered_as_before(monkeypatch):
    on_normalized, inner = _journey(monkeypatch)
    await on_normalized(_message(1, forwarded=False), {})
    inner.send_text.assert_awaited_once_with(WA, TRIAL_LIMIT_MESSAGE)


@pytest.mark.parametrize("registered", [False])
async def test_journey_unregistered_forward_is_answered_straight_away(monkeypatch, registered):
    on_normalized, inner = _journey(monkeypatch, registered=registered, window=60)
    await on_normalized(_message(1), {})
    inner.send_text.assert_awaited_once()  # no 60 s wait for a stranger
