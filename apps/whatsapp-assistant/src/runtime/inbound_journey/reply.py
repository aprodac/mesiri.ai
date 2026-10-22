"""Reply-building helpers: JourneyResult, _safe, _complete_resume_leg, and the
logic that decides what the user hears back from a workflow run/resume."""

from __future__ import annotations

from collections.abc import Awaitable

from channel.replies import (
    CONFIRM_BUTTONS,
    ListRow,
    ReplySpec,
    render_unsupported_reply,
)
from interactions.response_handler import render_workflow_run_reply
from runtime.inbound_journey._shared import _log
from workflows import WorkflowRunResult, WorkflowRunStatus
from workflows.slots import BUTTON_ID_PREFIXES


async def _safe(coro: Awaitable[None]) -> None:
    """Await a logger coroutine, swallowing any exception."""
    try:
        await coro
    except Exception:  # noqa: BLE001
        _log.warning("logger call failed", exc_info=True)


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
