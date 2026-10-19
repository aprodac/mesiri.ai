"""Workflow Runtime (M6) — executes a compiled graph from a PlannerDecision.

Orchestration only: state, transitions, and the confirmation handoff. Never
touches SQL, repositories, domain rules, or AI providers (architecture rule
#11 + layer-ownership table). The runtime enforces its own precondition (only
a START_WORKFLOW decision may reach ``start()``) rather than trusting callers.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from mesiri_contracts.assistant.planner_decision import PlannerDecisionType, WorkflowKey
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from mesiri_contracts.assistant.v2.interaction_spec import FieldCorrection
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from mesiri_contracts.assistant.v2.workflow_state import WorkflowStateV2
from mesiri_contracts.common.ids import new_id
from mesiri_contracts.context.enums import WorkflowPhase

from .ports import LoadedWorkflowInstance, SingleActiveConflict, WorkflowInstanceRepository
from .registry import WorkflowRegistry, allows_completion_without_draft, is_informational
from .slots import QUESTION_DROPPED_NOTE, SlotCandidate
from .state import WorkflowGraphState

logger = logging.getLogger(__name__)

# Per-workflow is_informational / allows_completion_without_draft flags live
# on WorkflowDefinition (registry.py) -- this module only consumes them via
# is_informational()/allows_completion_without_draft() below. See
# WorkflowDefinition's field docstrings for what each flag means and why
# (e.g. why REVERSE/EXPENSE_SUBMIT/ACCOUNT_ADMIN allow a missing draft
# without being informational).


def _to_slot_candidates(raw: list[dict[str, str]] | None) -> tuple[SlotCandidate, ...] | None:
    """Convert a node's `awaiting_slot_options` (plain dicts, LangGraph-state-
    safe) back into `SlotCandidate`s for `WorkflowRunResult`. None (a node
    that didn't set the field) stays None -- the send side falls back to
    plain text in that case."""
    if not raw:
        return None
    return tuple(SlotCandidate(value=c["value"], label=c["label"]) for c in raw)


class WorkflowRunStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    NO_GRAPH = "no_graph"
    FAILED = "failed"
    # A new actionable intent arrived while the user already has a confirmation
    # pending (single-active invariant). Carries the *existing* pending prompt.
    BLOCKED_PENDING_CONFIRMATION = "blocked_pending_confirmation"
    # A node set awaiting_slot (e.g. "which account?") -- persisted as
    # COLLECTING_FIELDS, not yet a draft awaiting confirmation. See Finance
    # Module Slice 1 / workflows/slots.py.
    AWAITING_INPUT = "awaiting_input"


@dataclass(frozen=True, slots=True)
class WorkflowRunResult:
    """A discriminated result — invariants enforced per status, not an ad-hoc
    nullable dataclass."""

    status: WorkflowRunStatus
    workflow_key: WorkflowKey
    correlation_id: str
    workflow_instance_id: str | None = None
    draft_action: DraftActionV2 | None = None
    pending_prompt: str | None = None
    # The candidate list behind an AWAITING_INPUT prompt, if the node
    # supplied one (see workflows/slots.py's `slot_options`) -- lets the
    # send side (runtime/inbound_journey.py) offer a real WhatsApp
    # interactive list instead of only numbered text. None for every other
    # status, and also legal for AWAITING_INPUT itself (a node that doesn't
    # set awaiting_slot_options just gets plain text, no crash).
    slot_options: tuple[SlotCandidate, ...] | None = None
    # The state the graph finished with. Present on the two statuses that ran
    # a graph to a usable end (AWAITING_INPUT, COMPLETED); None otherwise.
    #
    # This exists so a caller can act on something a node *decided* but must
    # not *do*. Nodes are pure -- no I/O, no repositories (see this module's
    # docstring) -- so a node that concludes "create these workers" can only
    # say so in its state and leave the write to whoever is holding the
    # database. Smuggling a callable into collected_fields instead is not an
    # option: this state is persisted with model_dump_json() between messages,
    # so a function neither survives the round trip nor serializes at all.
    collected_fields: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.slot_options is not None and self.status is not WorkflowRunStatus.AWAITING_INPUT:
            raise ValueError(f"{self.status.value} must not carry slot_options")
        if self.status is WorkflowRunStatus.STARTED:
            if not (self.workflow_instance_id and self.draft_action and self.pending_prompt):
                raise ValueError(
                    "STARTED requires workflow_instance_id, draft_action, and pending_prompt"
                )
        elif self.status is WorkflowRunStatus.COMPLETED:
            if not self.pending_prompt:
                raise ValueError("COMPLETED requires pending_prompt")
        elif self.status is WorkflowRunStatus.BLOCKED_PENDING_CONFIRMATION:
            if not self.pending_prompt:
                raise ValueError("BLOCKED_PENDING_CONFIRMATION requires the pending prompt")
            if self.workflow_instance_id is not None or self.draft_action is not None:
                raise ValueError("BLOCKED_PENDING_CONFIRMATION must carry only pending_prompt")
        elif self.status is WorkflowRunStatus.AWAITING_INPUT:
            if not (self.workflow_instance_id and self.pending_prompt):
                raise ValueError("AWAITING_INPUT requires workflow_instance_id and pending_prompt")
            if self.draft_action is not None:
                raise ValueError("AWAITING_INPUT must not carry a draft_action")
        elif (
            self.workflow_instance_id is not None
            or self.draft_action is not None
            or self.pending_prompt is not None
        ):
            raise ValueError(
                f"{self.status.value} must not carry workflow_instance_id/draft_action/pending_prompt"
            )

    @classmethod
    def started(
        cls,
        *,
        workflow_key: WorkflowKey,
        correlation_id: str,
        workflow_instance_id: str,
        draft_action: DraftActionV2,
        pending_prompt: str,
    ) -> WorkflowRunResult:
        return cls(
            status=WorkflowRunStatus.STARTED,
            workflow_key=workflow_key,
            correlation_id=correlation_id,
            workflow_instance_id=workflow_instance_id,
            draft_action=draft_action,
            pending_prompt=pending_prompt,
        )

    @classmethod
    def no_graph(cls, *, workflow_key: WorkflowKey, correlation_id: str) -> WorkflowRunResult:
        return cls(
            status=WorkflowRunStatus.NO_GRAPH,
            workflow_key=workflow_key,
            correlation_id=correlation_id,
        )

    @classmethod
    def failed(cls, *, workflow_key: WorkflowKey, correlation_id: str) -> WorkflowRunResult:
        return cls(
            status=WorkflowRunStatus.FAILED,
            workflow_key=workflow_key,
            correlation_id=correlation_id,
        )

    @classmethod
    def blocked_pending_confirmation(
        cls, *, workflow_key: WorkflowKey, correlation_id: str, pending_prompt: str
    ) -> WorkflowRunResult:
        return cls(
            status=WorkflowRunStatus.BLOCKED_PENDING_CONFIRMATION,
            workflow_key=workflow_key,
            correlation_id=correlation_id,
            pending_prompt=pending_prompt,
        )

    @classmethod
    def completed(
        cls,
        *,
        workflow_key: WorkflowKey,
        correlation_id: str,
        pending_prompt: str,
        collected_fields: dict[str, Any] | None = None,
    ) -> WorkflowRunResult:
        return cls(
            status=WorkflowRunStatus.COMPLETED,
            workflow_key=workflow_key,
            correlation_id=correlation_id,
            pending_prompt=pending_prompt,
            collected_fields=collected_fields,
        )

    @classmethod
    def awaiting_input(
        cls,
        *,
        workflow_key: WorkflowKey,
        correlation_id: str,
        workflow_instance_id: str,
        pending_prompt: str,
        slot_options: tuple[SlotCandidate, ...] | None = None,
        collected_fields: dict[str, Any] | None = None,
    ) -> WorkflowRunResult:
        return cls(
            status=WorkflowRunStatus.AWAITING_INPUT,
            workflow_key=workflow_key,
            correlation_id=correlation_id,
            workflow_instance_id=workflow_instance_id,
            pending_prompt=pending_prompt,
            slot_options=slot_options,
            collected_fields=collected_fields,
        )


class ResumeAction(str, Enum):
    """The workflow-layer verb for resuming an awaiting workflow. The interaction
    layer maps its InteractionIntent onto this — workflows/ never imports
    interactions/."""

    CONFIRM = "confirm"
    REJECT = "reject"
    CANCEL = "cancel"


class WorkflowResumeStatus(str, Enum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    # The optimistic transition found the row already moved on (duplicate
    # delivery / double reply) — idempotent no-op.
    ALREADY_RESOLVED = "already_resolved"
    # The instance was not in AWAITING_CONFIRMATION.
    NOT_RESUMABLE = "not_resumable"


_RESUME_PHASE: dict[ResumeAction, WorkflowPhase] = {
    ResumeAction.CONFIRM: WorkflowPhase.CONFIRMED,
    ResumeAction.REJECT: WorkflowPhase.REJECTED,
    ResumeAction.CANCEL: WorkflowPhase.CANCELLED,
}


@dataclass(frozen=True, slots=True)
class WorkflowResumeResult:
    """Discriminated resume outcome — only CONFIRMED carries a ConfirmedActionV2."""

    status: WorkflowResumeStatus
    workflow_instance_id: str
    correlation_id: str
    confirmed_action: ConfirmedActionV2 | None = None

    def __post_init__(self) -> None:
        if self.status is WorkflowResumeStatus.CONFIRMED:
            if self.confirmed_action is None:
                raise ValueError("CONFIRMED requires a confirmed_action")
        elif self.confirmed_action is not None:
            raise ValueError(f"{self.status.value} must not carry a confirmed_action")


class WorkflowRuntime:
    """Starts a workflow graph from a PlannerDecision + CanonicalEvent."""

    def __init__(self, registry: WorkflowRegistry, repo: WorkflowInstanceRepository) -> None:
        self._registry = registry
        self._repo = repo

    async def start(
        self, decision: PlannerDecisionV2, event: CanonicalEventV2
    ) -> WorkflowRunResult:
        # Defensive precondition: the runtime is a boundary and enforces this
        # itself rather than relying exclusively on the caller (inbound_journey
        # already only calls start() for START_WORKFLOW, but must not be the
        # only thing standing between a bad decision and a broken graph run).
        if (
            decision.decision_type is not PlannerDecisionType.START_WORKFLOW
            or decision.workflow_key is None
        ):
            raise ValueError(
                "WorkflowRuntime.start() requires a START_WORKFLOW decision with a workflow_key, "
                f"got decision_type={decision.decision_type!r} workflow_key={decision.workflow_key!r}"
            )
        workflow_key = decision.workflow_key

        # Single-active invariant: a user may have at most one AWAITING_CONFIRMATION
        # workflow. If one is pending, block the new one and re-show its prompt
        # rather than piling up ambiguous confirmations. (The partial unique index
        # in Postgres is the hard guarantee; this is the friendly pre-check.)
        # Informational workflows (WorkflowDefinition.is_informational) are exempt.
        # A pending COLLECTING_FIELDS slot question (Finance Module Slice 1)
        # blocks the same way -- there is no DB-level guarantee for that phase
        # (see workflows/ports.py's get_awaiting_input docstring), so this
        # pre-check is the only thing enforcing it.
        if not is_informational(workflow_key):
            # Fetch both pending-state types concurrently — they are
            # independent reads on different workflow phases.
            existing, existing_input = await asyncio.gather(
                self._repo.get_awaiting_confirmation(event.user_id),
                self._repo.get_awaiting_input(event.user_id),
            )
            if existing is not None and existing.state.pending_prompt:
                logger.info(
                    "workflow.blocked_pending_confirmation user=%s existing=%s",
                    event.user_id,
                    existing.state.workflow_instance_id,
                )
                return WorkflowRunResult.blocked_pending_confirmation(
                    workflow_key=workflow_key,
                    correlation_id=event.correlation_id,
                    pending_prompt=existing.state.pending_prompt,
                )
            if existing_input is not None and existing_input.state.pending_prompt:
                # An *optional* question must never hold the user hostage.
                # Worker promotion ("shall I add these to the register?") is
                # informational: nothing depends on the answer, and ignoring
                # it is a legitimate reply. Left blocking, an unanswered offer
                # stopped every later report -- and because the row lives in
                # Postgres with no expiry, it stopped them forever. Drop the
                # offer and let the new work through.
                if is_informational(existing_input.state.workflow_key):
                    logger.info(
                        "workflow.abandoned_optional_question user=%s existing=%s",
                        event.user_id,
                        existing_input.state.workflow_instance_id,
                    )
                    await self._abandon(existing_input)
                else:
                    logger.info(
                        "workflow.blocked_pending_input user=%s existing=%s",
                        event.user_id,
                        existing_input.state.workflow_instance_id,
                    )
                    return WorkflowRunResult.blocked_pending_confirmation(
                        workflow_key=workflow_key,
                        correlation_id=event.correlation_id,
                        pending_prompt=existing_input.state.pending_prompt,
                    )

        # Look up the graph BEFORE minting any identity: an unmapped key must
        # never generate an orphaned workflow_instance_id.
        graph = self._registry.get_graph(workflow_key)
        if graph is None:
            logger.warning("workflow.no_graph workflow_key=%s", workflow_key.value)
            return WorkflowRunResult.no_graph(
                workflow_key=workflow_key, correlation_id=event.correlation_id
            )

        workflow_instance_id = str(uuid.uuid4())
        graph_state: WorkflowGraphState = {
            "workflow_instance_id": workflow_instance_id,
            "workflow_key": workflow_key.value,
            "correlation_id": event.correlation_id,
            "organization_id": event.organization_id,
            "user_id": event.user_id,
            "project_id": event.project_id,
            "site_id": event.site_id,
            "collected_fields": dict(event.fields),
        }

        try:
            result_state = await graph.ainvoke(graph_state)
        except Exception:
            logger.exception(
                "workflow.run_failed workflow_key=%s workflow_instance_id=%s",
                workflow_key.value,
                workflow_instance_id,
            )
            return WorkflowRunResult.failed(
                workflow_key=workflow_key, correlation_id=event.correlation_id
            )

        draft_action: DraftActionV2 | None = result_state.get("draft_action")
        pending_prompt: str | None = result_state.get("pending_prompt")
        awaiting_slot: str | None = result_state.get("awaiting_slot")
        collected_fields = result_state.get("collected_fields", dict(event.fields))

        if awaiting_slot is not None:
            # A node asked a mid-workflow question (e.g. "which account?") --
            # persist as COLLECTING_FIELDS, not yet a draft. collected_fields
            # must come from the graph's result (not event.fields) so the
            # seeded candidate list survives to the next provide_input() call.
            if pending_prompt is None:
                logger.error(
                    "workflow.slot_missing_prompt workflow_key=%s workflow_instance_id=%s",
                    workflow_key.value,
                    workflow_instance_id,
                )
                return WorkflowRunResult.failed(
                    workflow_key=workflow_key, correlation_id=event.correlation_id
                )
            slot_state = WorkflowStateV2(
                workflow_instance_id=workflow_instance_id,
                workflow_key=workflow_key,
                correlation_id=event.correlation_id,
                organization_id=event.organization_id,
                user_id=event.user_id,
                project_id=event.project_id,
                site_id=event.site_id,
                phase=WorkflowPhase.COLLECTING_FIELDS,
                collected_fields=collected_fields,
                awaiting_slot=awaiting_slot,
                pending_prompt=pending_prompt,
            )
            try:
                await self._repo.save(slot_state)
            except Exception:
                logger.exception(
                    "workflow.save_failed workflow_instance_id=%s", workflow_instance_id
                )
                return WorkflowRunResult.failed(
                    workflow_key=workflow_key, correlation_id=event.correlation_id
                )
            return WorkflowRunResult.awaiting_input(
                workflow_key=workflow_key,
                correlation_id=event.correlation_id,
                workflow_instance_id=workflow_instance_id,
                pending_prompt=pending_prompt,
                slot_options=_to_slot_candidates(result_state.get("awaiting_slot_options")),
                collected_fields=collected_fields,
            )

        if pending_prompt is None:
            logger.error(
                "workflow.incomplete_result workflow_key=%s workflow_instance_id=%s",
                workflow_key.value,
                workflow_instance_id,
            )
            return WorkflowRunResult.failed(
                workflow_key=workflow_key, correlation_id=event.correlation_id
            )

        if draft_action is None:
            if not allows_completion_without_draft(workflow_key):
                logger.error(
                    "workflow.missing_draft_action workflow_key=%s workflow_instance_id=%s",
                    workflow_key.value,
                    workflow_instance_id,
                )
                return WorkflowRunResult.failed(
                    workflow_key=workflow_key, correlation_id=event.correlation_id
                )

            return WorkflowRunResult.completed(
                workflow_key=workflow_key,
                correlation_id=event.correlation_id,
                pending_prompt=pending_prompt,
                collected_fields=collected_fields,
            )

        state = WorkflowStateV2(
            workflow_instance_id=workflow_instance_id,
            workflow_key=workflow_key,
            correlation_id=event.correlation_id,
            organization_id=event.organization_id,
            user_id=event.user_id,
            project_id=event.project_id,
            site_id=event.site_id,
            phase=WorkflowPhase.AWAITING_CONFIRMATION,
            collected_fields=collected_fields,
            draft_action=draft_action,
            pending_prompt=pending_prompt,
        )

        try:
            await self._repo.save(state)
        except SingleActiveConflict:
            # Lost the check-then-insert race — the DB partial unique index is the
            # real guarantee. Re-fetch to re-show the winning workflow's prompt.
            existing = await self._repo.get_awaiting_confirmation(event.user_id)
            prompt = (
                existing.state.pending_prompt
                if existing is not None and existing.state.pending_prompt
                else "You have a pending confirmation. Please reply YES or NO to it first."
            )
            logger.info("workflow.blocked_pending_confirmation_on_insert user=%s", event.user_id)
            return WorkflowRunResult.blocked_pending_confirmation(
                workflow_key=workflow_key,
                correlation_id=event.correlation_id,
                pending_prompt=prompt,
            )
        except Exception:
            logger.exception("workflow.save_failed workflow_instance_id=%s", workflow_instance_id)
            return WorkflowRunResult.failed(
                workflow_key=workflow_key, correlation_id=event.correlation_id
            )

        return WorkflowRunResult.started(
            workflow_key=workflow_key,
            correlation_id=event.correlation_id,
            workflow_instance_id=workflow_instance_id,
            draft_action=draft_action,
            pending_prompt=pending_prompt,
        )

    async def correct(
        self, loaded: LoadedWorkflowInstance, corrections: list[FieldCorrection]
    ) -> WorkflowRunResult:
        """Applies field corrections and re-runs the workflow graph to generate a new draft."""
        state = loaded.state
        instance_id = state.workflow_instance_id

        if state.phase is not WorkflowPhase.AWAITING_CONFIRMATION:
            return WorkflowRunResult.failed(
                workflow_key=state.workflow_key, correlation_id=state.correlation_id
            )

        new_fields = dict(state.collected_fields)
        for corr in corrections:
            new_fields[corr.field_name] = corr.new_value

        graph = self._registry.get_graph(state.workflow_key)
        if graph is None:
            return WorkflowRunResult.failed(
                workflow_key=state.workflow_key, correlation_id=state.correlation_id
            )

        graph_state: WorkflowGraphState = {
            "workflow_instance_id": instance_id,
            "workflow_key": state.workflow_key.value,
            "correlation_id": state.correlation_id,
            "organization_id": state.organization_id,
            "user_id": state.user_id,
            "project_id": state.project_id,
            "site_id": state.site_id,
            "collected_fields": new_fields,
        }

        try:
            result_state = await graph.ainvoke(graph_state)
        except Exception:
            logger.exception("workflow.correct_failed workflow_instance_id=%s", instance_id)
            return WorkflowRunResult.failed(
                workflow_key=state.workflow_key, correlation_id=state.correlation_id
            )

        draft_action: DraftActionV2 | None = result_state.get("draft_action")
        pending_prompt: str | None = result_state.get("pending_prompt")

        if draft_action is None or pending_prompt is None:
            return WorkflowRunResult.failed(
                workflow_key=state.workflow_key, correlation_id=state.correlation_id
            )

        new_state = state.model_copy(
            update={
                "collected_fields": new_fields,
                "draft_action": draft_action,
                "pending_prompt": pending_prompt,
            }
        )

        applied = await self._repo.transition(instance_id, loaded.version, new_state)
        if not applied:
            # Another event won the race (e.g. duplicate webhook)
            return WorkflowRunResult.failed(
                workflow_key=state.workflow_key, correlation_id=state.correlation_id
            )

        return WorkflowRunResult.started(
            workflow_key=state.workflow_key,
            correlation_id=state.correlation_id,
            workflow_instance_id=instance_id,
            draft_action=draft_action,
            pending_prompt=pending_prompt,
        )

    async def provide_input(
        self, loaded: LoadedWorkflowInstance, answer_text: str
    ) -> WorkflowRunResult:
        """Answers a pending slot question (e.g. "which account?") and re-runs
        the graph. Generalizes correct()'s merge-fields -> re-invoke ->
        transition mechanic: the raw answer text is handed to the graph as
        `_slot_answer_text` and the node that raised the question (e.g.
        expense_capture's resolve_account) is responsible for matching it
        against the candidates it seeded -- this method never matches
        answers itself, only orchestrates the re-run and persistence
        (workflows/ -> no domain-rule matching in the runtime layer).

        Three outcomes: no match (graph re-asks) -> persisted as
        COLLECTING_FIELDS again with the new prompt; resolved -> persisted as
        AWAITING_CONFIRMATION with the built draft; anything else -> FAILED.
        """
        state = loaded.state
        instance_id = state.workflow_instance_id

        if state.phase is not WorkflowPhase.COLLECTING_FIELDS or state.awaiting_slot is None:
            return WorkflowRunResult.failed(
                workflow_key=state.workflow_key, correlation_id=state.correlation_id
            )

        new_fields = dict(state.collected_fields)
        new_fields["_slot_answer_text"] = answer_text

        graph = self._registry.get_graph(state.workflow_key)
        if graph is None:
            return WorkflowRunResult.failed(
                workflow_key=state.workflow_key, correlation_id=state.correlation_id
            )

        graph_state: WorkflowGraphState = {
            "workflow_instance_id": instance_id,
            "workflow_key": state.workflow_key.value,
            "correlation_id": state.correlation_id,
            "organization_id": state.organization_id,
            "user_id": state.user_id,
            "project_id": state.project_id,
            "site_id": state.site_id,
            "collected_fields": new_fields,
            "awaiting_slot": state.awaiting_slot,
        }

        try:
            result_state = await graph.ainvoke(graph_state)
        except Exception:
            logger.exception("workflow.provide_input_failed workflow_instance_id=%s", instance_id)
            return WorkflowRunResult.failed(
                workflow_key=state.workflow_key, correlation_id=state.correlation_id
            )

        draft_action: DraftActionV2 | None = result_state.get("draft_action")
        pending_prompt: str | None = result_state.get("pending_prompt")
        awaiting_slot: str | None = result_state.get("awaiting_slot")
        resolved_fields = result_state.get("collected_fields", new_fields)

        if awaiting_slot is not None:
            # Not matched (or another slot pending) -- ask again.
            if pending_prompt is None:
                return WorkflowRunResult.failed(
                    workflow_key=state.workflow_key, correlation_id=state.correlation_id
                )
            new_state = state.model_copy(
                update={
                    "collected_fields": resolved_fields,
                    "awaiting_slot": awaiting_slot,
                    "pending_prompt": pending_prompt,
                }
            )
            applied = await self._repo.transition(instance_id, loaded.version, new_state)
            if not applied:
                return WorkflowRunResult.failed(
                    workflow_key=state.workflow_key, correlation_id=state.correlation_id
                )
            return WorkflowRunResult.awaiting_input(
                workflow_key=state.workflow_key,
                correlation_id=state.correlation_id,
                workflow_instance_id=instance_id,
                pending_prompt=pending_prompt,
                slot_options=_to_slot_candidates(result_state.get("awaiting_slot_options")),
                collected_fields=resolved_fields,
            )

        if draft_action is None and pending_prompt is not None:
            # A workflow that legitimately ends without anything to confirm
            # (allows_completion_without_draft -- the answer *was* the
            # decision). start() has always allowed this; provide_input did
            # not, so such a workflow answered its own question and was then
            # told "Sorry, I couldn't apply that update". Worker promotion is
            # the first workflow to both ask a slot question and finish
            # without a draft, which is why the gap went unnoticed.
            if not allows_completion_without_draft(state.workflow_key):
                logger.error(
                    "workflow.missing_draft_action workflow_key=%s workflow_instance_id=%s",
                    state.workflow_key.value,
                    instance_id,
                )
                return WorkflowRunResult.failed(
                    workflow_key=state.workflow_key, correlation_id=state.correlation_id
                )
            # The COLLECTING_FIELDS row has to be closed out, not just left
            # behind: get_awaiting_input() would keep finding it and swallow
            # the user's next message as another answer to a question that is
            # already over.
            done_state = state.model_copy(
                update={
                    "collected_fields": resolved_fields,
                    "awaiting_slot": None,
                    "phase": WorkflowPhase.COMPLETED,
                    "pending_prompt": pending_prompt,
                }
            )
            if not await self._repo.transition(instance_id, loaded.version, done_state):
                return WorkflowRunResult.failed(
                    workflow_key=state.workflow_key, correlation_id=state.correlation_id
                )
            return WorkflowRunResult.completed(
                workflow_key=state.workflow_key,
                correlation_id=state.correlation_id,
                pending_prompt=pending_prompt,
                collected_fields=resolved_fields,
            )

        if draft_action is None or pending_prompt is None:
            return WorkflowRunResult.failed(
                workflow_key=state.workflow_key, correlation_id=state.correlation_id
            )

        new_state = state.model_copy(
            update={
                "collected_fields": resolved_fields,
                "awaiting_slot": None,
                "phase": WorkflowPhase.AWAITING_CONFIRMATION,
                "draft_action": draft_action,
                "pending_prompt": pending_prompt,
            }
        )
        applied = await self._repo.transition(instance_id, loaded.version, new_state)
        if not applied:
            return WorkflowRunResult.failed(
                workflow_key=state.workflow_key, correlation_id=state.correlation_id
            )

        return WorkflowRunResult.started(
            workflow_key=state.workflow_key,
            correlation_id=state.correlation_id,
            workflow_instance_id=instance_id,
            draft_action=draft_action,
            pending_prompt=pending_prompt,
        )

    async def abandon_optional_question(self, user_id: str) -> bool:
        """Close the user's open *optional* slot question, if there is one.

        Called before raising a new optional question, so at most one is ever
        outstanding. Two open promotion offers is not a hypothetical: the
        offer is raised by the system rather than requested, so every
        attendance report raises one, and without this the second report's
        offer joins the first instead of replacing it. get_awaiting_input()
        then answers whichever row is newest, and the user is looking at a
        list built from a different report than the one being answered.

        Returns True if something was closed. Never touches a question the
        workflow genuinely needs answered.
        """
        loaded = await self._repo.get_awaiting_input(user_id)
        if loaded is None or not is_informational(loaded.state.workflow_key):
            return False
        await self._abandon(loaded)
        return True

    async def close_question(self, loaded: LoadedWorkflowInstance) -> WorkflowRunResult:
        """End an open slot question the sender is not answering (request [51]).

        A question must never trap the sender: when the reply is plainly
        something else, or the second try missed too, it is closed with the
        safe default and the new message is handled normally.

        An informational question (worker promotion) is closed by answering
        it "skip" -- the node's own default, nobody promoted -- so whatever
        it had already decided still happens and the result carries its own
        closing line. Any other workflow is cancelled: nothing was recorded
        yet, and the sender can send it again. Always a COMPLETED run whose
        pending_prompt is the one short line to tell the sender.
        """
        state = loaded.state
        if is_informational(state.workflow_key):
            closing = await self.provide_input(loaded, "skip")
            if closing.status is WorkflowRunStatus.COMPLETED:
                return closing
            reloaded = await self._repo.get_awaiting_input(state.user_id)
            if reloaded is not None:
                loaded = reloaded
        await self._abandon(loaded)
        return WorkflowRunResult.completed(
            workflow_key=state.workflow_key,
            correlation_id=state.correlation_id,
            pending_prompt=QUESTION_DROPPED_NOTE,
        )

    async def _abandon(self, loaded: LoadedWorkflowInstance) -> None:
        """Close out an optional question the user moved on from.

        Best-effort by design: this runs on the path of a *new* report, and
        failing to tidy up an old offer must never cost the user the thing
        they actually just sent. A row left behind is retried on the next
        message anyway.
        """
        try:
            await self._repo.transition(
                loaded.state.workflow_instance_id,
                loaded.version,
                loaded.state.model_copy(
                    update={"awaiting_slot": None, "phase": WorkflowPhase.CANCELLED}
                ),
            )
        except Exception:  # noqa: BLE001 — tidying up never blocks new work
            logger.warning(
                "workflow.abandon_failed workflow_instance_id=%s",
                loaded.state.workflow_instance_id,
            )

    async def get_awaiting_confirmation(self, user_id: str) -> LoadedWorkflowInstance | None:
        """The user's single awaiting-confirmation instance, or None. Interactions
        talk only to the runtime, never the repo directly."""
        return await self._repo.get_awaiting_confirmation(user_id)

    async def get_awaiting_input(self, user_id: str) -> LoadedWorkflowInstance | None:
        """The user's single COLLECTING_FIELDS instance (pending slot
        question), or None. Interactions talk only to the runtime, never the
        repo directly."""
        return await self._repo.get_awaiting_input(user_id)

    async def resume(
        self, loaded: LoadedWorkflowInstance, action: ResumeAction
    ) -> WorkflowResumeResult:
        """Transition an AWAITING_CONFIRMATION workflow exactly once."""
        state = loaded.state
        instance_id = state.workflow_instance_id

        if state.phase is not WorkflowPhase.AWAITING_CONFIRMATION:
            logger.info(
                "workflow.not_resumable workflow_instance_id=%s phase=%s",
                instance_id,
                state.phase.value,
            )
            return WorkflowResumeResult(
                status=WorkflowResumeStatus.NOT_RESUMABLE,
                workflow_instance_id=instance_id,
                correlation_id=state.correlation_id,
            )

        # Guard before any write: a CONFIRM must be able to produce the handoff.
        # An awaiting instance should always carry a draft, but never half-
        # transition if it somehow doesn't.
        if action is ResumeAction.CONFIRM and state.draft_action is None:
            logger.error("workflow.confirm_without_draft workflow_instance_id=%s", instance_id)
            return WorkflowResumeResult(
                status=WorkflowResumeStatus.NOT_RESUMABLE,
                workflow_instance_id=instance_id,
                correlation_id=state.correlation_id,
            )

        new_phase = _RESUME_PHASE[action]
        new_state = state.model_copy(update={"phase": new_phase})

        applied = await self._repo.transition(instance_id, loaded.version, new_state)
        if not applied:
            # A concurrent transition already moved this instance (duplicate
            # delivery / double reply). Idempotent no-op.
            logger.info("workflow.already_resolved workflow_instance_id=%s", instance_id)
            return WorkflowResumeResult(
                status=WorkflowResumeStatus.ALREADY_RESOLVED,
                workflow_instance_id=instance_id,
                correlation_id=state.correlation_id,
            )

        if action is ResumeAction.CONFIRM:
            confirmed = ConfirmedActionV2(
                confirmed_action_id=new_id("confirmed"),
                workflow_instance_id=instance_id,
                correlation_id=state.correlation_id,
                draft_action=state.draft_action,
                confirmed_by_user_id=state.user_id,
            )
            return WorkflowResumeResult(
                status=WorkflowResumeStatus.CONFIRMED,
                workflow_instance_id=instance_id,
                correlation_id=state.correlation_id,
                confirmed_action=confirmed,
            )

        status = (
            WorkflowResumeStatus.REJECTED
            if action is ResumeAction.REJECT
            else WorkflowResumeStatus.CANCELLED
        )
        return WorkflowResumeResult(
            status=status,
            workflow_instance_id=instance_id,
            correlation_id=state.correlation_id,
        )


def log_workflow_run(result: WorkflowRunResult) -> None:
    """Log the WorkflowRunResult for development visibility (not user-facing)."""
    logger.info(
        "WorkflowRun correlation_id=%s workflow_key=%s status=%s workflow_instance_id=%s",
        result.correlation_id,
        result.workflow_key.value,
        result.status.value,
        result.workflow_instance_id or "none",
    )
