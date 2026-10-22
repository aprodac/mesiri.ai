"""Reading what a voice note says and what a photo or document shows.

The agent reads the message itself (runtime/agent/turn.py); for a voice note
it needs the words (``transcribe_voice``), for a photo or bill a description
with the fields read from it (``describe_media``). Providers are injected via
their ports (never SDKs), and media is read through the object-storage
abstraction. The extraction steps that turned a message into candidates for
the classic pipeline went with it (ARCH-06, 22 Oct 2026).
"""

from __future__ import annotations

import json
from typing import Any

from mesiri_ai.ports.vision import VisionUnderstandingProvider
from mesiri_ai.ports.voice_extraction import VoiceExtractionProvider
from mesiri_contracts.assistant.normalized_message import NormalizedMessage
from mesiri_contracts.common.errors import ErrorCategory, MesiriError
from mesiri_contracts.common.storage import ObjectStoragePort


def _vision_source(vision: Any) -> str | None:
    """The vision read as text, or None when nothing could be read.

    vision.raw_fields is Gemini's own structured read of the document
    (amount, vendor, ...) -- description is a *short* prose summary that does
    not reliably restate every field in words (a receipt description like
    "Restaurant bill for tea and toast" never mentions the total), so the
    fields are kept alongside, or a real numeric field like amount is
    silently lost between the vision call and whatever reads it next."""
    if (vision.document_classification or "").lower() == "unknown" and not vision.raw_fields:
        return None
    source = vision.description or ""
    if vision.raw_fields:
        details = "; ".join(f"{key}: {_render_vision_value(value)}" for key, value in vision.raw_fields.items())
        source = f"{source} ({details})" if source else details
    return source


def _render_vision_value(value: object) -> str:
    """Render one vision field for the text extraction call that follows.

    Scalars pass through as plain text, exactly as before -- a receipt's
    ``amount: 250`` must keep reading like prose, since that is what the
    extraction prompt was tuned against.

    Lists and dicts are JSON-encoded instead of being str()'d. This matters
    for attendance sheets specifically: a roster arrives as a ``workers``
    array of 15 rows, and Python's repr renders it with single quotes
    (``[{'name': 'Ravi'}]``), which is not JSON and which the extraction
    model then has to re-parse by eye. Nested structure is the one thing an
    attendance sheet cannot afford to lose in this hand-off -- lose it and 15
    named workers collapse into an unparseable blob, which reads exactly like
    the model having failed to read the handwriting.
    """
    if isinstance(value, (list, dict)):
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


class UnderstandingPipeline:
    def __init__(
        self,
        *,
        voice_extraction: VoiceExtractionProvider,
        vision: VisionUnderstandingProvider,
        object_storage: ObjectStoragePort,
    ) -> None:
        self._voice_extraction = voice_extraction
        self._vision = vision
        self._storage = object_storage
        # Bounded in-memory cache for media bytes, keyed by object_key (media
        # is immutable once uploaded); oldest entry evicted at the cap.
        self._media_cache: dict[str, bytes] = {}

    async def transcribe_voice(
        self, message: NormalizedMessage
    ) -> tuple[str, str | None, str | None]:
        """Just the words of a voice note: ``(transcript, translated_text,
        detected_language)``. The tool-calling agent reads the message itself,
        so it needs the speech step only. Same provider call as
        `_handle_voice` (which also extracts, in the one call)."""
        audio = await self._read_media(message)
        result = await self._voice_extraction.understand_voice(
            audio, correlation_id=message.correlation_id
        )
        return (result.transcript or "", result.translated_text, result.detected_language)

    async def describe_media(self, message: NormalizedMessage, hint: str | None = None) -> str | None:
        """What a photo or document shows, in words, with the fields read
        from it (amount, vendor, ...), or None when it cannot be read. The
        tool-calling agent reads this as the message; same vision call as
        `_handle_image`."""
        return _vision_source(await self._analyze(message, hint)) or None

    async def _analyze(self, message: NormalizedMessage, hint: str | None) -> Any:
        image = await self._read_media(message)
        mime = message.media.mime_type if message.media else None
        return await self._vision.analyze_image(
            image, mime_type=mime, hint=hint, correlation_id=message.correlation_id
        )

    async def _read_media(self, message: NormalizedMessage) -> bytes:
        if message.media is None:
            raise MesiriError(
                error_code="VALIDATION_ERROR",
                category=ErrorCategory.VALIDATION,
                internal_message="media modality without a media reference",
                correlation_id=message.correlation_id,
            )
        key = message.media.object_key
        if key in self._media_cache:
            return self._media_cache[key]
        obj = await self._storage.get_object(key)
        data = obj.data
        _MEDIA_CACHE_MAX = 20
        if len(self._media_cache) >= _MEDIA_CACHE_MAX:
            # Evict oldest entry (dict preserves insertion order in Python 3.7+)
            self._media_cache.pop(next(iter(self._media_cache)))
        self._media_cache[key] = data
        return data
