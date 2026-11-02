"""WA-143: a provider's "spending budget used up" refusal is told apart from a rate limit.

2 Nov 2026: Gemini answered every call with 429 RESOURCE_EXHAUSTED "Your project has exceeded its
monthly spending cap" for two hours. It was mapped like a passing rate limit (retryable, alert only
after 5 failures, "being retried"), though nothing works until a person raises the cap.
Guards: an ordinary 429 rate limit stays retryable; 401/402/403 stay as before.
"""

from __future__ import annotations

from mesiri_ai.core.errors import AUTH_OR_QUOTA_ERROR_CODE, is_budget_exhausted, map_provider_error
from mesiri_ai.core.failures import FailureAlertPolicy, ProviderFailure

CAP = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'Your project has exceeded its monthly "
       "spending cap. Please go to AI Studio at https://ai.studio/spend to manage your project spend cap.'}}")


class _Err(Exception):
    def __init__(self, code: int, text: str) -> None:
        super().__init__(text)
        self.code = code


def test_the_spending_cap_needs_a_person_and_is_not_retried() -> None:
    err = map_provider_error("gemini", _Err(429, CAP))
    assert err.error_code == AUTH_OR_QUOTA_ERROR_CODE and err.retryable is False
    assert err.details["budget_exhausted"] is True and err.details["status_code"] == 429


def test_guard_a_plain_rate_limit_is_still_retried() -> None:
    err = map_provider_error("gemini", _Err(429, "429 RESOURCE_EXHAUSTED. Quota exceeded for requests per minute"))
    assert err.retryable is True and "budget_exhausted" not in err.details
    assert not is_budget_exhausted(_Err(500, "billing service hiccup"))  # only 402 / 429


def test_guard_auth_errors_unchanged() -> None:
    err = map_provider_error("gemini", _Err(403, "permission denied"))
    assert err.error_code == AUTH_OR_QUOTA_ERROR_CODE and "budget_exhausted" not in err.details


def test_the_first_cap_failure_alerts_at_once_and_says_what_to_do() -> None:
    policy = FailureAlertPolicy()
    text = policy.record(ProviderFailure("gemini", "run_tools", AUTH_OR_QUOTA_ERROR_CODE, 429, budget_exhausted=True),
                         now=0.0)
    assert text and "spending budget is used up" in text and "AI Studio" in text
    # once an hour, not per message
    assert policy.record(ProviderFailure("gemini", "run_tools", AUTH_OR_QUOTA_ERROR_CODE, 429, budget_exhausted=True),
                         now=10.0) is None
