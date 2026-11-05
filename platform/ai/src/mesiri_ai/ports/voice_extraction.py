"""Merged voice-transcription + structured-extraction provider port (M3 perf).

Distinct from SpeechUnderstandingProvider + StructuredExtractionProvider used
together: a single adapter (Gemini) can transcribe and extract in one model
call, given audio in and the extraction schema in the same prompt -- this
port is what lets understanding/pipeline.py's voice path use that one call
instead of two sequential round trips (previously ~4.5s combined; see the
Gemini adapter's understand_voice()).

Only DynamicAIProviderResolver and GeminiProvider implement this. A raw
single-capability adapter (SarvamSpeechProvider) cannot -- it has no
extraction capability of its own to compose with -- so the resolver's
implementation falls back to calling transcribe() then extract() internally
and merging the two results when voice isn't routed to Gemini, keeping the
same external contract either way.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import ExtractionResult


@runtime_checkable
class VoiceExtractionProvider(Protocol):
    async def understand_voice(
        self,
        audio: bytes,
        *,
        semantic_hint: str | None = None,
        expense_categories: list[str] | None = None,
        correlation_id: str | None = None,
        speech_hint: str | None = None,
    ) -> ExtractionResult:
        """Returns an ExtractionResult with transcript/translated_text/
        detected_language populated alongside the usual extraction fields --
        see models.ExtractionResult and _EXTRACTION_PROMPT's per-type field
        schema, which this reuses verbatim.

        ``speech_hint`` ([258], optional): who speaks and the words they are likely to say (their language, the
        company's site, material, trade and worker names), so code-mixed speech is written as it was said. An
        adapter that cannot use it ignores it."""
        ...
