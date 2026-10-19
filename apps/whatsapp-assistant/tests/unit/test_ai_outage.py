"""AI outage handling (request [37] item 1) and its team alert (item 2)."""

from __future__ import annotations

import logging

import pytest

from mesiri_ai.core.errors import AUTH_OR_QUOTA_ERROR_CODE
from mesiri_ai.core.failures import FailureAlertPolicy, ProviderFailure
from mesiri_contracts.assistant.confidence import ConfidenceLevel
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.understanding_result import ProviderExecution, UnderstandingResult
from runtime.ai_failure_alert import AIFailureAlerter
from runtime.ai_outage import (
    GAVE_UP_REPLY,
    MAX_ATTEMPTS,
    QUEUED_REPLY,
    RESEND_REPLY,
    is_ai_outage,
    reply_for_attempt,
)


def _understanding(confidence, *executions) -> UnderstandingResult:
    return UnderstandingResult(
        source_message_id="m",
        correlation_id="c",
        input_modality=InputModality.TEXT,
        overall_confidence=confidence,
        provider_executions=list(executions),
    )


def _failed(code: str) -> ProviderExecution:
    return ProviderExecution(provider="deepseek", operation="understand", succeeded=False, error_code=code)


@pytest.mark.parametrize("code", [AUTH_OR_QUOTA_ERROR_CODE, "PROVIDER_ERROR", "PROVIDER_TIMEOUT", "PROVIDER_UNAVAILABLE"])
def test_an_unusable_result_with_a_failed_provider_call_is_an_outage(code):
    assert is_ai_outage(_understanding(ConfidenceLevel.UNUSABLE, _failed(code)))


def test_unusable_without_a_provider_failure_is_just_not_understood():
    assert not is_ai_outage(_understanding(ConfidenceLevel.UNUSABLE))
    assert not is_ai_outage(_understanding(ConfidenceLevel.UNUSABLE, _failed("PROVIDER_MALFORMED_OUTPUT")))


def test_a_usable_result_is_never_an_outage():
    assert not is_ai_outage(_understanding(ConfidenceLevel.HIGH, _failed("PROVIDER_ERROR")))


def test_what_the_sender_is_told_on_each_attempt():
    assert reply_for_attempt(1) == (QUEUED_REPLY, True)
    assert reply_for_attempt(2) == ("", True)  # already told; quiet until it works
    assert reply_for_attempt(MAX_ATTEMPTS) == (GAVE_UP_REPLY, False)
    assert reply_for_attempt(None) == (RESEND_REPLY, False)  # no retry queue to promise
    assert "few minutes" in QUEUED_REPLY


async def test_alert_goes_to_the_log_and_only_to_the_group_when_switched_on(monkeypatch, caplog):
    posts: list[str] = []

    class _Notifier:
        async def post(self, text, **kwargs):
            posts.append(text)
            return True

    failure = ProviderFailure("deepseek", "extract", AUTH_OR_QUOTA_ERROR_CODE, status_code=402)

    monkeypatch.delenv("MESIRI_AI_ALERT_TEAM_GROUP", raising=False)
    with caplog.at_level(logging.WARNING, logger="mesiri.ai_failure_alert"):
        await AIFailureAlerter(_Notifier()).on_failure(failure)
    assert "402" in caplog.text and posts == []

    monkeypatch.setenv("MESIRI_AI_ALERT_TEAM_GROUP", "1")
    await AIFailureAlerter(_Notifier()).on_failure(failure)
    assert len(posts) == 1 and "402" in posts[0]


async def test_the_alerter_sends_one_alert_an_hour():
    clock = {"t": 0.0}
    alerter = AIFailureAlerter(None, policy=FailureAlertPolicy(), clock=lambda: clock["t"])
    seen: list[str | None] = []
    original = alerter._policy.record
    alerter._policy.record = lambda f, now: (seen.append(original(f, now=now)) or seen[-1])  # type: ignore[method-assign]
    failure = ProviderFailure("gemini", "extract", AUTH_OR_QUOTA_ERROR_CODE, status_code=403)
    for t in (0.0, 60.0, 3700.0):
        clock["t"] = t
        await alerter.on_failure(failure)
    assert [s is not None for s in seen] == [True, False, True]
