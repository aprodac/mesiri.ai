"""Request 57, A5: a failure is retried once where that is safe, and always
told to the sender honestly."""

from __future__ import annotations

from interactions.response_handler import FAILED_REPLY, render_execution_reply
from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from runtime.inbound_journey._shared import _send_with_one_retry
from runtime.reply_language import localize_fixed_reply


def test_a_failed_save_says_nothing_was_recorded_and_does_not_promise_a_retry():
    text = render_execution_reply(
        ExecutionResult(status=ExecutionStatus.FAILED, idempotency_key="k")
    )
    assert text == FAILED_REPLY
    assert "retry" not in text.lower()
    assert "nothing was recorded" in text
    # and it reaches Malayalam / Hindi senders in their language
    assert localize_fixed_reply(text, "Malayalam") != text
    assert localize_fixed_reply(text, "Hindi") != text


async def test_a_document_send_is_tried_twice_before_giving_up():
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")

    assert await _send_with_one_retry(flaky, what="t", correlation_id="c") is True
    assert len(calls) == 2


async def test_two_failures_return_false_so_the_sender_is_told():
    calls = []

    async def always():
        calls.append(1)
        raise RuntimeError("boom")

    assert await _send_with_one_retry(always, what="t", correlation_id="c") is False
    assert len(calls) == 2
