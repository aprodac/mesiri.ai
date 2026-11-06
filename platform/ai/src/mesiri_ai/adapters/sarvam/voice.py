"""Sarvam text-to-speech (WEB-63): Mesiri's voice on the dashboard's Live.

One short line in, one WAV out (Sarvam's ``bulbul:v2``, which speaks Malayalam,
English, Hindi and the other Indian languages). The ``sarvamai`` SDK is imported
lazily and only here (the architecture test keeps provider SDKs inside
``adapters/``). Same key, timeout and retry policy as the speech-to-text adapter.
Sarvam bills text-to-speech by characters; the count goes in the usage report.
"""

from __future__ import annotations

import base64
from typing import Any

from ... import usage
from ...core.fallback import call_with_resilience

VOICE_MODEL = "bulbul:v2"
#: A clear voice that speaks every language bulbul:v2 has.
DEFAULT_SPEAKER = "anushka"
#: The languages Live speaks in (Sarvam's codes).
LANGUAGES = frozenset({"en-IN", "ml-IN", "hi-IN", "ta-IN", "kn-IN", "te-IN"})


class SarvamVoice:
    provider = "sarvam"

    def __init__(self, settings: Any, *, speaker: str = DEFAULT_SPEAKER) -> None:
        self._settings = settings
        self._speaker = speaker
        self._client: Any | None = None

    @property
    def configured(self) -> bool:
        return bool(getattr(self._settings, "api_key", None))

    def _get_client(self) -> Any:
        if self._client is None:
            from sarvamai import SarvamAI  # lazy: only the voice needs it here

            api_key = self._settings.api_key.get_secret_value() if self._settings.api_key else None
            self._client = SarvamAI(api_subscription_key=api_key)
        return self._client

    async def speak(self, text: str, language_code: str, *, correlation_id: str | None = None) -> bytes:
        """``text`` spoken in ``language_code`` (one of ``LANGUAGES``), as WAV bytes."""
        if language_code not in LANGUAGES:
            raise ValueError(f"no voice for {language_code}")
        client = self._get_client()

        async def _raw() -> Any:
            import asyncio

            def _call() -> Any:
                return client.text_to_speech.convert(
                    text=text, language_code=language_code, speaker=self._speaker, model=VOICE_MODEL, pace=1.05
                )

            return await asyncio.to_thread(_call)

        raw, latency_ms = await call_with_resilience(
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
                model=VOICE_MODEL,
                correlation_id=correlation_id,
                latency_ms=latency_ms,
                extra={"characters": len(text)},
            )
        )
        audios = raw.get("audios") if isinstance(raw, dict) else getattr(raw, "audios", None)
        if not audios:
            raise RuntimeError("sarvam text_to_speech returned no audio")
        return base64.b64decode(audios[0])
