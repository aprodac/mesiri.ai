"""WA-143: when the AI account's spending budget is used up, v3 says so plainly (not "a few
minutes"), skips the useless quick retry, and the worker keeps the message for much longer.
Guard: an ordinary outage keeps the old line and spacing."""

from __future__ import annotations

import pytest
from tests.agent_api.test_api_agent_124 import CTX, _message, _service, _stand_in_tools  # noqa: F401 (autouse)

from mesiri_contracts.common.errors import ErrorCategory, MesiriError
from runtime.ai_outage import (
    BUDGET_REPLY,
    BUDGET_RETRY_DEFER_STEP_SECONDS,
    QUEUED_REPLY,
    RETRY_DEFER_STEP_SECONDS,
    AIUnavailableError,
    reply_for_attempt,
    retry_attempt,
)


def _error(budget: bool) -> MesiriError:
    return MesiriError(error_code="PROVIDER_AUTH_OR_QUOTA" if budget else "PROVIDER_ERROR",
                       category=ErrorCategory.PROVIDER, retryable=not budget, internal_message="x",
                       details={"provider": "gemini", "status_code": 429, **({"budget_exhausted": True} if budget else {})})


class _Failing:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    async def run_tools(self, *a, **k):  # noqa: ANN002, ANN003, ANN201
        self.calls += 1
        raise self.error


@pytest.mark.parametrize(("budget", "line", "calls"), [(True, BUDGET_REPLY, 1), (False, QUEUED_REPLY, 4)])
async def test_the_sender_is_told_plainly_and_the_job_is_kept(budget, line, calls) -> None:
    model = _Failing(_error(budget))
    service, sent = _service(model)
    token = retry_attempt.set(1)
    try:
        with pytest.raises(AIUnavailableError) as raised:
            await service.handle(_message("50 bags cement"), CTX)
    finally:
        retry_attempt.reset(token)
    assert raised.value.budget_exhausted is budget
    assert sent[-1].text == line
    assert model.calls == calls  # budget: one call; an outage keeps its retries (2 runs x 2 tries)


def test_the_lines() -> None:
    assert reply_for_attempt(1, budget=True) == (BUDGET_REPLY, True)
    assert reply_for_attempt(1) == (QUEUED_REPLY, True)
    assert BUDGET_RETRY_DEFER_STEP_SECONDS >= 10 * RETRY_DEFER_STEP_SECONDS
