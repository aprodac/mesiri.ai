"""When the routed text provider fails, the other one answers (19 Oct: the
DeepSeek account was never recharged, every call failed, every message got
the greeting menu); an unpaid/invalid key is not retried; the team is told."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from mesiri_ai.core import failures
from mesiri_ai.core.errors import AUTH_OR_QUOTA_ERROR_CODE, map_provider_error
from mesiri_ai.core.failures import FailureAlertPolicy, ProviderFailure
from mesiri_ai.core.fallback import call_with_resilience
from mesiri_ai.models import DecompositionResult
from mesiri_ai.resolver import DynamicAIProviderResolver
from mesiri_contracts.common.errors import MesiriError


class _Section:
    def __init__(self, api_key=None, model="m"):
        from pydantic import SecretStr

        self.api_key = SecretStr(api_key) if api_key else None
        self.model = model
        self.base_url = "https://api.deepseek.com"
        self.timeout_seconds = 5.0
        self.max_retries = 1


class _Settings:
    def __init__(self, *, gemini=True, deepseek=True):
        self.gemini = _Section("g-key" if gemini else None, "gemini-default")
        self.deepseek = _Section("d-key" if deepseek else None, "ds-default")
        self.sarvam = _Section(None)


def _resolver(settings):
    redis = AsyncMock()
    redis.get.return_value = None
    db = MagicMock()
    del db.transaction
    return DynamicAIProviderResolver(db, redis, settings)


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    return httpx.HTTPStatusError(
        "boom", request=request, response=httpx.Response(status, request=request)
    )


# --- error mapping ---------------------------------------------------------


@pytest.mark.parametrize("status", [401, 402, 403])
def test_auth_and_quota_statuses_are_not_retryable(status):
    err = map_provider_error("deepseek", _http_error(status))
    assert err.error_code == AUTH_OR_QUOTA_ERROR_CODE
    assert err.retryable is False
    assert err.details["status_code"] == status


def test_server_errors_stay_retryable_and_carry_the_status():
    err = map_provider_error("deepseek", _http_error(503))
    assert err.retryable is True
    assert err.details["status_code"] == 503


async def test_a_402_burns_one_attempt_not_the_whole_retry_budget():
    attempts = {"n": 0}

    async def unpaid():
        attempts["n"] += 1
        raise _http_error(402)

    with pytest.raises(MesiriError) as exc:
        await call_with_resilience(
            unpaid, provider="deepseek", operation="extract", timeout_seconds=1.0, max_retries=5
        )
    assert exc.value.error_code == AUTH_OR_QUOTA_ERROR_CODE
    assert attempts["n"] == 1


async def test_failed_calls_are_reported_with_their_status():
    seen: list[ProviderFailure] = []
    failures.set_failure_sink(seen.append)
    try:

        async def unpaid():
            raise _http_error(402)

        with pytest.raises(MesiriError):
            await call_with_resilience(
                unpaid, provider="deepseek", operation="extract", timeout_seconds=1.0
            )
    finally:
        failures.set_failure_sink(None)
    assert [(f.provider, f.operation, f.status_code) for f in seen] == [("deepseek", "extract", 402)]
    assert seen[0].needs_a_person


# --- fallback --------------------------------------------------------------


class _Failing:
    provider = "deepseek"

    async def extract(self, text, **kw):
        raise map_provider_error("deepseek", _http_error(402))

    async def decompose(self, text, **kw):
        raise map_provider_error("deepseek", _http_error(402))

    async def translate_to_english(self, text, **kw):
        raise map_provider_error("deepseek", _http_error(402))


class _GeminiOk:
    provider = "gemini"

    def __init__(self):
        self.calls = 0

    async def decompose(self, text, **kw):
        self.calls += 1
        return DecompositionResult(is_multi_intent=False, provider="gemini")


async def test_default_route_falls_back_to_the_other_provider():
    resolver = _resolver(_Settings())
    gemini = _GeminiOk()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("mesiri_ai.resolver._build_deepseek_provider", lambda *a, **k: _Failing())
        mp.setattr("mesiri_ai.resolver._build_gemini_provider", lambda *a, **k: gemini)
        result = await resolver.decompose("anything", correlation_id="c1")
    assert result.provider == "gemini"
    assert gemini.calls == 1


async def test_both_providers_failing_raises_instead_of_inventing_an_answer():
    resolver = _resolver(_Settings())

    class _GeminiDown(_GeminiOk):
        async def decompose(self, text, **kw):
            raise map_provider_error("gemini", _http_error(503))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("mesiri_ai.resolver._build_deepseek_provider", lambda *a, **k: _Failing())
        mp.setattr("mesiri_ai.resolver._build_gemini_provider", lambda *a, **k: _GeminiDown())
        with pytest.raises(MesiriError):
            await resolver.decompose("anything")


async def test_no_second_provider_configured_means_no_fallback():
    resolver = _resolver(_Settings(gemini=False))
    config = await resolver._resolve_config()
    assert resolver._fallback_for(config, config["routing"]["extraction"]) == (None, "")


async def test_gemini_routed_falls_back_to_deepseek():
    resolver = _resolver(_Settings())
    config = json.loads(json.dumps(await resolver._resolve_config()))
    route = {"provider_id": "gemini", "model": "x"}
    assert resolver._fallback_for(config, route) == ("deepseek", "ds-default")


async def test_an_explicit_route_fallback_wins():
    resolver = _resolver(_Settings())
    config = await resolver._resolve_config()
    route = {"provider_id": "deepseek", "fallback_provider_id": "gemini", "fallback_model": "pick"}
    assert resolver._fallback_for(config, route) == ("gemini", "pick")


# --- alert threshold -------------------------------------------------------


def _fail(status=None) -> ProviderFailure:
    return ProviderFailure("deepseek", "extract", "PROVIDER_ERROR", status_code=status)


def test_four_failures_in_ten_minutes_do_not_alert_five_do():
    policy = FailureAlertPolicy()
    assert [policy.record(_fail(), now=t * 60.0) for t in range(4)] == [None] * 4
    assert policy.record(_fail(), now=4 * 60.0) is not None


def test_failures_spread_over_more_than_the_window_do_not_add_up():
    policy = FailureAlertPolicy()
    assert all(policy.record(_fail(), now=t * 200.0) is None for t in range(10))


@pytest.mark.parametrize("status", [401, 402, 403])
def test_a_single_auth_or_quota_failure_alerts_at_once(status):
    text = FailureAlertPolicy().record(_fail(status), now=0.0)
    assert text is not None and str(status) in text


def test_one_alert_per_hour():
    policy = FailureAlertPolicy()
    assert policy.record(_fail(402), now=0.0) is not None
    assert policy.record(_fail(402), now=1800.0) is None
    assert policy.record(_fail(402), now=3599.0) is None
    assert policy.record(_fail(402), now=3601.0) is not None
