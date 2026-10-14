"""BE-29: retired model names are replaced wherever they come from, and the
DeepSeek adapter keeps the old non-thinking behaviour on deepseek-flash."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

import mesiri_ai.adapters.deepseek.adapter as deepseek_module
from mesiri_ai.model_names import RETIRED_MODELS, current_model_name
from mesiri_ai.resolver import _build_deepseek_provider, _build_gemini_provider


@pytest.mark.parametrize(
    ("configured", "used"),
    [
        ("deepseek-chat", "deepseek-flash"),
        ("deepseek-reasoner", "deepseek-flash"),
        ("gemini-2.0-flash", "gemini-2.5-flash"),
        ("gemini-2.5-flash", "gemini-2.5-flash"),
        ("deepseek-flash", "deepseek-flash"),
        ("some-future-model", "some-future-model"),
        (None, None),
        ("", ""),
    ],
)
def test_retired_names_are_replaced_and_current_ones_kept(configured, used):
    assert current_model_name(configured) == used


def test_no_replacement_is_itself_retired():
    assert not set(RETIRED_MODELS.values()) & set(RETIRED_MODELS)


def _env():
    return SimpleNamespace(
        gemini=SimpleNamespace(model="gemini-2.0-flash", timeout_seconds=5, max_retries=0, max_image_edge=0),
        deepseek=SimpleNamespace(model="deepseek-chat", timeout_seconds=5, max_retries=0),
    )


def test_the_resolver_replaces_a_retired_env_or_routing_name():
    config = {"secrets": {"deepseek": {"api_key": "k"}, "gemini": {"api_key": "k"}}}
    # From the routing table (model given) and from the env (model empty).
    assert _build_deepseek_provider(config, "deepseek-chat", _env())._s.model == "deepseek-flash"
    assert _build_deepseek_provider(config, "", _env())._s.model == "deepseek-flash"
    assert _build_gemini_provider(config, "", _env())._settings.model == "gemini-2.5-flash"


async def test_deepseek_requests_turn_thinking_off(monkeypatch):
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        content = json.dumps({"translated_text": "hello", "detected_language": "en"})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        deepseek_module.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )

    async def run_once(raw, **kwargs):
        return await raw(), 1.0

    monkeypatch.setattr(deepseek_module, "call_with_resilience", run_once)

    provider = _build_deepseek_provider({"secrets": {"deepseek": {"api_key": "k"}}}, "deepseek-flash", _env())
    await provider.translate_to_english("hello", correlation_id="cor_be29")

    assert sent[0]["model"] == "deepseek-flash"
    assert sent[0]["thinking"] == {"type": "disabled"}
