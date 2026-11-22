"""UX-106: the narrator's ElevenLabs voice for lines made on the day (adapters/elevenlabs/voice.py)."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from mesiri_ai.adapters.elevenlabs import voice as el


def _settings(key: str | None = "k-123") -> SimpleNamespace:
    return SimpleNamespace(api_key=SecretStr(key) if key else None, voice_id=None, model=None, timeout_seconds=5.0,
                           max_retries=0)


@pytest.fixture
def sent(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"ID3audio")

    real = httpx.AsyncClient
    monkeypatch.setattr(el.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return seen


async def test_it_reads_with_the_recordings_voice_and_model(sent):
    audio = await el.ElevenLabsVoice(_settings()).speak("Meera paid ₹1,840.", "en-IN")
    assert audio == b"ID3audio"
    (req,) = sent
    assert req.url.path == f"/v1/text-to-speech/{el.VOICE_ID}" and req.headers["xi-api-key"] == "k-123"
    body = req.read().decode()
    assert el.MODEL in body and "one thousand, eight hundred and forty rupees" in body


def test_configured_only_with_a_key():
    assert el.ElevenLabsVoice(_settings()).configured
    assert not el.ElevenLabsVoice(_settings(None)).configured
    assert not el.ElevenLabsVoice(None).configured


async def test_guard_a_language_it_does_not_speak_is_refused(sent):
    with pytest.raises(ValueError):
        await el.ElevenLabsVoice(_settings()).speak("ഇന്ന്", "ml-IN")
    assert sent == []
