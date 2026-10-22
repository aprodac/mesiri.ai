"""Understanding pipeline (M3).

Consumes ``NormalizedMessage.v1`` and produces ``UnderstandingResult.v1``:

    text/interactive -> extraction
    voice            -> understand_voice (merged transcribe+extract, one call)
    image/document   -> vision -> extraction

Providers are injected via their ports (never SDKs), media is read through the
M0 object-storage abstraction (never R2 directly), and confidence is scored by
the deterministic policy. Provider failures are caught and surfaced as an
UNUSABLE result with observable telemetry rather than crashing the pipeline.

This module performs NO business persistence, context resolution, or workflow
selection (Understanding Module Boundary).
"""

from __future__ import annotations

import json
from typing import Any

from mesiri_ai.confidence import ConfidencePolicy, ConfidenceSignals
from mesiri_ai.greeting_classifier import is_greeting_trigger
from mesiri_ai.models import ExtractedIntent, ExtractionResult
from mesiri_ai.ports.extraction import StructuredExtractionProvider
from mesiri_ai.ports.vision import VisionUnderstandingProvider
from mesiri_ai.ports.voice_extraction import VoiceExtractionProvider
from mesiri_ai.whoami_classifier import is_whoami_trigger
from mesiri_contracts.assistant.candidates import CANDIDATE_TYPES, Candidate, FieldConfidence
from mesiri_contracts.assistant.confidence import ConfidenceLevel
from mesiri_contracts.assistant.enums import InputModality, SemanticType
from mesiri_contracts.assistant.normalized_message import NormalizedMessage
from mesiri_contracts.assistant.understanding_result import ProviderExecution, UnderstandingResult
from mesiri_contracts.common.errors import ErrorCategory, MesiriError
from mesiri_contracts.common.storage import ObjectStoragePort

# Minimal required-field expectations per semantic type (drives confidence).
_REQUIRED_FIELDS: dict[SemanticType, tuple[str, ...]] = {
    SemanticType.EXPENSE: ("amount",),
    SemanticType.EQUIPMENT_USAGE: ("equipment_name", "duration_hours"),
    SemanticType.MATERIAL_UPDATE: ("material_name",),
    # An invoice with no readable lines is a photo we failed to read, not a
    # purchase -- scoring it on `line_items` is what makes that show up as low
    # confidence instead of an empty record the user is asked to confirm.
    SemanticType.MATERIAL_INVOICE: ("line_items",),
    # Confidence is judged on the provider's own output, before
    # canonicalization folds the shapes together -- so this names what the
    # extraction prompt actually asks for (`workers`). A provider that falls
    # back to a flat `headcount` still canonicalizes fine (see
    # canonicalization/builder._normalize_labour_fields); it just scores as
    # one missing field, which is honest -- that reply lost the names.
    SemanticType.LABOUR_UPDATE: ("workers",),
    SemanticType.GENERAL_SITE_UPDATE: (),
    SemanticType.SITE_ISSUE: ("issue_type",),
    SemanticType.SITE_ISSUE_UPDATE: ("action",),
    SemanticType.GENERAL_QUESTION: (),
    SemanticType.WHOAMI_QUESTION: (),
    SemanticType.INVENTORY_QUERY: (),
    SemanticType.LABOUR_QUERY: (),
    SemanticType.ACTIVITY_QUERY: (),
    SemanticType.DPR_REQUEST: (),
    SemanticType.FINANCE_QUERY: (),
    SemanticType.TRANSFER: ("amount",),
    SemanticType.PETTY_CASH: ("amount", "recipient_name"),
    SemanticType.REVERSAL: (),
    SemanticType.ACCOUNT_ADMIN: ("action",),
    SemanticType.PROJECT_DETAIL_QUERY: (),
    SemanticType.AUTOMATION_SETUP: ("time_of_day",),
    SemanticType.UNKNOWN: (),
}


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
        extraction: StructuredExtractionProvider,
        object_storage: ObjectStoragePort,
        confidence_policy: ConfidencePolicy | None = None,
    ) -> None:
        self._voice_extraction = voice_extraction
        self._vision = vision
        self._extraction = extraction
        self._storage = object_storage
        self._confidence = confidence_policy or ConfidencePolicy()
        # Phase 9 perf: bounded in-memory cache for media bytes, keyed by
        # object_key. Images are immutable once uploaded (content-addressed),
        # so a cache hit always returns the correct bytes. Helps on admin
        # message retries and the image_purpose re-dispatch path (where the
        # held image is re-processed after the user answers the purpose picker).
        # Capped at _MEDIA_CACHE_MAX entries to prevent unbounded memory growth;
        # oldest entry is evicted when the cap is reached (simple FIFO via
        # dict insertion order, which Python 3.7+ guarantees).
        self._media_cache: dict[str, bytes] = {}

    async def understand_text_segment(
        self,
        text: str,
        *,
        source_message_id: str,
        correlation_id: str,
        expense_categories: list[str] | None = None,
    ) -> UnderstandingResult:
        """Classify one already-split segment of a decomposed message
        (docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md §9) -- the SAME
        single-intent extract() call and _apply_extraction logic every
        ordinary text message goes through, run once per segment rather than
        once per message.

        Deliberately skips the greeting/whoami deterministic shortcuts
        _handle_text runs first: a segment of an already-confirmed
        multi-intent message is never a bare greeting (the decomposition
        prompt is explicit that a greeting/non-actionable message must come
        back is_multi_intent=False, so this is never reached for one), and
        running those checks per segment would risk a false match against a
        short segment ("hi" as a person's name, say) that the whole-message
        check never sees in isolation.

        No semantic_hint parameter: a category-menu tap biases the ONE
        thing the user is about to say, and a decomposed message is by
        definition not that -- the hint would apply to only one segment
        arbitrarily.
        """
        result = UnderstandingResult(
            source_message_id=source_message_id,
            correlation_id=correlation_id,
            input_modality=InputModality.TEXT,
        )
        extraction = await self._extraction.extract(
            text, expense_categories=expense_categories, correlation_id=correlation_id
        )
        result.transcript = text
        result.normalized_text = text
        result.detected_language = extraction.detected_language
        result.detected_script = extraction.detected_script
        self._apply_extraction(result, extraction, is_empty=False)
        return result

    async def understand(
        self,
        message: NormalizedMessage,
        *,
        semantic_hint: str | None = None,
        expense_categories: list[str] | None = None,
    ) -> UnderstandingResult:
        """``semantic_hint`` is an optional nudge from a recent category-menu
        tap (see interactions/category_hint.py) -- it only reaches the
        extraction call, never the deterministic greeting/whoami shortcuts,
        and the provider may still override it if the text clearly disagrees.

        ``expense_categories`` is the caller org's active expense_categories
        names (fetched by the caller — this module must not resolve context
        itself, see the module docstring), threaded through to extraction so
        it can pick a real category instead of inventing free text."""
        result = UnderstandingResult(
            source_message_id=message.message_id,
            correlation_id=message.correlation_id,
            input_modality=message.modality,
            original_content_reference=message.media.object_key if message.media else None,
        )
        try:
            if message.modality in (InputModality.TEXT, InputModality.INTERACTIVE):
                await self._handle_text(
                    message, result, semantic_hint=semantic_hint, expense_categories=expense_categories
                )
            elif message.modality == InputModality.VOICE:
                await self._handle_voice(
                    message, result, semantic_hint=semantic_hint, expense_categories=expense_categories
                )
            elif message.modality in (InputModality.IMAGE, InputModality.DOCUMENT):
                await self._handle_image(
                    message, result, semantic_hint=semantic_hint, expense_categories=expense_categories
                )
            else:
                result.warnings.append(f"unsupported modality: {message.modality.value}")
                result.overall_confidence = ConfidenceLevel.UNUSABLE
        except MesiriError as err:
            result.warnings.append(err.user_safe_message)
            result.overall_confidence = ConfidenceLevel.UNUSABLE
            result.provider_executions.append(
                ProviderExecution(
                    provider=str(err.details.get("provider", "pipeline")),
                    operation="understand",
                    succeeded=False,
                    error_code=err.error_code,
                )
            )
        return result

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

    async def _handle_text(
        self,
        message: NormalizedMessage,
        result: UnderstandingResult,
        *,
        semantic_hint: str | None = None,
        expense_categories: list[str] | None = None,
    ) -> None:
        text = (message.text or "").strip()
        if not text:
            result.overall_confidence = ConfidenceLevel.UNUSABLE
            result.warnings.append("empty text")
            return

        result.transcript = text

        # Deterministic greeting/menu check, before any provider call. In
        # production a text greeting is normally already intercepted by
        # interactions/handler.py's pre-pipeline fast path and never reaches
        # here at all -- this is defense-in-depth so the pipeline is
        # correct in isolation too (direct calls, tests, future callers),
        # not the primary saving. See mesiri_ai.greeting_classifier.
        if is_greeting_trigger(text):
            result.normalized_text = text
            self._apply_deterministic_shortcut(result, SemanticType.UNKNOWN)
            return

        # Same reasoning, for "who am i"/"my profile"/etc -- see
        # mesiri_ai.whoami_classifier. Also defense-in-depth here (the
        # primary saving is interactions/handler.py's pre-pipeline check);
        # the reply itself is built later, in inbound_journey.py (which has
        # the ActorIdentity this module must not know about) by reading
        # semantic_type back off this result -- not by re-running this same
        # classifier a second time on raw text, which is what caused a real
        # bug (the second copy checked the wrong field for voice).
        if is_whoami_trigger(text):
            result.normalized_text = text
            self._apply_deterministic_shortcut(result, SemanticType.WHOAMI_QUESTION)
            return

        # No separate translate_to_english() hop: extract() now reads the
        # original-language text directly and returns detected_language
        # itself (see _EXTRACTION_PROMPT), removing a whole sequential
        # provider round trip from every text message -- previously ~1.9s
        # per message, and the source of three separate silent-failure
        # production bugs (see the Gemini/DeepSeek adapters' git history).
        #
        # Known tradeoff: the is_whoami_trigger phrase list is English-only,
        # and used to get a second, post-translation check here for exactly
        # that reason ("എന്റെ റോൾ എന്താണ്?" never matches until translated).
        # That free shortcut for a non-English whoami question is gone --
        # it now costs one extract() call instead of zero, but is still
        # answered correctly: extract()'s own schema includes
        # "whoami_question" as a semantic_type, so _apply_extraction below
        # classifies it the same way this shortcut would have.
        result.normalized_text = text

        extraction = await self._extraction.extract(
            text,
            semantic_hint=semantic_hint,
            expense_categories=expense_categories,
            correlation_id=result.correlation_id,
        )
        result.detected_language = extraction.detected_language
        result.detected_script = extraction.detected_script
        self._apply_extraction(result, extraction, is_empty=False)

    async def _handle_voice(
        self,
        message: NormalizedMessage,
        result: UnderstandingResult,
        *,
        semantic_hint: str | None = None,
        expense_categories: list[str] | None = None,
    ) -> None:
        # One call: transcribe + extract together (see
        # ports/voice_extraction.py), not the old sequential transcribe()
        # then extract() (~4.5s combined, measured). This means the
        # deterministic greeting/whoami shortcuts that used to run *between*
        # those two calls (skipping extraction for a spoken "hi") no longer
        # apply -- there is no longer a cheap first call to check before
        # committing to the expensive one. Traffic-weighted this should
        # still be a net win (most voice traffic is real reports), but a
        # spoken greeting now costs the same one call as everything else,
        # where it used to cost only the transcription half.
        audio = await self._read_media(message)
        extraction = await self._voice_extraction.understand_voice(
            audio,
            semantic_hint=semantic_hint,
            expense_categories=expense_categories,
            correlation_id=result.correlation_id,
        )
        result.transcript = extraction.transcript
        result.detected_language = extraction.detected_language
        result.translated_text = extraction.translated_text
        result.normalized_text = extraction.translated_text or extraction.transcript
        if not (result.normalized_text or "").strip():
            result.overall_confidence = ConfidenceLevel.UNUSABLE
            result.warnings.append("empty transcript")
            result.provider_executions.append(
                ProviderExecution(
                    provider=extraction.provider or "gemini",
                    operation="understand_voice",
                    model=extraction.model,
                    latency_ms=extraction.latency_ms,
                )
            )
            return

        self._apply_extraction(result, extraction, is_empty=False, operation="understand_voice")

    async def _handle_image(
        self,
        message: NormalizedMessage,
        result: UnderstandingResult,
        *,
        semantic_hint: str | None = None,
        expense_categories: list[str] | None = None,
    ) -> None:
        vision = await self._analyze(message, semantic_hint)
        result.document_classification = vision.document_classification
        result.normalized_text = vision.description
        result.provider_executions.append(
            ProviderExecution(
                provider=vision.provider or "gemini",
                operation="analyze_image",
                model=vision.model,
                latency_ms=vision.latency_ms,
            )
        )
        source = _vision_source(vision)
        if source is None:
            result.overall_confidence = ConfidenceLevel.UNUSABLE
            result.warnings.append("image not interpretable")
            return
        extraction = await self._extraction.extract(
            source,
            semantic_hint=semantic_hint,
            expense_categories=expense_categories,
            correlation_id=result.correlation_id,
        )
        self._apply_extraction(result, extraction, is_empty=False)

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

    def _apply_deterministic_shortcut(
        self, result: UnderstandingResult, semantic_type: SemanticType
    ) -> None:
        """A deterministically recognized greeting/menu or who-am-i request
        (see mesiri_ai.greeting_classifier / mesiri_ai.whoami_classifier) --
        no extraction call, no candidate.

        semantic_type distinguishes the two: UNKNOWN for greeting (the same
        classification an empty extraction would already produce, so it
        flows through canonicalization to CanonicalEventType.UNRECOGNIZED ->
        Planner's DIRECT_REPLY exactly as it does today -- this only makes
        the outcome deterministic rather than dependent on an AI provider
        correctly finding no fields). WHOAMI_QUESTION for who-am-i -- this
        result is the single source of truth callers read (e.g.
        inbound_journey.py checks result.semantic_type directly) rather than
        re-running is_whoami_trigger on raw text a second time downstream,
        which is what let a real bug in: two independent copies of "which
        text field do I check" drifted apart for voice.
        HIGH, not UNUSABLE: we are confident about what this is, we just
        chose not to spend a provider call confirming it.
        """
        result.semantic_type = semantic_type
        result.overall_confidence = ConfidenceLevel.HIGH
        # Phase B (docs/execution/UNIFIED_UNDERSTANDING_PIPELINE.md): a
        # deterministic shortcut still names exactly one intent -- no
        # extraction call happened to find any others, and greeting/who-am-i
        # are never themselves part of a multi-intent message in practice.
        # Kept non-empty (never "no intents") for the same reason
        # ExtractionResult._normalize enforces it in B1.
        result.intents = [Candidate(semantic_type=semantic_type)]

    def _apply_extraction(
        self,
        result: UnderstandingResult,
        extraction: ExtractionResult,
        *,
        is_empty: bool,
        operation: str = "extract",
    ) -> None:
        try:
            semantic = SemanticType(extraction.semantic_type)
        except ValueError:
            semantic = SemanticType.UNKNOWN
        result.semantic_type = semantic

        candidate = self._build_candidate(semantic, extraction)
        result.candidates.append(candidate)
        result.missing_fields = list(extraction.missing_fields)
        result.warnings.extend(extraction.warnings)
        # Phase B: intents is SET (not appended) -- one extraction call
        # produces every intent the message has all at once (today, always
        # exactly one; B4 changes that), unlike `candidates` above, which
        # can accumulate across separate pipeline stages over the life of
        # one message.
        result.intents = [
            self._build_candidate_from_intent(intent) for intent in extraction.intents
        ]
        result.provider_executions.append(
            ProviderExecution(
                provider=extraction.provider or getattr(self._extraction, "provider", "unknown"),
                operation=operation,
                model=extraction.model,
                latency_ms=extraction.latency_ms,
            )
        )

        required = _REQUIRED_FIELDS.get(semantic, ())
        signals = ConfidenceSignals(
            provider_succeeded=True,
            schema_valid=True,
            is_empty=is_empty,
            required_fields=required,
            present_fields=tuple(extraction.fields.keys()),
            missing_fields=tuple(extraction.missing_fields),
            field_confidences=tuple(extraction.field_confidences.values()),
        )
        result.overall_confidence = self._confidence.evaluate(signals)

    @staticmethod
    def _build_candidate(semantic: SemanticType, extraction: ExtractionResult) -> Candidate:
        candidate_cls = CANDIDATE_TYPES.get(semantic, Candidate)
        field_confidences = [
            FieldConfidence(field=k, confidence=v) for k, v in extraction.field_confidences.items()
        ]
        kwargs: dict[str, Any] = dict(
            fields=extraction.fields,
            unknown_fields=extraction.unknown_fields,
            missing_fields=extraction.missing_fields,
            field_confidences=field_confidences,
            warnings=extraction.warnings,
        )
        if candidate_cls is Candidate:
            kwargs["semantic_type"] = semantic
        return candidate_cls(**kwargs)

    @staticmethod
    def _build_candidate_from_intent(intent: ExtractedIntent) -> Candidate:
        """Same construction as _build_candidate above, generalized to read
        one ExtractedIntent (Phase B) instead of an ExtractionResult's own
        derived intents[0] shim -- used to build UnderstandingResult.intents,
        which needs one Candidate per intent, not just the first."""
        try:
            semantic = SemanticType(intent.semantic_type)
        except ValueError:
            semantic = SemanticType.UNKNOWN
        candidate_cls = CANDIDATE_TYPES.get(semantic, Candidate)
        field_confidences = [
            FieldConfidence(field=k, confidence=v) for k, v in intent.field_confidences.items()
        ]
        kwargs: dict[str, Any] = dict(
            fields=intent.fields,
            unknown_fields=intent.unknown_fields,
            missing_fields=intent.missing_fields,
            field_confidences=field_confidences,
            warnings=intent.warnings,
        )
        if candidate_cls is Candidate:
            kwargs["semantic_type"] = semantic
        return candidate_cls(**kwargs)
