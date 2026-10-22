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

from channel.replies import (
    ListRow,
    ReplySpec,
    is_module_disabled_reply,
    render_understanding_failed_reply,
)
from interactions.saved_summary import summarise_draft
from mesiri_contracts.application.results.execution_result import ExecutionStatus
from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.enums import InputModality, SemanticType
from mesiri_contracts.assistant.normalized_message import NormalizedMessage
from mesiri_contracts.assistant.planner_decision import PlannerDecisionType
from workflows import WorkflowRunStatus

from .gateway import StepResult
from .preset_pipeline import PresetUnderstandingPipeline

_log = logging.getLogger("mesiri.agent")

#: What only reads: its run ends with an answer, not a record.
_LOOKUPS = frozenset(
    {
        SemanticType.ACTIVITY_QUERY,
        SemanticType.DPR_REQUEST,
        SemanticType.FINANCE_QUERY,
        SemanticType.INVENTORY_QUERY,
        SemanticType.LABOUR_QUERY,
        SemanticType.PROJECT_DETAIL_QUERY,
    }
)


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
    #: WA-41: ``(material, unit, count) -> line to say``; None when not wired.
    set_conversion: Callable[[str, str, Any], Awaitable[str]] | None = None
    #: ARCH-01: material receipts/usage straight to the workflow
    #: (runtime/agent/material_entry.py); None keeps the classic route.
    material_entry: Any | None = None
    #: ARCH-02: work done, site issues and expenses straight to the workflow
    #: (runtime/agent/site_entry.py); None keeps the classic route.
    site_entry: Any | None = None
    #: ARCH-03: labour attendance straight to its workflow
    #: (runtime/agent/labour_entry.py; Alan's approval, 22 Oct).
    labour_entry: Any | None = None
    #: ARCH-06 step 2: lookups, transfers, site/project create, money undo
    #: (runtime/agent/query_entry.py).
    query_entry: Any | None = None
    #: ``WorkflowRuntime.start``, for the direct routes.
    start_workflow: Callable[[Any, Any], Awaitable[Any]] | None = None
    #: WA-45: ``(project_id, site_id) -> label``: today's site is this one
    #: (runtime/agent/work_site.py); None when not wired.
    set_today_site: Callable[[str | None, str], Awaitable[str]] | None = None

    async def run(self, candidate: Candidate, *, text: str) -> StepResult:
        step = await self._run(candidate, text=text)
        if step.status == "saved" and self.handled:
            await self._remember_site(self.handled[-1])
        return step

    async def _remember_site(self, handled: Any) -> None:
        """WA-45: a save at a site keeps the sender there for the rest of the
        day, whatever module it was. Never raises."""
        if self.set_today_site is None:
            return
        try:
            confirmed = getattr(handled.result, "confirmed_action", None)
            draft = confirmed.draft_action if confirmed is not None else None
            site_id = getattr(draft, "site_id", None)
            if site_id:
                await self.set_today_site(getattr(draft, "project_id", None), str(site_id))
        except Exception:  # noqa: BLE001 -- a missed hint only costs one question
            _log.warning("agent.remember_site_failed", exc_info=True)

    async def set_work_site(self, *, project_id: str | None, site_id: str) -> str:
        if self.set_today_site is None:
            raise RuntimeError("today's site is not wired")
        return await self.set_today_site(project_id, site_id)

    async def _run(self, candidate: Candidate, *, text: str) -> StepResult:
        sink = CaptureSink()
        # A text message carrying the user's words: the journey's own checks
        # (duplicates, narrative, logging) read it. Voice was transcribed already.
        message = self.message.model_copy(update={"text": text, "modality": InputModality.TEXT})
        entry = self._entry_for(getattr(candidate, "semantic_type", None))
        if entry is not None:
            direct = await self._direct(entry, candidate, message)
            if direct is not None:
                return direct
        journey = await self.process(
            message, PresetUnderstandingPipeline(candidate, language=self.language), sink
        )
        return await self._after_run(journey, candidate, sink)

    def _entry_for(self, semantic_type: Any) -> Any | None:
        """The direct entry for this kind of record, or None (classic route)."""
        if self.start_workflow is None:
            return None
        if semantic_type is SemanticType.MATERIAL_UPDATE:
            return self.material_entry
        if semantic_type is SemanticType.LABOUR_UPDATE:
            return self.labour_entry
        from .site_entry import SITE_ENTRY_TYPES

        if semantic_type in SITE_ENTRY_TYPES:
            return self.site_entry
        from .query_entry import QUERY_ENTRY_TYPES

        if semantic_type in QUERY_ENTRY_TYPES:
            return self.query_entry
        return None

    async def _direct(self, entry: Any, candidate: Candidate, message: Any) -> StepResult | None:
        """ARCH-01/02: the tool's arguments as the workflow's event. Never the
        classic route (ARCH-06, Ilan 22 Oct): what the entry cannot place
        (a failed lookup) is said, not handed to the old pipeline."""
        from types import SimpleNamespace

        from .entry_base import Say

        understanding = await PresetUnderstandingPipeline(candidate, language=self.language).understand(message)
        prepared = await entry.prepare(message, understanding, candidate)
        kind = getattr(getattr(candidate, "semantic_type", None), "value", None)
        if prepared is None:
            _log.warning("agent.direct correlation_id=%s kind=%s route=unplaced", message.correlation_id, kind)
            return StepResult("error", text="Not saved: the system could not look this up just now. Send it again.")
        if isinstance(prepared, Say):
            from .toolbox import question_reply

            reply = question_reply(prepared.question, list(prepared.options)) if prepared.question else None
            return StepResult(prepared.status, text=prepared.text, reply=reply)
        run = await self.start_workflow(prepared.decision, prepared.event)
        _log.info("agent.direct correlation_id=%s kind=%s route=direct", message.correlation_id, kind)
        journey = SimpleNamespace(workflow_run=run, planner_decision=prepared.decision)
        step = await self._after_run(journey, candidate, CaptureSink())
        if step.status in ("saved", "needs_confirmation"):
            await entry.remember(prepared, correlation_id=message.correlation_id)
        deliver = getattr(entry, "deliver", None)
        if deliver is not None:
            failed = await deliver(prepared, message)
            if failed:
                from dataclasses import replace

                step = replace(step, text=f"{step.text}\n\n{failed}".strip())
        return step

    async def _after_run(self, journey: Any, candidate: Candidate, sink: CaptureSink) -> StepResult:
        run = journey.workflow_run
        key = run.workflow_key.value if run is not None else None

        if run is not None and run.status is WorkflowRunStatus.STARTED:
            saved = await self.save_now()
            if saved is not None and not _succeeded(saved):
                # WA-37: the save was refused or failed (a repeat, a closed
                # day, a validation error). Its reply says why; it is never
                # "saved", or the model writes "Saved" for nothing.
                return StepResult("error", text=saved.reply_text, workflow_key=key)
            if saved is not None and getattr(candidate, "semantic_type", None) in _LOOKUPS:
                # A lookup ends through the same step as an entry (the answer
                # is that step's reply), but it keeps nothing: never "saved",
                # no Undo line, no part of the Save card (round 3b, 21 Oct).
                return StepResult("answer", text=saved.reply_text, workflow_key=key)
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
            if run.status is WorkflowRunStatus.BLOCKED_PENDING_CONFIRMATION:
                # Nothing of this message was kept: an earlier entry waits for
                # its Yes/No. Said plainly, with no buttons, so a Yes is never
                # taken for this one (review, 22 Oct: the bare earlier card
                # went out and Yes confirmed the old entry instead).
                return StepResult(
                    "error",
                    text=(
                        "Not saved: an earlier entry is still waiting for Yes or No (its buttons are "
                        "above). Answer that one first, then send this again."
                    ),
                    workflow_key=key,
                )
            # The classic rendering when nothing was captured (the direct
            # routes capture nothing), with its list or buttons.
            prompt = sink.last or self.held_prompt(journey)
            return StepResult("needs_answer", text=prompt.text, reply=prompt, workflow_key=key)

        if run is not None and run.status is WorkflowRunStatus.COMPLETED:
            # The direct routes capture nothing: the workflow's own answer.
            text = "\n\n".join(r.text for r in sink.replies if r.text) or (run.pending_prompt or "")
            return StepResult("answer", text=text, workflow_key=key)

        if run is not None:  # FAILED / NO_GRAPH
            text = sink.last.text if sink.last else "Sorry, that didn't go through. Please try again."
            return StepResult("error", text=text, workflow_key=key)

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
        if reply.text == render_understanding_failed_reply():
            # The pipeline could not place it (context or understanding
            # failed): that is a failure to say, never a question to park --
            # it went out alone as the reply to a plain "Yes" (22 Oct).
            return StepResult("error", text="Not saved: the system could not place this entry.")
        if decision is None or decision.decision_type is not PlannerDecisionType.DIRECT_REPLY:
            return StepResult("needs_answer", text=reply.text, reply=reply)
        return StepResult("info", text=_without_menu(reply.text))

    async def set_unit_conversion(self, *, material: str, unit: str, count: Any) -> StepResult:
        if self.set_conversion is None:
            return StepResult("info", text="I can't remember unit conversions here yet.")
        line = await self.set_conversion(material, unit, count)
        status = "answer" if line.startswith("Saved for the company") else "info"
        return StepResult(status, text=line)

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
