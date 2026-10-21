"""Hands an agent tool's understanding to the existing journey.

`process_inbound_message` starts with `pipeline.understand(message)`. For a
tool call the model has already done the understanding, so this stands in for
the AI step with the candidate the tool built; everything after it (context,
canonicalization, gates, planner, workflow) runs unchanged.
"""

from __future__ import annotations

from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.confidence import ConfidenceLevel
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage
from mesiri_contracts.assistant.understanding_result import UnderstandingResult


class PresetUnderstandingPipeline:
    #: WA-37: the journey keeps only the first canonical event: the model
    #: makes one tool call per thing, so there is nothing left to split.
    one_event_per_call = True

    def __init__(self, candidate: Candidate, *, language: str | None = None) -> None:
        self._candidate = candidate
        self._language = language

    async def understand(
        self,
        message: NormalizedMessage,
        *,
        semantic_hint: str | None = None,
        expense_categories: list[str] | None = None,
    ) -> UnderstandingResult:
        # Transcript / normalized text stay empty on purpose: the journey's
        # correction/confirmation classifier runs on them, and a tool call is
        # never a reply to a waiting draft. The site-update narrative is a
        # field of its own.
        return UnderstandingResult(
            source_message_id=message.message_id,
            correlation_id=message.correlation_id,
            input_modality=InputModality.TEXT,
            detected_language=self._language,
            semantic_type=self._candidate.semantic_type,
            candidates=[self._candidate],
            intents=[self._candidate],
            overall_confidence=ConfidenceLevel.HIGH,
        )
