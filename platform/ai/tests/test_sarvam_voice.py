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


def _voice(**extra) -> tuple[SarvamVoice, _TTS]:  # noqa: ANN003
    settings = SimpleNamespace(api_key=SimpleNamespace(get_secret_value=lambda: "k"), timeout_seconds=5.0, max_retries=0, **extra)
    voice = SarvamVoice(settings)
    tts = _TTS()
    voice._client = SimpleNamespace(text_to_speech=tts)
    return voice, tts


async def test_a_line_comes_back_as_wav():
    voice, tts = _voice()
    assert await voice.speak("ഇന്ന് 50 ചാക്ക്", "ml-IN") == b"RIFFwav"
    assert tts.calls[0]["language_code"] == "ml-IN"
    # INF-34: bulbul:v2 and its anushka voice were retired (Sarvam answers 400); v3 with a v3 voice.
    assert tts.calls[0]["model"] == "bulbul:v3" and tts.calls[0]["speaker"] == "priya"


async def test_the_server_settings_can_change_the_model_and_voice():
    voice, tts = _voice(tts_model="bulbul:v4-flash", tts_speaker="shubh")
    await voice.speak("Six masons today", "en-IN")
    assert tts.calls[0]["model"] == "bulbul:v4-flash" and tts.calls[0]["speaker"] == "shubh"


def test_no_retired_voice_is_the_default():
    """The guard: a retired model or voice must never come back as the default."""
    from mesiri.bootstrap.settings import SarvamSettings
    from mesiri_ai.adapters.sarvam import voice as mod

    retired_models, retired_speakers = {"bulbul:v1", "bulbul:v2"}, {"anushka", "meera", "arvind", "manisha", "vidya", "abhilash", "karun", "hitesh"}
    for model, speaker in ((mod.VOICE_MODEL, mod.DEFAULT_SPEAKER), (SarvamSettings().tts_model, SarvamSettings().tts_speaker)):
        assert model not in retired_models and speaker not in retired_speakers


async def test_a_language_live_does_not_speak_is_refused():
    voice, tts = _voice()
    with pytest.raises(ValueError):
        await voice.speak("hola", "es-ES")
    assert tts.calls == []


def test_without_a_key_it_says_so():
    assert SarvamVoice(SimpleNamespace(api_key=None)).configured is False
