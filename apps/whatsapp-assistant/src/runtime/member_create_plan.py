"""Start CREATE_USER and hold the ADD_PROJECT_MEMBER that waits on it (a
two-step Plan in the shared PlanStore). Used by a shared contact card
(runtime/contact_share_journey.py); moved here from the retired
inbound_journey/resume.py (ARCH-06)."""

from __future__ import annotations

import logging

from backend.ports import ActorIdentity
from channel.replies import ReplySpec
from memory.recent_turns import RecentTurnsStore
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.canonical_event import IntentCompleteness as _IntentCompleteness
from mesiri_contracts.assistant.planner_decision import PlannerDecisionType, WorkflowKey
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from mesiri_contracts.common.ids import new_id as _new_id
from planning.plan import Plan, PlanOrigin, PlanStep, StepRef, StepStatus
from planning.plan_store import PlanStore
from runtime.inbound_journey.reply import _safe, render_workflow_run_reply_spec
from workflows import WorkflowRuntime
from workflows.create_user.nodes import find_mentioned_phone_number

_log = logging.getLogger("mesiri.inbound_journey")

_CREATE_USER_STEP_ID = "create_user"
_ADD_MEMBER_STEP_ID = "add_member"


async def start_member_create_plan(
    *,
    name_hint: str,
    original_event: CanonicalEventV2,
    actor: ActorIdentity | None,
    plan_store: PlanStore,
    workflow_runtime: WorkflowRuntime,
    recent_turns: RecentTurnsStore | None = None,
    whatsapp_number: str | None = None,
) -> ReplySpec | None:
    """Start CREATE_USER for real, and remember (in the shared PlanStore)
    that the held ADD_PROJECT_MEMBER request should resume once it succeeds.

    A Plan of exactly two steps -- create_user (RUNNING, started here) and
    add_member (PENDING, its member_name a StepRef pointing at create_user's
    full_name output) -- per ENTITY_RESOLUTION_PLAN.md sections 3.3/8.1: this
    is the entity-resolution layer's continuation, built on the shared
    Plan/PlanStep/PlanStore contracts rather than a standalone mechanism, so
    the composite-request plan layer's Phase 4 has one executor to extend
    rather than a second one to reconcile against.

    add_member's role/created_by_role/project_id travel as literals, copied
    from original_event -- they were already known before the Missing result
    paused this request and never depended on CREATE_USER's outcome. Only
    member_name is a StepRef, because it is the one field CREATE_USER's own
    execution determines (the exact name the new user was actually created
    under).

    Mirrors start_project_setup_followup's "hand-build a PlannerDecisionV2 +
    CanonicalEventV2, then call workflow_runtime.start()" pattern for
    starting CREATE_USER itself -- there is no lower-level shortcut. CREATE_
    USER's role is seeded from the SAME role hint the original add-member
    request carried (a project manager added as PM plausibly gets that as
    their org-wide role too).

    ``recent_turns``, when supplied, is checked for a phone number the
    sender already stated earlier in this conversation (e.g. "+91 97781
    90485 create Hysam in project hospital" -- ADD_PROJECT_MEMBER's own
    extraction has no phone-number field, so that number is otherwise
    dropped on the floor, and CREATE_USER re-asking for it several turns
    later reads as "I already told you that"). When found, it is seeded
    directly, so CREATE_USER's own build_draft has everything it needs on
    this very first pass and goes straight to its confirmation prompt --
    which already says "please double check this number", the existing
    safety net for a value the sender didn't just re-type on purpose. When
    not found (or ``recent_turns`` is None), CREATE_USER's own build_draft
    asks for it as before -- this is purely additive, never a regression on
    the case nothing was mentioned.

    Returns the full ReplySpec for CREATE_USER's own next question -- a
    Yes/No-buttoned confirmation if the number was recalled, otherwise a
    plain-text question (usually the phone number) -- or None if nothing
    could be started. Built via render_workflow_run_reply_spec, the one
    place that decides plain text vs buttons vs a tappable list for a
    WorkflowRunResult (see its own docstring): this function used to return
    only run.pending_prompt as a bare string, which meant a recalled number
    -- landing on STARTED, a real draft, on the very first call -- sent a
    plain-text "Reply YES to confirm or NO to cancel" instead of tappable
    buttons. That prompt was reachable before recall existed too, in
    principle, but recall is what actually made STARTED reachable from
    here on the very first pass; going through pending_prompt was correct
    right up until it wasn't. render_workflow_run_reply_spec's own
    docstring documents this exact bug class already happening once before,
    in the slot-answer fast path -- reusing it here instead of a second
    hand-rolled prompt extraction is what stops a third occurrence.
    """
    org_id = str(getattr(actor, "organization_id", None) or "")
    user_id = str(getattr(actor, "user_id", None) or "")
    if not org_id or not user_id:
        return None

    role_hint = original_event.fields.get("role")

    # ``whatsapp_number``, when given, is a number the sender handed over
    # explicitly (a shared contact card, SS-13) and is used as-is; recall
    # from recent turns is only the fallback for a typed request.
    recalled_number: str | None = whatsapp_number
    if recalled_number is None and recent_turns is not None:
        try:
            turns = await recent_turns.recent(user_id=user_id)
            recalled_number = find_mentioned_phone_number(t.user_text for t in turns)
        except Exception:  # noqa: BLE001 -- a recall miss just means CREATE_USER
            # asks for the number the normal way; never worth failing the
            # create-offer over.
            _log.warning("member_create_plan.recall_failed user=%s", user_id, exc_info=True)

    corr_id = _new_id("member_create")
    decision = PlannerDecisionV2(
        correlation_id=corr_id,
        source_message_id=corr_id,
        decision_type=PlannerDecisionType.START_WORKFLOW,
        workflow_key=WorkflowKey.CREATE_USER,
        reason=CanonicalEventType.CREATE_USER_REQUESTED,
        organization_id=org_id,
        user_id=user_id,
    )
    event_fields: dict[str, object] = {
        "full_name": name_hint,
        "role": role_hint,
        "created_by_role": getattr(actor, "role", None),
    }
    if recalled_number is not None:
        event_fields["whatsapp_number"] = recalled_number
    event = CanonicalEventV2(
        event_id=corr_id,
        correlation_id=corr_id,
        source_message_id=corr_id,
        event_type=CanonicalEventType.CREATE_USER_REQUESTED,
        completeness=_IntentCompleteness.ACTIONABLE,
        organization_id=org_id,
        user_id=user_id,
        fields=event_fields,
    )

    await _safe(workflow_runtime.abandon_optional_question(user_id))

    try:
        run = await workflow_runtime.start(decision, event)
    except Exception:  # noqa: BLE001 -- never raise into the tap handler
        _log.exception("member_create_plan.start_failed org=%s", org_id)
        return None
    if not run.pending_prompt:
        _log.error("member_create_plan.no_prompt org=%s status=%s", org_id, run.status.value)
        return None

    # Persisted only AFTER the workflow actually started, so the plan can
    # record the real workflow_instance_id it is waiting on -- the guard that
    # stops an abandoned plan from later attaching itself to a *different*
    # CREATE_USER the same user starts inside the TTL window (see
    # advance_member_plan_after_user_created). Storing first and patching
    # afterwards would leave a window where the plan matches any CREATE_USER;
    # storing after means a failed start simply leaves no plan behind at all,
    # which is also why the two failure branches above no longer need to
    # clear one.
    create_user_step = PlanStep(
        step_id=_CREATE_USER_STEP_ID,
        workflow_key=WorkflowKey.CREATE_USER,
        event_type=CanonicalEventType.CREATE_USER_REQUESTED,
        fields={"full_name": name_hint, "role": role_hint},
        status=StepStatus.RUNNING,
        workflow_instance_id=run.workflow_instance_id,
    )
    add_member_step = PlanStep(
        step_id=_ADD_MEMBER_STEP_ID,
        workflow_key=WorkflowKey.ADD_PROJECT_MEMBER,
        event_type=CanonicalEventType.ADD_PROJECT_MEMBER_REQUESTED,
        fields={
            "member_name": StepRef(step_id=_CREATE_USER_STEP_ID, output_key="full_name"),
            "role": role_hint,
            "created_by_role": original_event.fields.get("created_by_role"),
        },
        # Which project this adds to is SCOPE, not a collected field --
        # add_project_member reads it off the event, the same way
        # site_create reads state["project_id"]. Previously carried in
        # `fields` and popped back out by hand before building the event;
        # `scope` is now the typed home for it (plan-layer doc §11.1(b)).
        scope={"project_id": str(original_event.project_id or "")},
        status=StepStatus.PENDING,
    )
    plan = Plan(
        plan_id=_new_id("plan"),
        correlation_id=original_event.correlation_id,
        user_id=user_id,
        organization_id=org_id,
        origin=PlanOrigin.RESOLUTION,
        source_message_id=original_event.source_message_id,
        conversation_id=original_event.conversation_id,
        permissions=tuple(original_event.permissions),
        steps=(create_user_step, add_member_step),
    )
    await _safe(plan_store.start_plan(plan=plan))
    return render_workflow_run_reply_spec(run)
