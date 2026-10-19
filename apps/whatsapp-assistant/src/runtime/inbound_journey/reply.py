"""Reply-building helpers: JourneyResult, _safe, _complete_resume_leg, and the
logic that decides what the user hears back from a workflow run/resume."""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass

from channel.replies import (
    CONFIRM_BUTTONS,
    ListRow,
    ReplySpec,
    render_clarify_reply,
    render_direct_reply,
    render_understanding_failed_reply,
    render_unsupported_reply,
)
from interactions.response_handler import render_workflow_run_reply
from mesiri_contracts.assistant.normalized_message import NormalizedMessage
from mesiri_contracts.assistant.planner_decision import PlannerDecisionType
from mesiri_contracts.assistant.understanding_result import UnderstandingResult
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from mesiri_contracts.assistant.v2.resolved_context import ResolvedContextV2
from runtime.inbound_journey._shared import _log
from runtime.logging_ports import MessageLogger
from workflows import WorkflowResumeResult, WorkflowRunResult, WorkflowRunStatus
from workflows.slots import BUTTON_ID_PREFIXES


@dataclass(slots=True)
class JourneyResult:
    understanding: UnderstandingResult
    resolved_context: ResolvedContextV2 | None
    canonical_event: CanonicalEventV2 | None
    planner_decision: PlannerDecisionV2 | None
    workflow_run: WorkflowRunResult | None
    workflow_resume: WorkflowResumeResult | None = None


async def _safe(coro: Awaitable[None]) -> None:
    """Await a logger coroutine, swallowing any exception."""
    try:
        await coro
    except Exception:  # noqa: BLE001
        _log.warning("logger call failed", exc_info=True)


async def _complete_resume_leg(
    message: NormalizedMessage,
    event: CanonicalEventV2,
    message_logger: MessageLogger | None,
) -> None:
    if message_logger is not None:
        await _safe(
            message_logger.update_context(
                correlation_id=message.correlation_id,
                project_id=event.project_id,
                site_id=event.site_id,
            )
        )
        # event.correlation_id survives every pop_pending/model_copy in the
        # material/unit/project gate chain unchanged -- it's always the
        # ORIGINAL report's correlation_id, even N gate-taps later. Tagging
        # every leg's own message with it (a plain string, not a workflow_
        # instance_id FK -- no workflow may exist yet) lets the logs viewer
        # resolve the whole picker chain to one interaction once a workflow
        # instance is eventually created from it (see message_logger.py's
        # list_recent/get_message_detail COALESCE join).
        await _safe(
            message_logger.set_interaction_group(
                correlation_id=message.correlation_id, group_id=event.correlation_id
            )
        )
        await _safe(message_logger.mark_completed(correlation_id=message.correlation_id))


def render_workflow_run_reply_spec(workflow_run: WorkflowRunResult) -> ReplySpec:
    """Turn a WorkflowRunResult into the ReplySpec it should be sent as --
    the one place that decides plain-text vs Yes/No buttons vs a tappable
    list, so every caller that can receive a WorkflowRunResult (starting a
    new workflow, or *resuming* one already in progress -- see
    runtime/dependencies.py's handle_slot_answer fast path) renders it the
    same way. Extracted out of `_render_reply` below (2026-07-26): the fast
    path for resuming a pending slot answer used to skip this entirely and
    always send plain text via send_text, so a resumed workflow that landed
    on STARTED (needs Yes/No) or AWAITING_INPUT (needs another list) never
    got its buttons/list -- exactly the "Reply YES to confirm or NO to
    cancel" plain-text bug a user hit right after answering the account
    slot.

    STARTED and BLOCKED_PENDING_CONFIRMATION are the two statuses actually
    asking the user to confirm a draft -- those get Yes/No buttons.
    AWAITING_INPUT (when the node supplied slot_options -- see
    workflows/slots.py's `slot_options`) gets a tappable list, when every
    label fits WhatsApp's limits. COMPLETED (who_am_i, inventory_query) is
    informational, nothing to confirm, so it stays plain text. NO_GRAPH
    means understood but no compiled graph exists yet. Every other status
    (FAILED, IGNORED, ...) falls back to plain rendered text."""
    if workflow_run.status in (
        WorkflowRunStatus.STARTED,
        WorkflowRunStatus.BLOCKED_PENDING_CONFIRMATION,
    ):
        return ReplySpec(
            text=render_workflow_run_reply(
                workflow_run, pending_prompt=workflow_run.pending_prompt
            ),
            buttons=CONFIRM_BUTTONS,
        )

    if workflow_run.status is WorkflowRunStatus.AWAITING_INPUT:
        text = render_workflow_run_reply(workflow_run, pending_prompt=workflow_run.pending_prompt)
        # A tapped row normalizes to NormalizedMessage.text = its title
        # (ingress/normalization.py's _resolve_interactive_reply), matched
        # by match_slot_answer exactly like a typed reply -- so title must
        # equal the candidate's own label, byte for byte. WhatsApp caps a
        # list at 10 rows and a row title at 24 chars; degrade to plain
        # text (still answerable by typing) rather than send a request Meta
        # would reject outright.
        options = workflow_run.slot_options
        # The worker-promotion questions (ids promo_* / dup_*) are one-tap
        # reply buttons rather than a list to open; every other slot keeps its
        # list. A tapped button comes back with its id (interactions/handler.py).
        if (
            options
            and len(options) <= 3
            and all(o.value.startswith(BUTTON_ID_PREFIXES) and len(o.label) <= 20 for o in options)
        ):
            return ReplySpec(
                text=text,
                buttons=tuple(ListRow(o.value, o.label) for o in options),
            )
        if options and 1 < len(options) <= 10 and all(len(o.label) <= 24 for o in options):
            return ReplySpec(
                text=text,
                list_button_label="Choose one",
                list_rows=tuple(ListRow(o.value, o.label) for o in options),
            )
        return ReplySpec(text=text)

    if workflow_run.status is WorkflowRunStatus.COMPLETED:
        return ReplySpec(
            text=render_workflow_run_reply(workflow_run, pending_prompt=workflow_run.pending_prompt)
        )

    if workflow_run.status is WorkflowRunStatus.NO_GRAPH:
        # Understood, but this WorkflowKey has no graph registered.
        # Equipment usage is the only such key left today; the reply lists
        # what *is* built, generated from workflows/registry.py.
        return ReplySpec(text=render_unsupported_reply())

    return ReplySpec(
        text=render_workflow_run_reply(workflow_run, pending_prompt=workflow_run.pending_prompt)
    )


def _render_reply(
    workflow_run: WorkflowRunResult | None,
    workflow_resume: WorkflowResumeResult | None,
    decision: PlannerDecisionV2 | None,
    resolved: ResolvedContextV2 | None,
    *,
    is_first_message: bool = False,
) -> ReplySpec | None:
    """The single place that decides what the user hears back.

    Returns None only when the interaction leg has already replied. Every other
    path must produce something: a message that reaches the assistant and gets
    no answer is indistinguishable from Mesiri being down.

    Every workflow_run status is delegated to render_workflow_run_reply_spec
    above; everything else (a fresh decision with no workflow at all) is
    handled here.
    """
    if workflow_run is not None and workflow_run.status is not WorkflowRunStatus.FAILED:
        return render_workflow_run_reply_spec(workflow_run)

    if workflow_resume is not None:
        return None  # interactions/handler.py already sent its own reply

    if decision is not None:
        if decision.decision_type is PlannerDecisionType.CLARIFY:
            return ReplySpec(text=render_clarify_reply(decision))
        if decision.decision_type is PlannerDecisionType.DIRECT_REPLY:
            # is_first_message is resolved by the caller, which is async and
            # can do the inbound_messages lookup this needs (see
            # runtime/first_message_query.py). False here means either a
            # returning sender or a failed lookup -- both render the shorter
            # copy, which is the safe way to be wrong.
            return render_direct_reply(
                decision,
                timezone=resolved.timezone if resolved else None,
                is_first_message=is_first_message,
            )

    # Context resolution failed, understanding was UNUSABLE, the workflow run
    # FAILED, or the planner said IGNORE. Never fall through to format_reply():
    # that is a developer diagnostic ("Type: unknown / Confidence: unusable"),
    # not a reply a site worker should ever receive.
    return ReplySpec(text=render_understanding_failed_reply())
