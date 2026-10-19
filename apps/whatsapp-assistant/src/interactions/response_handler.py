"""Interaction reply rendering — single source of truth for interaction-leg replies.

All text the assistant sends back to the user as a result of an interaction
(resume, blocked, ambiguous) is defined here. No business logic — purely
string rendering. Localisation / WhatsApp template migration happens here, not
in the callers.
"""

from __future__ import annotations

from channel.friendly_errors import friendly_rejection
from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from workflows import (
    WorkflowResumeResult,
    WorkflowResumeStatus,
    WorkflowRunResult,
    WorkflowRunStatus,
)


def render_resume_reply(result: WorkflowResumeResult) -> str:
    """Human-readable reply after a workflow interaction (confirm / reject / cancel).

    Localisation and rich WhatsApp templates are future work; string constants
    live here so the migration touches exactly one file.

    Note: the CONFIRMED branch here is only reached when no ExecutionDispatcher
    is wired (e.g. M7-only tests). When M8 execution runs, CONFIRMED replies go
    through render_execution_reply() instead, which reflects the real domain
    outcome rather than optimistically assuming a domain write happened.
    """
    if result.status is WorkflowResumeStatus.CONFIRMED:
        return "✅ Recorded. Thank you."
    if result.status is WorkflowResumeStatus.REJECTED:
        return "❌ Discarded. Nothing was recorded."
    if result.status is WorkflowResumeStatus.CANCELLED:
        return "Cancelled. Nothing was recorded."
    # ALREADY_RESOLVED (duplicate delivery / double reply) or NOT_RESUMABLE.
    return "That request was already handled."


def render_execution_reply(result: ExecutionResult) -> str:
    """Reply after M8 execution actually runs — reflects the real domain outcome,
    not just "the user confirmed" (fixes the M7 always-optimistic reply bug)."""
    if result.status in (ExecutionStatus.SUCCEEDED, ExecutionStatus.ALREADY_EXECUTED):
        # Conflict Resolution (#12): the write still succeeded -- this is
        # never a rejection -- but one narrower part of it (a concurrent
        # status transition) was safely held back rather than silently
        # overwriting what someone else already applied. Surfaced, not
        # swallowed: a user who thinks they just paused an activity that was
        # actually already completed by a colleague needs to know that.
        if result.conflict_note:
            return f"✅ Recorded. Thank you.\n\n{result.conflict_note}"
        return "✅ Recorded. Thank you."
    if result.status is ExecutionStatus.REJECTED:
        return f"⚠️ Couldn't record this. {friendly_rejection(result.rejection_reasons, where='reply')}"
    # FAILED
    return "⚠️ Something went wrong — we'll retry automatically."


def render_workflow_run_reply(
    result: WorkflowRunResult, *, pending_prompt: str | None = None
) -> str:
    """Reply to send after a workflow run.

    ``pending_prompt`` is the text produced by the workflow graph — passed in
    rather than read from ``result`` so the caller controls which prompt is used
    (e.g. the *existing* workflow's prompt when blocked).
    """
    if result.status is WorkflowRunStatus.FAILED:
        return "Sorry, I couldn't apply that update — please try again."
    if result.status is WorkflowRunStatus.BLOCKED_PENDING_CONFIRMATION:
        # Also reached when the block was actually a pending slot question
        # (Finance Module Slice 1) rather than a confirmation -- kept generic
        # ("this" not "the confirmation") so the wording fits both.
        #
        # The first line is load-bearing. What follows it is the EARLIER
        # report's prompt, not the one just sent, and the message the user
        # just sent is discarded (start() returns before saving anything).
        # Without saying so, the sequence reads as: send report -> see a
        # prompt -> reply "yes" -> "Recorded" -- and the user reasonably
        # believes they recorded what they just sent, when they confirmed
        # something older and their new report is gone. That was reported
        # from the deployed build on 2026-07-26 as "it recorded but I never
        # got a preview".
        return (
            "⏳ I haven't saved what you just sent — there's an earlier one "
            "still waiting for your answer:\n\n"
            f"{pending_prompt}\n\n"
            "Answer that first, then send yours again."
        )
    # STARTED / AWAITING_INPUT — show the workflow's next question directly.
    return pending_prompt or ""
