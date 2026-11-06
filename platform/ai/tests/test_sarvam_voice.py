"""WEB-63: the Sarvam voice adapter: one line in, the decoded WAV out, in a language Live speaks; usage reported."""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from mesiri_ai.adapters.sarvam.voice import SarvamVoice


class _TTS:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def convert(self, **kw):  # noqa: ANN003, ANN201
        self.calls.append(kw)
        return SimpleNamespace(audios=[base64.b64encode(b"RIFFwav").decode()])


def _voice() -> tuple[SarvamVoice, _TTS]:
    settings = SimpleNamespace(api_key=SimpleNamespace(get_secret_value=lambda: "k"), timeout_seconds=5.0, max_retries=0)
    voice = SarvamVoice(settings)
    tts = _TTS()
    voice._client = SimpleNamespace(text_to_speech=tts)
    return voice, tts


async def test_a_line_comes_back_as_wav():
    voice, tts = _voice()
    assert await voice.speak("ഇന്ന് 50 ചാക്ക്", "ml-IN") == b"RIFFwav"
    assert tts.calls[0]["language_code"] == "ml-IN" and tts.calls[0]["model"] == "bulbul:v2"


async def test_a_language_live_does_not_speak_is_refused():
    voice, tts = _voice()
    with pytest.raises(ValueError):
        await voice.speak("hola", "es-ES")
    assert tts.calls == []


def test_without_a_key_it_says_so():
    assert SarvamVoice(SimpleNamespace(api_key=None)).configured is False
