"""The real `WorkflowGateway`: runs a tool's understanding through the existing
journey and saves like a "YES" would.

Built per message by `runtime.message_journey`, which owns every dependency the
journey needs; this class only holds the few callables the agent uses, so it
is testable without the whole container.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from channel.replies import ListRow, ReplySpec, is_module_disabled_reply
from interactions.saved_summary import summarise_draft
from mesiri_contracts.application.results.execution_result import ExecutionStatus
from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage
from mesiri_contracts.assistant.planner_decision import PlannerDecisionType
from workflows import WorkflowRunStatus

from .gateway import StepResult
from .preset_pipeline import PresetUnderstandingPipeline

_log = logging.getLogger("mesiri.agent")


def _without_menu(text: str) -> str:
    """A module-disabled reply is one line; older replies carried the
    capability list after it, which the agent never repeats (requests [43], [59])."""
    if is_module_disabled_reply(text):
        return text.split("\n\n", 1)[0]
    return text


def _saved_summary(handled: Any) -> str | None:
    """What the confirmed record says, from its own data. Never raises."""
    try:
        confirmed = getattr(handled.result, "confirmed_action", None)
        return summarise_draft(confirmed.draft_action) if confirmed is not None else None
    except Exception:  # noqa: BLE001 -- the summary is wording only
        _log.warning("agent.saved_summary_failed", exc_info=True)
        return None


def _succeeded(handled: Any) -> bool:
    """Whether the save behind ``handled`` actually wrote its record."""
    execution = getattr(handled, "execution_result", None)
    return execution is not None and execution.status is ExecutionStatus.SUCCEEDED


@dataclass(slots=True)
class CaptureSink:
    """Stands in for the send callbacks: remembers what the journey would have
    sent, so the agent can fold it into its one reply."""

    replies: list[ReplySpec] = field(default_factory=list)

    async def send_text(self, wa_id: str, body: str, *args: Any, **kwargs: Any) -> None:
        self.replies.append(ReplySpec(text=body))

    async def send_list(
        self,
        wa_id: str,
        body: str | None = None,
        button_label: str | None = None,
        rows: tuple[ListRow, ...] | None = None,
        **kwargs: Any,
    ) -> bool:
        self.replies.append(
            ReplySpec(text=body or "", list_button_label=button_label, list_rows=tuple(rows or ()))
        )
        return True

    async def send_button(
        self,
        wa_id: str,
        body: str | None = None,
        buttons: tuple[ListRow, ...] | None = None,
        **kwargs: Any,
    ) -> bool:
        self.replies.append(ReplySpec(text=body or "", buttons=tuple(buttons or ())))
        return True

    @property
    def last(self) -> ReplySpec | None:
        return self.replies[-1] if self.replies else None


#: ``(message, pipeline, sink) -> JourneyResult``: the existing
#: process_inbound_message with the sink's senders.
ProcessFn = Callable[[NormalizedMessage, PresetUnderstandingPipeline, CaptureSink], Awaitable[Any]]
#: ``() -> InteractionHandled | None``: save the waiting capture draft.
SaveNowFn = Callable[[], Awaitable[Any]]
#: ``() -> str | None``: the classic UNDO of the latest saved draft.
UndoFn = Callable[[], Awaitable[str | None]]
#: ``(handled) -> None``: the follow-ups a saved confirmation triggers.
FollowupsFn = Callable[[Any], Awaitable[None]]
#: ``(journey_result) -> ReplySpec``: the confirm prompt the journey held back.
HeldPromptFn = Callable[[Any], ReplySpec]


@dataclass(slots=True)
class JourneyGateway:
    message: NormalizedMessage
    process: ProcessFn
    save_now: SaveNowFn
    undo: UndoFn
    followups: FollowupsFn
    held_prompt: HeldPromptFn
    language: str | None = None
    handled: list[Any] = field(default_factory=list)

    async def run(self, candidate: Candidate, *, text: str) -> StepResult:
        sink = CaptureSink()
        # A text message carrying the user's words: the journey's own checks
        # (duplicates, narrative, logging) read it. Voice was transcribed already.
        message = self.message.model_copy(update={"text": text, "modality": InputModality.TEXT})
        journey = await self.process(
            message, PresetUnderstandingPipeline(candidate, language=self.language), sink
        )
        run = journey.workflow_run
        key = run.workflow_key.value if run is not None else None

        if run is not None and run.status is WorkflowRunStatus.STARTED:
            saved = await self.save_now()
            if saved is not None and not _succeeded(saved):
                # WA-37: the save was refused or failed (a repeat, a closed
                # day, a validation error). Its reply says why; it is never
                # "saved", or the model writes "Saved" for nothing.
                return StepResult("error", text=saved.reply_text, workflow_key=key)
            if saved is not None:
                self.handled.append(saved)
                return StepResult(
                    "saved",
                    text=saved.reply_text,
                    workflow_key=key,
                    summary=_saved_summary(saved),
                )
            # Confirm-first (expenses, transfers) or the save failed: the
            # prompt the sender must answer.
            prompt = sink.last or self.held_prompt(journey)
            return StepResult("needs_confirmation", text=prompt.text, reply=prompt, workflow_key=key)

        if run is not None and run.status in (
            WorkflowRunStatus.AWAITING_INPUT,
            WorkflowRunStatus.BLOCKED_PENDING_CONFIRMATION,
        ):
            prompt = sink.last or ReplySpec(text=run.pending_prompt or "")
            return StepResult("needs_answer", text=prompt.text, reply=prompt, workflow_key=key)

        if run is not None and run.status is WorkflowRunStatus.COMPLETED:
            return StepResult(
                "answer", text="\n\n".join(r.text for r in sink.replies if r.text), workflow_key=key
            )

        if run is not None:  # FAILED / NO_GRAPH
            return StepResult("error", text=sink.last.text if sink.last else "", workflow_key=key)

        # No workflow started: a gate asked (which project / material / unit?),
        # or the pipeline answered directly (module off, not allowed).
        decision = journey.planner_decision
        reply = sink.last
        if reply is None:
            return StepResult("error", text="")
        if is_module_disabled_reply(reply.text):
            # The module gate sends its reply and ends the journey; it is a
            # statement, not a question to park (request [59]).
            return StepResult("info", text=_without_menu(reply.text))
        if decision is None or decision.decision_type is not PlannerDecisionType.DIRECT_REPLY:
            return StepResult("needs_answer", text=reply.text, reply=reply)
        return StepResult("info", text=_without_menu(reply.text))

    async def undo_latest_draft(self) -> StepResult:
        reply = await self.undo()
        if reply:
            return StepResult("undone", text=reply)
        return StepResult("info", text="There is no recent saved update of theirs to undo.")

    async def finish(self) -> None:
        for handled in self.handled:
            try:
                await self.followups(handled)
            except Exception:  # noqa: BLE001 — a follow-up never disturbs a saved record
                _log.exception("agent.followup_failed")
