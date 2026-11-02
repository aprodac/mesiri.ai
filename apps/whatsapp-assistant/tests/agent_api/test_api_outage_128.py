"""WA-128: a v3 failure goes through v2's outage handling, never a bare "send it again".

Live 2 Nov 11:02: "Hy" and "Its really bad" both got "I couldn't work on that just now" because
the model failed (Gemini cap). Now: a provider outage is retried quickly, then queued in the
sender's language with an ARQ retry; a bug in v3 or a tool falls back to v2; a greeting is
answered by the code.
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
from runtime.ai_outage import AIUnavailableError, FallBackToV2

CTX = SimpleNamespace(user_id=USER, organization_id=ORG, role="PROJECT_MANAGER", full_name="Adarsh",
                      timezone="Asia/Kolkata", projects=[], sites=[])


def _quota() -> MesiriError:
    return MesiriError(error_code=ai_outage.AUTH_OR_QUOTA_ERROR_CODE, category=ErrorCategory.PROVIDER,
                       retryable=False, user_safe_message="x", internal_message="spending cap")


@pytest.fixture(autouse=True)
def _tools(monkeypatch):
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))
    monkeypatch.setattr(wa, "QUICK_RETRY_PAUSE_SECONDS", 0)


def _message(text: str) -> NormalizedMessage:
    return NormalizedMessage(message_id=f"wamid.{uuid.uuid4().hex[:6]}", sender=SenderInfo(wa_id="919800000000"),
                             timestamp=dt.datetime(2026, 11, 2, 5, 32, tzinfo=dt.UTC), modality=InputModality.TEXT,
                             text=text, correlation_id=f"cor_{uuid.uuid4().hex[:8]}")


def _service(error: BaseException, sent: list[ReplySpec]) -> tuple[wa.ApiWhatsApp, AsyncMock]:
    logger = AsyncMock()

    async def send(spec: ReplySpec, wa_id: str) -> None:
        sent.append(spec)

    service = wa.ApiWhatsApp(provider=FakeToolCallingProvider([], error=error), database=None, redis=FakeRedis(),
                             send=send, transcribe=None, message_logger=logger, trace_logger=AsyncMock(),
                             app=stand_in_api([]))
    return service, logger


async def test_a_provider_outage_is_queued_and_retried_in_the_worker() -> None:
    sent: list[ReplySpec] = []
    service, logger = _service(_quota(), sent)
    token = ai_outage.retry_attempt.set(1)
    try:
        with pytest.raises(AIUnavailableError):
            await service.handle(_message("Its really bad"), CTX)
    finally:
        ai_outage.retry_attempt.reset(token)
    assert [s.text for s in sent] == [ai_outage.QUEUED_REPLY]
    logger.mark_failed.assert_awaited()
    # the quick retry ran first: the agent asked the model twice (it retries once itself) per run
    assert service._agent._provider.calls >= 2


async def test_the_queued_reply_is_in_the_senders_language() -> None:
    sent: list[ReplySpec] = []
    service, _ = _service(_quota(), sent)
    token = ai_outage.retry_attempt.set(1)
    try:
        with pytest.raises(AIUnavailableError):
            await service.handle(_message("ഇന്ന് 50 ബാഗ് സിമന്റ് വന്നു"), CTX)
    finally:
        ai_outage.retry_attempt.reset(token)
    assert sent[-1].text != ai_outage.QUEUED_REPLY and "മിനിറ്റിനുള്ളിൽ" in sent[-1].text


async def test_later_attempts_are_quiet_and_the_last_says_it_gave_up() -> None:
    sent: list[ReplySpec] = []
    service, _ = _service(_quota(), sent)
    token = ai_outage.retry_attempt.set(2)
    try:
        with pytest.raises(AIUnavailableError):
            await service.handle(_message("cement came"), CTX)
        assert sent == []
        ai_outage.retry_attempt.set(ai_outage.MAX_ATTEMPTS)
        assert await service.handle(_message("cement came"), CTX) is True
    finally:
        ai_outage.retry_attempt.reset(token)
    assert [s.text for s in sent] == [ai_outage.GAVE_UP_REPLY]


async def test_outside_the_worker_the_sender_is_asked_to_resend() -> None:
    sent: list[ReplySpec] = []
    service, _ = _service(_quota(), sent)
    assert await service.handle(_message("cement came"), CTX) is True
    assert [s.text for s in sent] == [ai_outage.RESEND_REPLY]


async def test_a_bug_in_v3_or_a_tool_falls_back_to_v2_and_is_traced() -> None:
    sent: list[ReplySpec] = []
    service, _ = _service(KeyError("tool bug"), sent)
    with pytest.raises(FallBackToV2):
        await service.handle(_message("Its really bad"), CTX)
    assert sent == []
    traced = service._trace.log_stage.await_args.kwargs
    assert traced["stage"] == "agent_api_turn" and traced["succeeded"] is False
    assert traced["stage_payload"]["handled"] == "v2_fallback"


@pytest.mark.parametrize("error", [_quota(), KeyError("bug")])
@pytest.mark.parametrize("hello", ["Hy", "Hi", "hello!"])
async def test_a_greeting_never_fails_loudly(error, hello) -> None:
    """Replay of 2 Nov 11:02: "Hy" -> the greeting, whatever the model does."""
    sent: list[ReplySpec] = []
    service, logger = _service(error, sent)
    assert await service.handle(_message(hello), CTX) is True
    assert len(sent) == 1 and "send it again" not in sent[0].text and "What are you reporting" in sent[0].text
    logger.mark_completed.assert_awaited()


async def test_a_photo_the_vision_step_cannot_reach_is_queued_not_unreadable() -> None:
    sent: list[ReplySpec] = []
    service, _ = _service(_quota(), sent)

    async def describe(message, hint=None):  # noqa: ANN001, ANN202
        raise _quota()

    service._describe = describe
    msg = _message("bill").model_copy(update={"modality": InputModality.IMAGE})
    token = ai_outage.retry_attempt.set(1)
    try:
        with pytest.raises(AIUnavailableError):
            await service.handle(msg, CTX)
    finally:
        ai_outage.retry_attempt.reset(token)
    assert sent[-1].text == ai_outage.QUEUED_REPLY
