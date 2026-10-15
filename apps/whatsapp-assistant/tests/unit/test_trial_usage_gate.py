"""SS-09: a trial company over today's usage cap is paused before any AI runs."""

from __future__ import annotations

import datetime as dt
import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import runtime.message_journey as mj
from mesiri.domains.organizations.guardrails import TRIAL_LIMIT_MESSAGE, TrialUsageVerdict
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo

ORG = uuid.uuid4()


class _Guard:
    def __init__(self, over: bool) -> None:
        self.over = over
        self.asked: list = []

    async def check(self, organization_id):
        self.asked.append(organization_id)
        return TrialUsageVerdict(over_cap=self.over, reason="ai_cost" if self.over else None)


def _handlers(monkeypatch, guard, trial_journey=None):
    async def fake_resolve(_reader, wa_id):
        return SimpleNamespace(
            organization_id=ORG,
            org_active=True,
            user_id=uuid.uuid4(),
            full_name="Ravi",
            projects=[],
        )

    monkeypatch.setattr(mj, "resolve_sender", fake_resolve)
    # Past the gate is the real journey; stop it at its first step so an
    # under-cap message is seen to continue without running the rest.
    reached = MagicMock(side_effect=RuntimeError("past the gate"))
    monkeypatch.setattr(mj.workflow_registry, "set_enabled_modules", reached)

    params = inspect.signature(mj.build_message_handlers).parameters
    deps = {
        name: AsyncMock()
        for name, p in params.items()
        if p.default is inspect.Parameter.empty
    }
    sender = deps["sender"]
    on_normalized, _ = mj.build_message_handlers(
        **deps, trial_usage_guard=guard, trial_journey=trial_journey
    )
    return on_normalized, sender, reached


def _message():
    return NormalizedMessage(
        message_id="wamid.in.1",
        sender=SenderInfo(wa_id="919876543210", profile_name="Ravi"),
        timestamp=dt.datetime(2026, 10, 15, 6, tzinfo=dt.UTC),
        modality=InputModality.TEXT,
        text="10 masons today",
    )


@pytest.mark.asyncio
async def test_over_cap_trial_gets_the_limit_reply_and_nothing_else(monkeypatch) -> None:
    guard = _Guard(over=True)
    on_normalized, sender, reached = _handlers(monkeypatch, guard)

    await on_normalized(_message(), {})

    assert guard.asked == [ORG]
    sent = [c.args[1] for c in sender.send_text.await_args_list]
    assert sent == [TRIAL_LIMIT_MESSAGE]
    reached.assert_not_called()


@pytest.mark.asyncio
async def test_under_cap_continues_into_the_journey(monkeypatch) -> None:
    guard = _Guard(over=False)
    on_normalized, sender, reached = _handlers(monkeypatch, guard)

    # The stop placed just past the gate is reached: the journey went on.
    with pytest.raises(RuntimeError, match="past the gate"):
        await on_normalized(_message(), {})

    assert guard.asked == [ORG]
    reached.assert_called_once()
    assert TRIAL_LIMIT_MESSAGE not in [c.args[1] for c in sender.send_text.await_args_list]


@pytest.mark.asyncio
async def test_over_cap_owner_can_still_ask_to_continue(monkeypatch) -> None:
    from channel.replies import ReplySpec

    class _TrialJourney:
        async def handle_continue(self, message, ctx):
            return ReplySpec(text="Thanks! Our team will call you.")

    guard = _Guard(over=True)
    on_normalized, sender, reached = _handlers(monkeypatch, guard, _TrialJourney())

    await on_normalized(_message(), {})

    sent = [c.args[1] for c in sender.send_text.await_args_list]
    assert sent == ["Thanks! Our team will call you."]
    reached.assert_not_called()
