"""BE-25: reading usage from provider responses and handing it to the sink."""

from __future__ import annotations

import asyncio
import struct
from types import SimpleNamespace

import pytest

from mesiri_ai import usage


@pytest.fixture(autouse=True)
def _no_sink():
    yield
    usage.set_usage_sink(None)


def test_gemini_usage_adds_thinking_to_output_and_splits_audio() -> None:
    response = SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=1200,
            candidates_token_count=80,
            thoughts_token_count=20,
            cached_content_token_count=None,
            prompt_tokens_details=[
                SimpleNamespace(modality="TEXT", token_count=200),
                SimpleNamespace(modality=SimpleNamespace(), token_count=0),
                SimpleNamespace(modality="MediaModality.AUDIO", token_count=1000),
            ],
        )
    )
    assert usage.gemini_usage(response) == {
        "input_tokens": 1200,
        "cached_input_tokens": None,
        "audio_input_tokens": 1000,
        "output_tokens": 100,
    }


def test_gemini_without_usage_metadata() -> None:
    assert usage.gemini_usage(SimpleNamespace()) == {}


def test_deepseek_usage() -> None:
    raw = {
        "usage": {
            "prompt_tokens": 900,
            "completion_tokens": 50,
            "prompt_cache_hit_tokens": 640,
            "prompt_cache_miss_tokens": 260,
        }
    }
    assert usage.openai_style_usage(raw) == {
        "input_tokens": 900,
        "cached_input_tokens": 640,
        "output_tokens": 50,
    }
    assert usage.openai_style_usage({}) == {}


def _ogg_page(granule: int, payload: bytes) -> bytes:
    # Enough of an Ogg page header for the duration reader: magic, version,
    # flags, granule position.
    return b"OggS" + b"\x00\x00" + struct.pack("<q", granule) + b"\x00" * 13 + payload


def test_ogg_opus_duration_uses_48khz_minus_pre_skip() -> None:
    head = b"OpusHead" + b"\x01\x01" + struct.pack("<H", 312) + b"\x00" * 8
    audio = _ogg_page(0, head) + _ogg_page(48000 * 7 + 312, b"")
    assert usage.ogg_duration_seconds(audio) == pytest.approx(7.0)


def test_non_ogg_audio_has_no_duration() -> None:
    assert usage.ogg_duration_seconds(b"RIFF....WAVE") is None


async def test_report_tags_the_scope_and_never_raises() -> None:
    received: list[usage.ProviderUsage] = []

    async def sink(u: usage.ProviderUsage) -> None:
        received.append(u)

    usage.set_usage_sink(sink)
    with usage_scope_for("org-1", "dpr"):
        usage.report(usage.ProviderUsage(provider="gemini", operation="extract", model="m"))
    await usage.drain()
    assert [(u.organization_id, u.purpose) for u in received] == [("org-1", "dpr")]

    async def broken(_: usage.ProviderUsage) -> None:
        raise RuntimeError("db down")

    usage.set_usage_sink(broken)
    usage.report(usage.ProviderUsage(provider="gemini", operation="extract", model="m"))
    await usage.drain()  # logged, not raised

    def broken_sync(_: usage.ProviderUsage) -> None:
        raise RuntimeError("bad sink")

    usage.set_usage_sink(broken_sync)
    usage.report(usage.ProviderUsage(provider="gemini", operation="extract", model="m"))


def usage_scope_for(org: str, purpose: str):
    return usage.usage_scope(organization_id=org, purpose=purpose)


async def test_no_sink_drops_reports() -> None:
    usage.report(usage.ProviderUsage(provider="gemini", operation="extract", model="m"))
    await asyncio.sleep(0)


async def test_gemini_adapter_reports_each_call(monkeypatch) -> None:
    from mesiri_ai.adapters.gemini.adapter import GeminiProvider

    class _Models:
        async def generate_content(self, **kwargs):
            return SimpleNamespace(
                text='{"translated_text": "two bags cement", "detected_language": "ml"}',
                usage_metadata=SimpleNamespace(
                    prompt_token_count=300,
                    candidates_token_count=12,
                    thoughts_token_count=None,
                    cached_content_token_count=None,
                    prompt_tokens_details=None,
                ),
            )

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._settings = SimpleNamespace(model="gemini-2.5-flash", timeout_seconds=5, max_retries=0)
    provider._client = SimpleNamespace(aio=SimpleNamespace(models=_Models()))
    received: list[usage.ProviderUsage] = []
    usage.set_usage_sink(received.append)

    await provider.translate_to_english("രണ്ട് ബാഗ് സിമന്റ്", correlation_id="cor_g")

    [call] = received
    assert (call.provider, call.operation, call.model, call.correlation_id) == (
        "gemini",
        "translate",
        "gemini-2.5-flash",
        "cor_g",
    )
    assert (call.input_tokens, call.output_tokens) == (300, 12)


async def test_deepseek_adapter_reports_each_call(monkeypatch) -> None:
    import mesiri_ai.adapters.deepseek.adapter as deepseek_module
    from mesiri_ai.adapters.deepseek.adapter import DeepSeekExtractionProvider

    provider = DeepSeekExtractionProvider.__new__(DeepSeekExtractionProvider)
    provider._s = SimpleNamespace(
        api_key=None,
        base_url="https://example.test",
        timeout_seconds=5,
        max_retries=0,
        model="deepseek-flash",
    )

    async def _fake_resilience(_raw, **kwargs):
        return {
            "choices": [{"message": {"content": '{"is_multi_intent": false, "segments": []}'}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 30, "prompt_cache_hit_tokens": 448},
        }, 40.0

    monkeypatch.setattr(deepseek_module, "call_with_resilience", _fake_resilience)
    received: list[usage.ProviderUsage] = []
    usage.set_usage_sink(received.append)

    await provider.decompose("40 bags cement", correlation_id="cor_d")

    [call] = received
    assert (call.provider, call.operation, call.model) == ("deepseek", "decompose", "deepseek-flash")
    assert (call.input_tokens, call.cached_input_tokens, call.output_tokens) == (500, 448, 30)


async def test_sarvam_adapter_reports_audio_seconds(monkeypatch) -> None:
    import mesiri_ai.adapters.sarvam.adapter as sarvam_module
    from mesiri_ai.adapters.sarvam.adapter import SarvamSpeechProvider

    provider = SarvamSpeechProvider.__new__(SarvamSpeechProvider)
    provider._settings = SimpleNamespace(timeout_seconds=5, max_retries=0)
    provider._client = object()

    async def _fake_resilience(_raw, **kwargs):
        return {"transcript": "two bags", "language_code": "ml-IN"}, 900.0

    monkeypatch.setattr(sarvam_module, "call_with_resilience", _fake_resilience)
    received: list[usage.ProviderUsage] = []
    usage.set_usage_sink(received.append)
    head = b"OpusHead" + b"\x01\x01" + struct.pack("<H", 0) + b"\x00" * 8

    await provider.transcribe(_ogg_page(0, head) + _ogg_page(48000 * 4, b""))

    [call] = received
    assert call.provider == "sarvam"
    assert call.audio_seconds == pytest.approx(4.0)
