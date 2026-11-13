"""[221] (Ilan, 3 Nov 22:12-23:48 and 5 Nov 12:15-12:38): while the AI budget was used up Mesiri said "your message is
kept", then gave up after the third try (about an hour); "try again" afterwards re-ran an old request from the
history; and on 5 Nov the voice notes kept through a short pause were answered 20 minutes later with no sign of which
message the answer was about.

Now: a budget pause keeps a message for ~18 hours of tries; a late answer starts with "⏱️ Your voice note from 12:15:";
a message Mesiri still gave up on is kept and answered first, with its time, when the person next writes, and the model
is told so (a bare "try again" then prepares nothing).

Guards: any other AI failure still stops at three tries; a normal message with nothing kept is unchanged; a Save tap
never replays a kept message (it would change the card the tap is for).
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tests.agent_api.standin import ORG, STAND_IN_TOOLS, USER, stand_in_api

from agent_api import whatsapp as wa
from channel.replies import ReplySpec
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from mesiri_contracts.common.errors import ErrorCategory, MesiriError
from runtime import ai_outage

CTX = SimpleNamespace(user_id=USER, organization_id=ORG, role="ADMIN", full_name="Ilan", timezone="Asia/Kolkata",
                      projects=[], sites=[])


@pytest.fixture(autouse=True)
def _tools(monkeypatch):  # noqa: ANN001, ANN202
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))
    monkeypatch.setattr(wa, "QUICK_RETRY_PAUSE_SECONDS", 0)


def _quota() -> MesiriError:
    return MesiriError(error_code=ai_outage.AUTH_OR_QUOTA_ERROR_CODE, category=ErrorCategory.PROVIDER,
                       retryable=False, user_safe_message="x", internal_message="spending cap")


def _message(text: str, *, at: dt.datetime | None = None, tap: str | None = None) -> NormalizedMessage:
    return NormalizedMessage(
        message_id=f"wamid.{uuid.uuid4().hex[:6]}", sender=SenderInfo(wa_id="919800000000"),
        timestamp=at or dt.datetime(2026, 11, 5, 6, 45, tzinfo=dt.UTC),  # 12:15 in India
        modality=InputModality.INTERACTIVE if tap else InputModality.TEXT, text=text,
        metadata={"interactive_reply_id": tap} if tap else {}, correlation_id=f"cor_{uuid.uuid4().hex[:8]}")


def _service(model: FakeToolCallingProvider, redis: FakeRedis, sent: list[ReplySpec]) -> wa.ApiWhatsApp:
    async def send(spec: ReplySpec, wa_id: str) -> None:
        sent.append(spec)

    return wa.ApiWhatsApp(provider=model, database=None, redis=redis, send=send, transcribe=None,
                          message_logger=AsyncMock(), trace_logger=AsyncMock(), app=stand_in_api([]))


# -- the tries --------------------------------------------------------------------------------------------------------


def test_a_budget_pause_keeps_trying_past_the_third_try() -> None:
    assert ai_outage.reply_for_attempt(ai_outage.MAX_ATTEMPTS, budget=True) == ("", True)
    assert ai_outage.reply_for_attempt(ai_outage.BUDGET_MAX_ATTEMPTS, budget=True) == (ai_outage.GAVE_UP_REPLY, False)
    waits = [ai_outage.budget_defer_seconds(a) for a in range(1, ai_outage.BUDGET_MAX_ATTEMPTS)]
    assert waits[:2] == [20 * 60, 40 * 60] and max(waits) == 2 * 3600
    assert 15 * 3600 <= sum(waits) <= 24 * 3600  # "kept" means about a day, not an hour


def test_guard_any_other_ai_failure_still_stops_at_three() -> None:
    assert ai_outage.reply_for_attempt(ai_outage.MAX_ATTEMPTS) == (ai_outage.GAVE_UP_REPLY, False)


def test_the_worker_allows_the_budget_tries() -> None:
    from worker import WorkerSettings

    assert WorkerSettings.max_tries == ai_outage.BUDGET_MAX_ATTEMPTS


# -- a late answer says which message -----------------------------------------------------------------------------------


async def test_a_late_answer_starts_with_the_message_it_answers() -> None:
    sent: list[ReplySpec] = []
    service = _service(FakeToolCallingProvider(["Sheri, ithu nokkaam."]), FakeRedis(), sent)
    token = ai_outage.retry_attempt.set(2)
    try:
        await service.handle(_message("innathe stock entha"), CTX)
    finally:
        ai_outage.retry_attempt.reset(token)
    assert sent[-1].text.startswith("⏱️ 12:15-nu ayacha message:\n\n")  # Manglish by default (WA-207)


async def test_guard_an_answer_on_time_has_no_late_line() -> None:
    sent: list[ReplySpec] = []
    service = _service(FakeToolCallingProvider(["Sheri."]), FakeRedis(), sent)
    await service.handle(_message("innathe stock entha"), CTX)
    assert not sent[-1].text.startswith("⏱️")


# -- a message given up on is kept, and answered first ------------------------------------------------------------------


async def _given_up(redis: FakeRedis, sent: list[ReplySpec]) -> NormalizedMessage:
    down = _service(FakeToolCallingProvider([], error=_quota()), redis, sent)
    old = _message("innathe stock entha")
    token = ai_outage.retry_attempt.set(ai_outage.MAX_ATTEMPTS)
    try:
        assert await down.handle(old, CTX) is True
    finally:
        ai_outage.retry_attempt.reset(token)
    assert sent[-1].text != ai_outage.QUEUED_REPLY  # the give-up line (in their language), not "a few minutes"
    assert len((await down._state(CTX)).get("kept") or []) == 1
    return old


async def test_try_again_answers_the_kept_message_first_and_the_model_is_told() -> None:
    redis, sent = FakeRedis(), []
    await _given_up(redis, sent)
    sent.clear()
    # WA-283: a figure answered with no lookup is looked up again; this test is about the kept message, so the
    # scripted answer's figure is one the check leaves alone (a single digit).
    model = FakeToolCallingProvider(["Stock: 8 bags cement.", "Cheythu, mukalil kaanaam."])
    up = _service(model, redis, sent)
    await up.handle(_message("try again", at=dt.datetime(2026, 11, 5, 7, 30, tzinfo=dt.UTC)), CTX)
    assert len(sent) == 2
    assert sent[0].text.startswith("⏱️ 12:15-nu ayacha message:") and "8 bags cement" in sent[0].text
    assert not sent[1].text.startswith("⏱️")
    last_user = next(m.text for m in reversed(model.last_messages) if m.role == "user")
    assert "were just answered above" in last_user and last_user.endswith("try again")
    state = await up._state(CTX)
    assert not state.get("kept")  # answered once, never again


async def test_guard_a_tap_never_replays_a_kept_message() -> None:
    redis, sent = FakeRedis(), []
    await _given_up(redis, sent)
    sent.clear()
    up = _service(FakeToolCallingProvider(["x"]), redis, sent)
    await up.handle(_message("Save", tap=f"{wa.SAVE_PREFIX}nope"), CTX)
    assert len(sent) == 1 and not sent[0].text.startswith("⏱️")
    assert (await up._state(CTX)).get("kept")  # still kept for their next message


async def test_a_kept_message_stays_kept_while_the_ai_is_still_down() -> None:
    redis, sent = FakeRedis(), []
    await _given_up(redis, sent)
    still_down = _service(FakeToolCallingProvider([], error=_quota()), redis, [])
    token = ai_outage.retry_attempt.set(1)
    try:
        with pytest.raises(ai_outage.AIUnavailableError):
            await still_down.handle(_message("try again"), CTX)
    finally:
        ai_outage.retry_attempt.reset(token)
    assert len((await still_down._state(CTX)).get("kept") or []) == 1


def test_the_model_note_names_the_times() -> None:
    assert wa.kept_note([]) == ""
    assert "12:15, 12:18" in wa.kept_note(["12:15", "12:18"]) and "prepare nothing" in wa.kept_note(["12:15"])
