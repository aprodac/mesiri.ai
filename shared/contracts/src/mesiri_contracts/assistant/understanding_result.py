"""UnderstandingResult.v1 — the M3 output contract.

Produced by the Understanding Pipeline from a ``NormalizedMessage``. Captures the
transcript/translation, document classification, structured extraction
candidates, confidence, and provider telemetry — but never business truth,
context resolution, or workflow selection (those are downstream).

Ownership: Ilan.  Required reviewer: Alan.  Version: v1.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .candidates import Candidate
from .confidence import ConfidenceLevel
from .enums import InputModality, SemanticType

CONTRACT_VERSION = "v1"


class ProviderExecution(BaseModel):
    """One provider invocation's telemetry (no secrets, no raw payloads)."""

    provider: str
    operation: str
    model: str | None = None
    latency_ms: float | None = None
    succeeded: bool = True
    error_code: str | None = None


class UnderstandingResult(BaseModel):
    version: str = CONTRACT_VERSION

    # Provenance / linkage back to the inbound message.
    source_message_id: str
    correlation_id: str
    input_modality: InputModality

    # Original media pointer (object-storage key), never inline bytes.
    original_content_reference: str | None = None

    # Speech / language.
    transcript: str | None = None
    detected_language: str | None = None
    # "latin" | "native" -- the letters the sender wrote in. None = unknown.
    detected_script: str | None = None
    translated_text: str | None = None
    normalized_text: str | None = None

    # Vision / classification.
    document_classification: str | None = None

    # Semantic understanding.
    semantic_type: SemanticType = SemanticType.UNKNOWN
    candidates: list[Candidate] = Field(default_factory=list)
    # Phase B of docs/execution/UNIFIED_UNDERSTANDING_PIPELINE.md. Composing,
    # not competing -- see that doc's ADR-U3: `candidates` above are RIVAL
    # readings of one request (planner/ambiguity.py picks one); `intents` are
    # requests that ALL co-occur in the one message ("create a project, then
    # a site, then add a member" is three). Deliberately NOT derived from
    # `candidates` (a real temptation, since both are `list[Candidate]`) --
    # conflating the two axes would make "did the user ask for two things,
    # or might they have meant one of two things?" unanswerable. Real field,
    # not yet a derived property the way ExtractionResult's old fields
    # became in B1: understanding/pipeline.py builds this result
    # incrementally across several methods (`result.semantic_type = ...`,
    # `result.warnings.append(...)`), which a read-only property can't
    # support without a larger rewrite of that construction style -- out of
    # scope for B2, which only adds the field. Always length 1 until B4
    # changes the extraction prompt; `semantic_type`/`missing_fields`/
    # `warnings` above stay the real, independently-set fields they already
    # are, unaffected by this addition.
    intents: list[Candidate] = Field(default_factory=list)

    # Aggregate quality signals.
    overall_confidence: ConfidenceLevel = ConfidenceLevel.UNUSABLE
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    # Telemetry.
    provider_executions: list[ProviderExecution] = Field(default_factory=list)

    model_config = {"extra": "forbid"}
