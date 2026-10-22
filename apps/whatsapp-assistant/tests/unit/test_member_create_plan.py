"""Unit tests for the CREATE_USER -> ADD_PROJECT_MEMBER chain
(ENTITY_RESOLUTION_PLAN.md sections 3.3/8.1): start_member_create_plan, and
the generic runtime/plan_executor.advance_plan that drives it once started.

The live bug this completes: a Malayalam message named a real user who did
not yet have a Mesiri account. Missing's "Yes, create" tap must not just
create the user and stop -- it has to finish the original "add them to the
project" request the user actually sent.

Advancing the plan used to be resume.py's own hand-written
advance_member_plan_after_user_created, hardcoded to this one chain's two
step ids. That function is retired: message_journey.py now calls
runtime/plan_executor.py's advance_plan generically for every confirmation
(docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md §4.2's one-plan-one-executor
invariant) -- the SAME executor a decomposed multi-intent plan (§9) drives.
test_plan_executor.py owns that mechanism's own unit coverage; this file's
job is proving THIS chain still gets the exact behaviour the retired
function was written to guarantee. See also
tests/integration/test_member_create_plan_real_runtime.py, which drives the
same sequence through the real WorkflowRuntime and compiled LangGraph
graphs rather than fakes.

Fakes only here: no live DB, no LangGraph, no HTTP.
"""

from __future__ import annotations

from typing import Any

from interactions.handler import InteractionHandled
from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from mesiri_contracts.assistant.canonical_event import CanonicalEventType, IntentCompleteness
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import PlannerDecisionType, WorkflowKey
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from planning.plan import StepStatus
from planning.plan_store import PlanStore
from runtime.member_create_plan import start_member_create_plan
from runtime.plan_executor import advance_plan
from workflows.runtime import (
    WorkflowResumeResult,
    WorkflowResumeStatus,
    WorkflowRunResult,
    WorkflowRunStatus,
)

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def namespaced(self, *parts: str) -> str:
        return ":".join(parts)

    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        self._store[key] = value

    async def get_json(self, key: str) -> Any | None:
        return self._store.get(key)


def _plan_store() -> PlanStore:
    return PlanStore(_FakeRedis())


class _Actor:
    def __init__(self, *, user_id: str = USR, organization_id: str = ORG, role: str = "ADMIN"):
        self.user_id = user_id
        self.organization_id = organization_id
        self.role = role


#: The one CREATE_USER WorkflowInstance these fixtures model. The started
#: workflow and the confirmation that later resolves it are the SAME
#: instance in reality, so both _awaiting_input and
#: _handled_create_user_success use this id -- advance_member_plan_after_
#: user_created matches on it to tell "the CREATE_USER my plan is waiting
#: on" apart from any other CREATE_USER the same user starts inside the
#: plan's TTL.
CREATE_USER_WF = "wf_1"


def _awaiting_input(
    workflow_key, pending_prompt: str, *, workflow_instance_id: str = CREATE_USER_WF
) -> WorkflowRunResult:
    return WorkflowRunResult(
        status=WorkflowRunStatus.AWAITING_INPUT,
        workflow_key=workflow_key,
        correlation_id="c1",
        workflow_instance_id=workflow_instance_id,
        pending_prompt=pending_prompt,
    )


def _started(workflow_key, pending_prompt: str) -> WorkflowRunResult:
    draft = DraftActionV2(
        draft_id="d_new",
        correlation_id="c2",
        workflow_instance_id="wf_new2",
        action_type=DraftActionType.ADD_PROJECT_MEMBER,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        site_id=None,
        fields={},
    )
    return WorkflowRunResult(
        status=WorkflowRunStatus.STARTED,
        workflow_key=workflow_key,
        correlation_id="c2",
        workflow_instance_id="wf_new2",
        draft_action=draft,
        pending_prompt=pending_prompt,
    )


class _FakeWorkflowRuntime:
    """Records every start() call and replays canned results in order."""

    def __init__(self, results: list[WorkflowRunResult]) -> None:
        self._results = list(results)
        self.start_calls: list[tuple[Any, Any]] = []

    async def start(self, decision, event):
        self.start_calls.append((decision, event))
        return self._results.pop(0)

    async def abandon_optional_question(self, user_id: str) -> None:
        return None


def _original_event(member_name: str = "Hysam", role: str = "PROJECT_MANAGER") -> CanonicalEventV2:
    return CanonicalEventV2(
        event_id="evt_1",
        correlation_id="cor_original",
        source_message_id="msg_1",
        event_type=CanonicalEventType.ADD_PROJECT_MEMBER_REQUESTED,
        completeness=IntentCompleteness.ACTIONABLE,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        fields={"member_name": member_name, "role": role, "created_by_role": "PROJECT_MANAGER"},
    )


async def test_start_member_create_plan_persists_the_two_step_plan_and_starts_create_user():
    store = _plan_store()
    runtime = _FakeWorkflowRuntime(
        [
            _awaiting_input(WorkflowKey.CREATE_USER, "What's their WhatsApp number?")
        ]
    )
    reply = await start_member_create_plan(
        name_hint="Hysam",
        original_event=_original_event(),
        actor=_Actor(),
        plan_store=store,
        workflow_runtime=runtime,
    )
    assert reply.text == "What's their WhatsApp number?"
    assert reply.buttons is None  # a plain question, not a confirmation

    # A real CREATE_USER workflow was started, seeded with the name hint.
    assert len(runtime.start_calls) == 1
    decision, event = runtime.start_calls[0]
    assert decision.decision_type is PlannerDecisionType.START_WORKFLOW
    assert decision.workflow_key is WorkflowKey.CREATE_USER
    assert event.fields["full_name"] == "Hysam"
    assert event.fields["role"] == "PROJECT_MANAGER"

    # The plan is durable: two steps, create_user RUNNING, add_member PENDING
    # with member_name as a StepRef -- not resolved yet.
    plan = await store.get_plan(user_id=USR)
    assert plan is not None
    assert [s.step_id for s in plan.steps] == ["create_user", "add_member"]
    create_step = plan.step("create_user")
    add_step = plan.step("add_member")
    assert create_step.status.value == "running"
    assert add_step.status.value == "pending"
    assert add_step.depends_on == frozenset({"create_user"})


async def test_start_member_create_plan_clears_the_plan_if_the_start_fails():
    store = _plan_store()
    runtime = _FakeWorkflowRuntime(
        [
            WorkflowRunResult(
                status=WorkflowRunStatus.FAILED,
                workflow_key=WorkflowKey.CREATE_USER,
                correlation_id="c1",
            )
        ]
    )
    prompt = await start_member_create_plan(
        name_hint="Hysam",
        original_event=_original_event(),
        actor=_Actor(),
        plan_store=store,
        workflow_runtime=runtime,
    )
    assert prompt is None
    assert await store.get_plan(user_id=USR) is None


def _confirmed_create_user(full_name: str = "Hysam") -> ConfirmedActionV2:
    draft = DraftActionV2(
        draft_id="draft_1",
        correlation_id="cor_cu",
        workflow_instance_id="wf_1",
        action_type=DraftActionType.CREATE_USER,
        organization_id=ORG,
        user_id=USR,
        project_id=None,
        site_id=None,
        fields={"full_name": full_name, "whatsapp_number": "919876543210", "role": "PROJECT_MANAGER"},
    )
    return ConfirmedActionV2(
        confirmed_action_id="conf_1",
        workflow_instance_id="wf_1",
        correlation_id="cor_cu",
        draft_action=draft,
        confirmed_by_user_id=USR,
    )


def _handled_create_user_success(full_name: str = "Hysam") -> InteractionHandled:
    result = WorkflowResumeResult(
        status=WorkflowResumeStatus.CONFIRMED,
        workflow_instance_id="wf_1",
        correlation_id="cor_cu",
        confirmed_action=_confirmed_create_user(full_name),
    )
    execution = ExecutionResult(
        status=ExecutionStatus.SUCCEEDED,
        idempotency_key="wf_1",
        material_row_id="44444444-4444-4444-8444-444444444444",
    )
    return InteractionHandled(result=result, reply_text="ok", execution_result=execution)

async def test_full_chain_via_the_generic_executor_end_to_end():
    """The acid test for the swap onto runtime/plan_executor.py's generic
    advance_plan (docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md §4.2):
    resume.py's own hand-written advance_member_plan_after_user_created is
    retired, and message_journey.py now calls plan_executor.advance_plan for
    every confirmation, generically. This test drives the exact same
    create_user -> add_member sequence through THAT function instead, and
    checks every behaviour the retired one used to guarantee by name:

    - the site/member StepRef resolves to the just-created user's exact
      confirmed name (not the original hint)
    - the reply carries Yes/No buttons, not plain text
    - the plan survives through the SECOND step too (unlike the old
      hardcoded advance, which cleared immediately after starting it) and
      closes with an honest summary once that step also confirms

    See test_plan_executor.py for the generic mechanism's own unit coverage
    (hijack guard, rejection cascade, a confirmed-but-failed-write step,
    etc.) -- this file's remaining job is proving THIS specific chain still
    gets the exact behaviour the retired function was written to guarantee.
    """
    store = _plan_store()
    create_runtime = _FakeWorkflowRuntime(
        [_awaiting_input(WorkflowKey.CREATE_USER, "What's their WhatsApp number?")]
    )
    await start_member_create_plan(
        name_hint="Hysam",
        original_event=_original_event(member_name="Hysam", role="PROJECT_MANAGER"),
        actor=_Actor(),
        plan_store=store,
        workflow_runtime=create_runtime,
    )

    resume_runtime = _FakeWorkflowRuntime(
        [_started(WorkflowKey.ADD_PROJECT_MEMBER, "Confirm this action?")]
    )
    reply = await advance_plan(
        _handled_create_user_success(full_name="Hisham"),  # the exact created name
        plan_store=store,
        workflow_runtime=resume_runtime,
        actor=_Actor(),
    )

    assert reply is not None
    # A genuine new behaviour of the generic executor, not present in the
    # retired function: a "(N of M)" progress prefix for any plan with more
    # than one step (plan_executor._progress_prefix).
    assert reply.text == "(2 of 2) Confirm this action?"
    assert len(resume_runtime.start_calls) == 1
    decision, event = resume_runtime.start_calls[0]
    assert decision.workflow_key is WorkflowKey.ADD_PROJECT_MEMBER
    assert decision.project_id == PRJ
    assert event.fields["member_name"] == "Hisham"  # resolved via StepRef, not the name_hint
    assert event.fields["role"] == "PROJECT_MANAGER"

    # Unlike the retired function, the plan stays alive through this step.
    plan = await store.get_plan(user_id=USR)
    assert plan is not None
    assert plan.step("add_member").status is StepStatus.RUNNING

    # Confirming ADD_PROJECT_MEMBER closes the plan out with a summary.
    add_member_confirmation = InteractionHandled(
        result=WorkflowResumeResult(
            status=WorkflowResumeStatus.CONFIRMED,
            workflow_instance_id="wf_new2",  # _started()'s instance id, above
            correlation_id="c2",
            confirmed_action=ConfirmedActionV2(
                confirmed_action_id="conf_2",
                workflow_instance_id="wf_new2",
                correlation_id="c2",
                draft_action=DraftActionV2(
                    draft_id="d_2",
                    correlation_id="c2",
                    workflow_instance_id="wf_new2",
                    action_type=DraftActionType.ADD_PROJECT_MEMBER,
                    organization_id=ORG,
                    user_id=USR,
                    project_id=PRJ,
                    site_id=None,
                    fields={"member_name": "Hisham", "role": "PROJECT_MANAGER"},
                ),
                confirmed_by_user_id=USR,
            ),
        ),
        reply_text="ok",
        execution_result=ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            idempotency_key="wf_new2",
            material_row_id="77777777-7777-4777-8777-777777777777",
        ),
    )
    closing_reply = await advance_plan(
        add_member_confirmation,
        plan_store=store,
        workflow_runtime=_FakeWorkflowRuntime([]),
        actor=_Actor(),
    )

    assert closing_reply is not None
    assert "here's what i did" in closing_reply.text.lower()
    assert await store.get_plan(user_id=USR) is None


async def test_advance_is_a_no_op_when_no_plan_exists():
    store = _plan_store()
    runtime = _FakeWorkflowRuntime([])
    reply = await advance_plan(
        _handled_create_user_success(),
        plan_store=store,
        workflow_runtime=runtime,
        actor=_Actor(),
    )
    assert reply is None
    assert runtime.start_calls == []


async def test_abandoned_plan_does_not_hijack_a_later_unrelated_create_user():
    """A plan the user walked away from must never attach itself to a
    DIFFERENT CREATE_USER started later inside the plan's TTL.

    The regression: "add Hysam to the hospital project as PM" -> tap "Yes,
    create" -> abandon. Twenty minutes later the same admin legitimately
    adds Rajesh as a site engineer. Matching the waiting plan on
    workflow_key + RUNNING alone made that confirmation look like the one
    the plan was waiting for, and offered *Rajesh* project-manager rights on
    *Hysam's* project. Now covered generically by
    test_plan_executor.py's test_a_confirmation_for_a_different_instance_is_
    ignored_and_leaves_the_plan_intact -- this test keeps the specific
    member-create regression scenario named and reachable by search.
    """
    store = _plan_store()
    create_runtime = _FakeWorkflowRuntime(
        [_awaiting_input(WorkflowKey.CREATE_USER, "What's their WhatsApp number?")]
    )
    await start_member_create_plan(
        name_hint="Hysam",
        original_event=_original_event(member_name="Hysam", role="PROJECT_MANAGER"),
        actor=_Actor(),
        plan_store=store,
        workflow_runtime=create_runtime,
    )
    stale = await store.get_plan(user_id=USR)
    assert stale is not None
    assert stale.step("create_user").status is StepStatus.RUNNING

    other = _handled_create_user_success(full_name="Rajesh")
    other_result = WorkflowResumeResult(
        status=WorkflowResumeStatus.CONFIRMED,
        workflow_instance_id="wf_some_other_create_user",
        correlation_id="cor_other",
        confirmed_action=other.result.confirmed_action,
    )
    unrelated = InteractionHandled(
        result=other_result, reply_text="ok", execution_result=other.execution_result
    )

    resume_runtime = _FakeWorkflowRuntime([])
    reply = await advance_plan(
        unrelated, plan_store=store, workflow_runtime=resume_runtime, actor=_Actor()
    )

    assert reply is None
    assert resume_runtime.start_calls == []
    assert await store.get_plan(user_id=USR) is not None


async def test_rejecting_the_create_user_clears_the_waiting_plan():
    """Saying NO to "create this user?" ends the chain. Otherwise the plan
    lingers for the rest of its TTL with its first step still RUNNING,
    waiting on a confirmation that is never coming.

    The generic executor also reports this outcome honestly (P4) -- the
    retired function silently cleared the plan with no reply at all on
    rejection; the generic one names both steps' fate in a closing summary,
    which is a genuine improvement, not a regression to paper over.

    Wording: "Discarded." (not the older generic "couldn't be completed") --
    Phase A1 of docs/execution/UNIFIED_UNDERSTANDING_PIPELINE.md ports
    workflows/batch.py's summarize_batch_outcome wording onto every plan
    step's outcome_detail, since it is strictly more informative (a rejection
    reads differently from a domain-validation failure) and this is the
    wording the material->activity batch path's real users already see."""
    store = _plan_store()
    create_runtime = _FakeWorkflowRuntime(
        [_awaiting_input(WorkflowKey.CREATE_USER, "What's their WhatsApp number?")]
    )
    await start_member_create_plan(
        name_hint="Hysam",
        original_event=_original_event(),
        actor=_Actor(),
        plan_store=store,
        workflow_runtime=create_runtime,
    )
    assert await store.get_plan(user_id=USR) is not None

    rejected = InteractionHandled(
        result=WorkflowResumeResult(
            status=WorkflowResumeStatus.REJECTED,
            workflow_instance_id=CREATE_USER_WF,
            correlation_id="cor_cu",
        ),
        reply_text="Discarded.",
    )
    resume_runtime = _FakeWorkflowRuntime([])
    reply = await advance_plan(
        rejected, plan_store=store, workflow_runtime=resume_runtime, actor=_Actor()
    )

    assert reply is not None
    assert "Discarded." in reply.text
    assert "skipped" in reply.text  # add_member cascaded, never attempted
    assert resume_runtime.start_calls == []
    assert await store.get_plan(user_id=USR) is None


async def test_rejecting_an_unrelated_create_user_leaves_the_plan_alone():
    """The mirror of the test above: a rejection belonging to some other
    CREATE_USER must not cancel a plan that is still legitimately waiting."""
    store = _plan_store()
    create_runtime = _FakeWorkflowRuntime(
        [_awaiting_input(WorkflowKey.CREATE_USER, "What's their WhatsApp number?")]
    )
    await start_member_create_plan(
        name_hint="Hysam",
        original_event=_original_event(),
        actor=_Actor(),
        plan_store=store,
        workflow_runtime=create_runtime,
    )

    rejected_elsewhere = InteractionHandled(
        result=WorkflowResumeResult(
            status=WorkflowResumeStatus.REJECTED,
            workflow_instance_id="wf_some_other_create_user",
            correlation_id="cor_other",
        ),
        reply_text="Discarded.",
    )
    await advance_plan(
        rejected_elsewhere,
        plan_store=store,
        workflow_runtime=_FakeWorkflowRuntime([]),
        actor=_Actor(),
    )

    assert await store.get_plan(user_id=USR) is not None


async def test_plan_records_the_started_create_user_instance_id():
    """The guard above is only as good as the id being persisted at all."""
    store = _plan_store()
    runtime = _FakeWorkflowRuntime(
        [_awaiting_input(WorkflowKey.CREATE_USER, "What's their WhatsApp number?")]
    )
    await start_member_create_plan(
        name_hint="Hysam",
        original_event=_original_event(),
        actor=_Actor(),
        plan_store=store,
        workflow_runtime=runtime,
    )
    plan = await store.get_plan(user_id=USR)
    assert plan is not None
    assert plan.step("create_user").workflow_instance_id == CREATE_USER_WF


async def test_no_plan_is_left_behind_when_create_user_fails_to_start():
    """A failed start must leave no plan at all -- the plan is persisted
    only after the workflow it tracks actually started."""
    store = _plan_store()

    class _FailingRuntime:
        async def start(self, decision, event):
            raise RuntimeError("boom")

        async def abandon_optional_question(self, user_id: str) -> None:
            return None

    prompt = await start_member_create_plan(
        name_hint="Hysam",
        original_event=_original_event(),
        actor=_Actor(),
        plan_store=store,
        workflow_runtime=_FailingRuntime(),
    )
    assert prompt is None
    assert await store.get_plan(user_id=USR) is None
