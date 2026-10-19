"""The generic plan executor
(docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md §7.1/§7.4, P4/P6).

Drives a Plan of N steps to completion, one step at a time. Called from
runtime/message_journey.py's post-confirmation hook every time any workflow
confirmation resolves; a cheap no-op (one Redis read) when no plan is
waiting, which is the overwhelmingly common case.

## What this replaced

`resume.py` used to have its own advance_member_plan_after_user_created,
hardcoded to exactly two named step ids for exactly one chain. Correct at
the scale it was written for, but not general: an N-step decomposed plan
needs to advance from *whatever* step is running to *whatever* is next,
without either being named in code. This module is that loop; the retired
function's own chain is now just a plan of size 2 running through it
(§4.2's one-plan-one-executor invariant -- the whole reason PlanStore was
built N-capable from the start rather than as a size-1 store to widen
later). message_journey.py now calls this module's `advance_plan`
generically for every confirmation instead. See
tests/unit/test_member_create_plan.py and tests/integration/
test_member_create_plan_real_runtime.py for the falsification tests that
prove the swap: the retired function's own scenario, driven through this
generic path, against both fakes and a real WorkflowRuntime with real
compiled LangGraph graphs.

## Why every decision matches on workflow_instance_id

A plan outlives the turn that created it (PlanStore's 30-minute TTL), and a
user can abandon a running step and legitimately start a *different*
workflow of the same key inside that window. Matching on workflow_key +
RUNNING alone let an abandoned "create Hysam" plan attach itself to a later
unrelated "create Rajesh" and offer Rajesh project-manager rights on Hysam's
project (fixed in 1ba6462). An N-step plan has N times that exposure, so the
instance match is the executor's single most load-bearing guard.

## Failure semantics (ADR-C4)

A step that is rejected, cancelled, or fails to start marks FAILED, which
cascades CANCELLED to every step transitively depending on it -- those are
never attempted, because they would either fail anyway or attach to the
wrong parent. Steps that do NOT depend on it still run. The plan then
continues from the next runnable step rather than stopping, and the closing
summary reports every step's real outcome, success and failure alike (P4:
never a blanket "all done" that papers over a partial failure).
"""

from __future__ import annotations

from backend.ports import ActorIdentity
from channel.friendly_errors import friendly_rejection, is_question_rejection
from channel.replies import ReplySpec
from interactions.handler import InteractionHandled
from interactions.saved_summary import summarise_draft
from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from mesiri_contracts.assistant.planner_decision import PlannerDecisionType
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from mesiri_contracts.common.ids import new_id as _new_id
from planning.binding import build_event
from planning.outputs import build_step_outputs
from planning.plan import Plan, PlanOrigin, PlanStep, StepStatus
from planning.plan_store import PlanStore
from runtime.inbound_journey._shared import _log
from runtime.inbound_journey.reply import _safe, render_workflow_run_reply_spec
from workflows import WorkflowResumeResult, WorkflowResumeStatus, WorkflowRuntime
from workflows.readable import workflow_name

#: Execution outcomes that mean the step's write actually landed.
#: ALREADY_EXECUTED counts: an idempotent replay wrote nothing new but the
#: row exists, so a later step referencing its id must still resolve.
_SUCCEEDED = (ExecutionStatus.SUCCEEDED, ExecutionStatus.ALREADY_EXECUTED)


def _running_step_for(plan: Plan, workflow_instance_id: str | None) -> PlanStep | None:
    """The plan's RUNNING step matching this confirmation's instance, or
    None. Never falls back to "the only RUNNING step" when the id doesn't
    match -- that fallback is exactly the hijack this guard exists to
    prevent."""
    if not workflow_instance_id:
        return None
    for step in plan.steps:
        if (
            step.status is StepStatus.RUNNING
            and step.workflow_instance_id is not None
            and step.workflow_instance_id == workflow_instance_id
        ):
            return step
    return None


async def plan_defers_rejection(
    handled: InteractionHandled,
    *,
    plan_store: PlanStore,
    actor: ActorIdentity | None,
) -> bool:
    """True when this confirmation is a plan step that was rejected with a
    QUESTION ("Which site is this for?") and the plan has more to do.

    One question at a time (request [38]): the question is not sent now, next
    to the following step's Yes/No -- there a reply to it was read as the
    answer to the other one. The closing summary carries it instead, once
    nothing else is waiting."""
    result = handled.result
    execution = handled.execution_result
    if (
        not isinstance(result, WorkflowResumeResult)
        or execution is None
        or execution.status is not ExecutionStatus.REJECTED
        or not is_question_rejection(execution.rejection_reasons)
    ):
        return False
    user_id = str(getattr(actor, "user_id", None) or "")
    if not user_id:
        return False
    plan = await plan_store.get_plan(user_id=user_id)
    if plan is None:
        return False
    step = _running_step_for(plan, result.workflow_instance_id)
    if step is None:
        return False
    return any(s.status is StepStatus.PENDING for s in plan.steps)


async def plan_has_more_to_do(
    plan_store: PlanStore, *, user_id: str, finishing_instance_id: str | None = None
) -> bool:
    """True while a plan still has a step waiting or running other than the
    one that just resolved -- used to hold optional prompts (team photo,
    letterhead question) until the plan has finished."""
    if not user_id:
        return False
    plan = await plan_store.get_plan(user_id=user_id)
    if plan is None or plan.origin is PlanOrigin.SINGLE_MESSAGE:
        return False
    for step in plan.steps:
        if step.status is StepStatus.PENDING:
            return True
        if step.status is StepStatus.RUNNING and step.workflow_instance_id != finishing_instance_id:
            return True
    return False


def _progress_prefix(plan: Plan) -> str:
    """"(2 of 3) " -- so the user knows more is coming and where they are.
    Mirrors workflows/batch.py's format_batch_prefix wording exactly, since
    a user cannot tell which mechanism produced their message and the two
    must not describe progress differently. Omitted for a single-step plan,
    where there is no "more" to signal."""
    total = len(plan.steps)
    if total <= 1:
        return ""
    resolved = sum(
        1
        for s in plan.steps
        if s.status in (StepStatus.DONE, StepStatus.FAILED, StepStatus.CANCELLED)
    )
    return f"({min(resolved + 1, total)} of {total}) "


def _summarize_step_outcome(
    result: WorkflowResumeResult, execution_result: ExecutionResult | None
) -> str:
    """One plain-language line for a resolved step's entry in the closing
    summary. Ported verbatim (2026-07-31, Phase A1 of
    docs/execution/UNIFIED_UNDERSTANDING_PIPELINE.md) from workflows/batch.py's
    summarize_batch_outcome -- same wording, since a user cannot tell which
    mechanism produced their message and the two must not describe outcomes
    differently. This is the richer, execution-result-aware detail a bare
    StepStatus cannot carry (why a FAILED step failed, a conflict note on a
    DONE one) -- see PlanStep.outcome_detail."""
    if result.status is WorkflowResumeStatus.REJECTED:
        return "Discarded."
    if result.status is WorkflowResumeStatus.CANCELLED:
        return "Cancelled."
    if result.status is WorkflowResumeStatus.ALREADY_RESOLVED:
        return "Already handled."
    if result.status is WorkflowResumeStatus.NOT_RESUMABLE:
        return "Couldn't be resumed."
    # CONFIRMED
    if execution_result is None:
        return "Confirmed."
    if execution_result.status in (ExecutionStatus.SUCCEEDED, ExecutionStatus.ALREADY_EXECUTED):
        confirmed = getattr(result, "confirmed_action", None)
        summary = summarise_draft(confirmed.draft_action) if confirmed is not None else None
        head = f"Recorded ({summary})." if summary else "Recorded."
        if execution_result.conflict_note:
            return f"{head} {execution_result.conflict_note}"
        return head
    if execution_result.status is ExecutionStatus.REJECTED:
        line = friendly_rejection(execution_result.rejection_reasons, where="plan_step")
        if is_question_rejection(execution_result.rejection_reasons):
            return f"Not saved yet. {line}"
        return line
    return "Something went wrong — please resend this part."


def _outcome_line(step: PlanStep, index: int) -> str:
    """One plain-language line per step for the closing summary.

    Prefers ``outcome_detail`` (the execution-result-aware wording from
    ``_summarize_step_outcome``) when the step resolved through
    ``advance_plan``. Falls back to status-only wording for a step that
    never got that far -- CANCELLED (never attempted, ADR-C4) or a bind/start
    failure inside ``_start_next_runnable``, neither of which has an
    execution result to describe."""
    label = workflow_name(step.workflow_key.value)
    narrative = str(step.fields.get("narrative") or "").strip()
    if narrative and step.outcome_detail is not None and step.outcome_detail.startswith("Not saved"):
        # Name WHICH part still needs an answer, in the sender's own words.
        label = f"{label} (“{narrative[:80]}”)"
    if step.outcome_detail is not None:
        return f"{index}. {label}: {step.outcome_detail}"
    if step.status is StepStatus.DONE:
        return f"{index}. {label}: recorded"
    if step.status is StepStatus.FAILED:
        return f"{index}. {label}: couldn't be completed"
    if step.status is StepStatus.CANCELLED:
        return f"{index}. {label}: skipped (an earlier step didn't complete)"
    return f"{index}. {label}: not run"


def format_plan_summary(plan: Plan) -> str:
    """The closing block once every step has reached a terminal status.
    Every step gets exactly one line, in plan order, success and failure
    alike -- never a blanket "all done" that hides a partial failure (P4)."""
    lines = ["*Here's what I did:*"]
    lines.extend(_outcome_line(step, i + 1) for i, step in enumerate(plan.steps))
    return "\n".join(lines)


async def _start_next_runnable(
    *,
    user_id: str,
    plan_store: PlanStore,
    workflow_runtime: WorkflowRuntime,
) -> ReplySpec | None:
    """Start steps until one asks the user something, or the plan is done.

    Loops rather than starting exactly one step because a step can resolve
    without any user interaction -- it can fail to bind, fail to start, or
    complete informationally -- and a plan must not stall on one of those
    waiting for a confirmation that will never arrive. Every iteration moves
    exactly one step to a terminal status, so the loop is bounded by the
    number of steps.
    """
    plan = await plan_store.get_plan(user_id=user_id)
    if plan is None:
        return None

    for _ in range(len(plan.steps) + 1):
        step = await plan_store.next_runnable_step(user_id=user_id)
        if step is None:
            break

        plan = await plan_store.get_plan(user_id=user_id)
        if plan is None:
            return None

        # ADR-C2: the event is built here, immediately before the step runs
        # -- not earlier. Every StepRef it carries names a value that did not
        # exist until the step it points at actually executed.
        try:
            event = build_event(step, plan, correlation_id=_new_id("plan_step"))
        except Exception:  # noqa: BLE001 -- a binding failure is a contract bug
            # between producer and consumer, never a user-facing state. The
            # step is failed (cascading to its dependents) and the plan
            # continues, rather than the whole plan dying on one bad ref.
            _log.exception(
                "plan.bind_failed user=%s plan_id=%s step_id=%s", user_id, plan.plan_id, step.step_id
            )
            plan = await plan_store.mark_step_failed(user_id=user_id, step_id=step.step_id)
            continue

        decision = PlannerDecisionV2(
            correlation_id=event.correlation_id,
            source_message_id=event.source_message_id,
            decision_type=PlannerDecisionType.START_WORKFLOW,
            workflow_key=step.workflow_key,
            reason=step.event_type,
            organization_id=event.organization_id,
            user_id=event.user_id,
            project_id=event.project_id,
            site_id=event.site_id,
        )

        await _safe(workflow_runtime.abandon_optional_question(user_id))
        try:
            run = await workflow_runtime.start(decision, event)
        except Exception:  # noqa: BLE001 -- one step failing to start must not
            # take down the rest of the plan.
            _log.exception(
                "plan.step_start_failed user=%s plan_id=%s step_id=%s",
                user_id,
                plan.plan_id,
                step.step_id,
            )
            plan = await plan_store.mark_step_failed(user_id=user_id, step_id=step.step_id)
            continue

        if not run.pending_prompt:
            _log.error(
                "plan.step_no_prompt user=%s plan_id=%s step_id=%s status=%s",
                user_id,
                plan.plan_id,
                step.step_id,
                run.status.value,
            )
            plan = await plan_store.mark_step_failed(user_id=user_id, step_id=step.step_id)
            continue

        # Started and waiting on the user. Record which instance this step is
        # now running as -- the guard every later advance matches on.
        plan = await plan_store.mark_step_running(
            user_id=user_id,
            step_id=step.step_id,
            workflow_instance_id=run.workflow_instance_id,
        )
        spec = render_workflow_run_reply_spec(run)
        prefix = _progress_prefix(plan)
        if prefix:
            spec = ReplySpec(
                text=prefix + spec.text,
                list_button_label=spec.list_button_label,
                list_rows=spec.list_rows,
                buttons=spec.buttons,
            )
        return spec

    # Nothing left to run: report every step's real outcome and release the
    # plan so the next message starts clean.
    plan = await plan_store.get_plan(user_id=user_id)
    await _safe(plan_store.clear(user_id=user_id))
    if plan is None:
        return None
    if plan.origin is PlanOrigin.SINGLE_MESSAGE:
        # Phase A4 (docs/execution/UNIFIED_UNDERSTANDING_PIPELINE.md): an
        # ordinary single-intent message never showed an upfront multi-step
        # preview, so its own step's confirmation reply (already sent by
        # interactions/handler.py before this ever runs) is the whole story
        # -- a second "*Here's what I did:*" message here would be a pure,
        # user-visible regression for the ~95% of traffic this origin covers.
        return None
    return ReplySpec(text=format_plan_summary(plan))


async def begin_plan(
    *,
    user_id: str,
    plan_store: PlanStore,
    workflow_runtime: WorkflowRuntime,
) -> ReplySpec | None:
    """Start executing a Plan that is ALREADY persisted on ``plan_store``,
    with every step still PENDING -- the public name for
    _start_next_runnable, exposed for the one caller outside this module
    that needs to begin a plan without also persisting one:
    resume_pending_plan_confirmation (docs/execution/
    COMPOSITE_REQUEST_PLAN_LAYER.md §8), the Yes tap on the whole-plan
    preview. The preview itself persists the plan (all-PENDING, so it is
    inert and skipped by every advance_plan call until this runs) well
    before the user answers Yes/No -- see planning/preview.py and
    channel/replies.py's render_plan_preview_reply.
    """
    return await _start_next_runnable(
        user_id=user_id, plan_store=plan_store, workflow_runtime=workflow_runtime
    )


async def start_plan(
    plan: Plan,
    *,
    plan_store: PlanStore,
    workflow_runtime: WorkflowRuntime,
) -> ReplySpec | None:
    """Persist a freshly-built Plan and immediately start its first runnable
    step -- used by producers that skip the preview (today: the
    entity-resolution layer's 2-step member-create chain, which is already a
    direct continuation of a confirmation the user just answered, not a
    fresh multi-intent message that needs its own preview). The decomposer
    (§9) uses begin_plan above instead, via the preview's Yes tap.
    """
    await plan_store.start_plan(plan=plan)
    return await begin_plan(
        user_id=plan.user_id, plan_store=plan_store, workflow_runtime=workflow_runtime
    )


async def advance_plan(
    handled: InteractionHandled,
    *,
    plan_store: PlanStore,
    workflow_runtime: WorkflowRuntime,
    actor: ActorIdentity | None,
) -> ReplySpec | None:
    """Advance whatever plan this confirmation belongs to, or return None.

    None means "not mine" -- no plan waiting, or a confirmation belonging to
    some other workflow entirely. That is the common case for every ordinary
    single-workflow confirmation in the org, so it must stay cheap and
    silent.
    """
    result = handled.result
    if not isinstance(result, WorkflowResumeResult):
        return None

    user_id = str(getattr(actor, "user_id", None) or "")
    if not user_id:
        return None

    plan = await plan_store.get_plan(user_id=user_id)
    if plan is None:
        return None

    step = _running_step_for(plan, result.workflow_instance_id)
    if step is None:
        # A plan exists but this confirmation is not the one it is waiting
        # on. Left completely untouched: clearing here would let an
        # unrelated workflow silently cancel a legitimately waiting plan.
        # Logged, because a waiting plan plus a mismatched confirmation is
        # the one state worth being able to see -- it means either the
        # hijack guard just did its job or instance tracking is wrong, and
        # only this line tells those apart.
        _log.warning(
            "plan.instance_mismatch user=%s plan_id=%s confirmed_instance=%s",
            user_id,
            plan.plan_id,
            result.workflow_instance_id,
        )
        return None

    if result.status is WorkflowResumeStatus.CONFIRMED:
        execution = handled.execution_result
        confirmed = result.confirmed_action
        outcome_detail = _summarize_step_outcome(result, execution)
        if execution is not None and execution.status in _SUCCEEDED and confirmed is not None:
            await _safe(
                plan_store.mark_step_done(
                    user_id=user_id,
                    step_id=step.step_id,
                    outputs=build_step_outputs(
                        workflow_key=step.workflow_key,
                        row_id=execution.material_row_id,
                        draft_fields=confirmed.draft_action.fields,
                    ),
                    outcome_detail=outcome_detail,
                )
            )
        else:
            # Confirmed, but the write did not land (REJECTED by domain
            # validation, or FAILED). Treated exactly like a rejection: the
            # entity this step promised does not exist, so anything
            # depending on it cannot run.
            _log.info(
                "plan.step_execution_unsuccessful user=%s plan_id=%s step_id=%s status=%s",
                user_id,
                plan.plan_id,
                step.step_id,
                execution.status.value if execution else None,
            )
            await _safe(
                plan_store.mark_step_failed(
                    user_id=user_id, step_id=step.step_id, outcome_detail=outcome_detail
                )
            )
    elif result.status in (WorkflowResumeStatus.REJECTED, WorkflowResumeStatus.CANCELLED):
        # The user said no to this step. Its dependents cannot run -- you
        # cannot add a site to a project you just declined to create -- but
        # independent steps still should (ADR-C4).
        await _safe(
            plan_store.mark_step_failed(
                user_id=user_id,
                step_id=step.step_id,
                outcome_detail=_summarize_step_outcome(result, None),
            )
        )
    else:
        # ALREADY_RESOLVED / NOT_RESUMABLE: nothing changed, so the plan is
        # left exactly as it was rather than guessed at.
        return None

    return await _start_next_runnable(
        user_id=user_id, plan_store=plan_store, workflow_runtime=workflow_runtime
    )
