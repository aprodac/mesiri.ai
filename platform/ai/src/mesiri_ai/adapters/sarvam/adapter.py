"""Sarvam speech-understanding adapter (M3).

Implements :class:`SpeechUnderstandingProvider`. Sarvam's speech-to-text-translate
returns transcript, detected language, and English translation from a single
invocation, so the adapter makes one call — no separate translation request.

The ``sarvamai`` SDK is imported lazily and is the only SDK reference here; the
response is converted into the Mesiri-owned :class:`SpeechResult` before
returning.

Verified against sarvamai 0.1.28: the client exposes ``speech_to_text``
(there is no ``speech_to_text_translate`` attribute), whose ``translate()``
returns ``transcript`` and ``language_code``. Every call here is exercised
only against the live SDK — the fake provider stands in for all tests — so
an SDK rename surfaces as an UNUSABLE understanding result, never a test
failure. Re-verify this call on every ``sarvamai`` upgrade.
"""

from __future__ import annotations

import io
from typing import Any

from ... import usage
from ...core.fallback import call_with_resilience
from ...models import SpeechResult

# The only value sarvamai's SpeechToTextTranslateModel literal accepts. A stale
# name here fails the call, which surfaces as an UNUSABLE understanding result
# rather than an error — verify against the installed SDK when upgrading.
_TRANSLATE_MODEL = "saaras:v2.5"

try:  # settings live in the backend package; import defensively for standalone use
    from mesiri.bootstrap.settings import SarvamSettings
except Exception:  # pragma: no cover
    SarvamSettings = Any  # type: ignore


class SarvamSpeechProvider:
    provider = "sarvam"

    def __init__(self, settings: SarvamSettings) -> None:
        self._settings = settings
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            from sarvamai import SarvamAI  # lazy: only the sarvam lane needs it

            api_key = self._settings.api_key.get_secret_value() if self._settings.api_key else None
            self._client = SarvamAI(api_subscription_key=api_key)
        return self._client

    async def transcribe(
        self, audio: bytes, *, language_hint: str | None = None, correlation_id: str | None = None
    ) -> SpeechResult:
        client = self._get_client()

        async def _raw() -> Any:
            import asyncio

            def _call() -> Any:
                # Sarvam infers the codec from the upload's filename/content-type,
                # so send a named tuple rather than a bare BytesIO. WhatsApp voice
                # notes are always OGG/Opus.
                return client.speech_to_text.translate(
                    file=("audio.ogg", io.BytesIO(audio), "audio/ogg"),
                    model=_TRANSLATE_MODEL,
                )

            return await asyncio.to_thread(_call)

        raw, latency_ms = await call_with_resilience(
            _raw,
            provider=self.provider,
            operation="speech_to_text_translate",
            timeout_seconds=self._settings.timeout_seconds,
            max_retries=self._settings.max_retries,
            correlation_id=correlation_id,
        )
        # BE-25: Sarvam bills by audio length, read from the Ogg file itself.
        usage.report(
            usage.ProviderUsage(
                provider=self.provider,
                operation="speech_to_text_translate",
                model=_TRANSLATE_MODEL,
                correlation_id=correlation_id,
                latency_ms=latency_ms,
                audio_seconds=usage.ogg_duration_seconds(audio),
            )
        )
        return self._to_result(raw, latency_ms)

    def _to_result(self, raw: Any, latency_ms: float) -> SpeechResult:
        def _field(name: str) -> Any:
            if isinstance(raw, dict):
                return raw.get(name)
            return getattr(raw, name, None)

        return SpeechResult(
            transcript=_field("transcript") or "",
            detected_language=_field("language_code"),
            translated_text=_field("transcript"),  # translate endpoint returns English
            provider=self.provider,
            model=_TRANSLATE_MODEL,
            latency_ms=latency_ms,
        )
