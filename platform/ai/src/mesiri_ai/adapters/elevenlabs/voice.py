"""ElevenLabs text-to-speech (UX-106): the walkthroughs' narrator for lines made on the day.

The voiced walkthrough steps and the scenes are recorded once with ElevenLabs into static files (UX-73, UX-76:
``scripts/scene_audio``). Lines that change every day (the morning briefing's "what each person did", a hint, a step
changed since it was recorded) used to be read by Sarvam, a different voice. With a key set
(``MESIRI_ELEVENLABS__API_KEY``) the server reads them with the same voice (George), model and settings as the
recordings; without one, or when ElevenLabs fails, the caller falls back to Sarvam.

Same interface as ``SarvamVoice`` (``configured``, ``speak``). httpx only, no SDK. ElevenLabs bills by character; the
count goes in the usage report.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from ... import usage
from ...core.fallback import call_with_resilience

#: The recordings' voice and model (scripts/scene_audio/make_scene_audio.py): George, multilingual v2.
VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
MODEL = "eleven_multilingual_v2"
OUTPUT = "mp3_44100_64"
VOICE_SETTINGS = {"stability": 0.55, "similarity_boost": 0.75, "style": 0.25, "use_speaker_boost": True}
#: The narrator speaks English (a Malayalam or Hindi line stays with Sarvam).
LANGUAGES = frozenset({"en-IN"})

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
         "seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _under_1000(n: int) -> str:
    words = []
    if n >= 100:
        words.append(f"{_ONES[n // 100]} hundred")
        n %= 100
        if n:
            words.append("and")
    if n >= 20:
        words.append(_TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else ""))
    elif n or not words:
        words.append(_ONES[n])
    return " ".join(words)


def rupees_in_words(n: int) -> str:
    """82,06,050 -> 'eighty-two lakh, six thousand and fifty': how an Indian builder says a sum."""
    parts = []
    for size, name in ((10**7, "crore"), (10**5, "lakh"), (1000, "thousand")):
        if n >= size:
            parts.append(f"{rupees_in_words(n // size) if size == 10**7 else _under_1000(n // size)} {name}")
            n %= size
    if n and parts and n < 100:
        return ", ".join(parts) + f" and {_under_1000(n)}"
    if n:
        parts.append(_under_1000(n))
    return ", ".join(parts) if parts else "zero"


_SAY = [
    (re.compile(r"₹\s?(\d{1,3}(?:,\d{2,3})*|\d+)(?:\.(\d{1,2}))?"),
     lambda m: f"{rupees_in_words(int(m.group(1).replace(',', '')))} rupees"
               + (f" and {int(m.group(2))} paise" if m.group(2) and int(m.group(2)) else "")),
    (re.compile(r"(\d+(?:\.\d+)?)\s?%"), lambda m: f"{m.group(1)} percent"),
    (re.compile(r"\bDr\.\s*"), lambda m: "Doctor "),
]


def speakable(line: str) -> str:
    """What George reads for a line: rupees in Indian words, percent and "Doctor" said in full (as the recordings)."""
    for pattern, words in _SAY:
        line = pattern.sub(words, line)
    return line


class ElevenLabsVoice:
    provider = "elevenlabs"

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._voice_id = getattr(settings, "voice_id", None) or VOICE_ID
        self._model = getattr(settings, "model", None) or MODEL

    @property
    def configured(self) -> bool:
        return bool(getattr(self._settings, "api_key", None))

    async def speak(
        self, text: str, language_code: str, *, correlation_id: str | None = None, codec: str | None = None
    ) -> bytes:
        """``text`` read by the narrator, as MP3 (``codec`` is accepted for the same interface; it is always MP3)."""
        if language_code not in LANGUAGES:
            raise ValueError(f"no narrator voice for {language_code}")
        words = speakable(text)
        key = self._settings.api_key.get_secret_value()

        async def _raw() -> bytes:
            async with httpx.AsyncClient(timeout=self._settings.timeout_seconds) as client:
                res = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}",
                    params={"output_format": OUTPUT},
                    headers={"xi-api-key": key, "Accept": "audio/mpeg"},
                    json={"text": words, "model_id": self._model, "voice_settings": VOICE_SETTINGS},
                )
                res.raise_for_status()
                return res.content

        audio, latency_ms = await call_with_resilience(
            _raw,
            provider=self.provider,
            operation="text_to_speech",
            timeout_seconds=self._settings.timeout_seconds,
            max_retries=self._settings.max_retries,
            correlation_id=correlation_id,
        )
        usage.report(
            usage.ProviderUsage(
                provider=self.provider,
                operation="text_to_speech",
                model=self._model,
                correlation_id=correlation_id,
                latency_ms=latency_ms,
                extra={"characters": len(words)},
            )
        )
        if not audio:
            raise RuntimeError("elevenlabs text_to_speech returned no audio")
        return audio
