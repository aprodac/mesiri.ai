"""Unit tests for runtime/plan_executor.py -- the generic N-step plan loop
(docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md §7.1/§7.4).

Fakes only: no live DB, no LangGraph, no HTTP. Mirrors
test_member_create_plan.py's fixture shapes, since that file covers the same
machinery hardcoded to one two-step chain and this one covers it generalized.
"""

from __future__ import annotations

from typing import Any

from interactions.handler import InteractionHandled
from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from planning.plan import Plan, PlanOrigin, PlanStep, StepRef, StepStatus
from planning.plan_store import PlanStore
from runtime.plan_executor import advance_plan, format_plan_summary
from workflows.runtime import (
    WorkflowResumeResult,
    WorkflowResumeStatus,
    WorkflowRunResult,
    WorkflowRunStatus,
)

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "55555555-5555-4555-8555-555555555555"


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


class _FakeWorkflowRuntime:
    """Replays canned WorkflowRunResults in order, recording every start."""

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.start_calls: list[tuple[Any, Any]] = []

    async def start(self, decision, event):
        self.start_calls.append((decision, event))
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def abandon_optional_question(self, user_id: str) -> None:
        return None


def _started(workflow_key, prompt: str, instance: str) -> WorkflowRunResult:
    draft = DraftActionV2(
        draft_id=f"d_{instance}",
        correlation_id=f"c_{instance}",
        workflow_instance_id=instance,
        action_type=DraftActionType.CREATE_SITE,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        site_id=None,
        fields={},
    )
    return WorkflowRunResult(
        status=WorkflowRunStatus.STARTED,
        workflow_key=workflow_key,
        correlation_id=f"c_{instance}",
        workflow_instance_id=instance,
        draft_action=draft,
        pending_prompt=prompt,
    )


def _confirmation(
    instance: str,
    *,
    action_type: DraftActionType,
    row_id: str | None = PRJ,
    fields: dict | None = None,
    status: WorkflowResumeStatus = WorkflowResumeStatus.CONFIRMED,
    execution_status: ExecutionStatus = ExecutionStatus.SUCCEEDED,
) -> InteractionHandled:
    confirmed = None
    execution = None
    if status is WorkflowResumeStatus.CONFIRMED:
        draft = DraftActionV2(
            draft_id=f"draft_{instance}",
            correlation_id=f"cor_{instance}",
            workflow_instance_id=instance,
            action_type=action_type,
            organization_id=ORG,
            user_id=USR,
            project_id=None,
            site_id=None,
            fields=fields or {},
        )
        confirmed = ConfirmedActionV2(
            confirmed_action_id=f"conf_{instance}",
            workflow_instance_id=instance,
            correlation_id=f"cor_{instance}",
            draft_action=draft,
            confirmed_by_user_id=USR,
        )
        if execution_status in (ExecutionStatus.SUCCEEDED, ExecutionStatus.ALREADY_EXECUTED):
            execution = ExecutionResult(
                status=execution_status, idempotency_key=instance, material_row_id=row_id
            )
        else:
            execution = ExecutionResult(
                status=ExecutionStatus.FAILED, idempotency_key=instance
            )
    return InteractionHandled(
        result=WorkflowResumeResult(
            status=status,
            workflow_instance_id=instance,
            correlation_id=f"cor_{instance}",
            confirmed_action=confirmed,
        ),
        reply_text="ok",
        execution_result=execution,
    )


def _starship_plan(*, running_instance: str = "wf_1") -> Plan:
    """project Starship (RUNNING) -> site Site A (scope ref) -> user Hysam."""
    return Plan(
        plan_id="plan_starship",
        correlation_id="cor_starship",
        user_id=USR,
        organization_id=ORG,
        origin=PlanOrigin.DECOMPOSITION,
        source_message_id="msg_starship",
        permissions=("projects:write",),
        steps=(
            PlanStep(
                step_id="s1",
                workflow_key=WorkflowKey.PROJECT_CREATE,
                event_type=CanonicalEventType.PROJECT_CREATE_REQUESTED,
                fields={"name": "Starship"},
                status=StepStatus.RUNNING,
                workflow_instance_id=running_instance,
            ),
            PlanStep(
                step_id="s2",
                workflow_key=WorkflowKey.SITE_CREATE,
                event_type=CanonicalEventType.SITE_CREATE_REQUESTED,
                fields={"name": "Site A"},
                scope={"project_id": StepRef("s1", "project_id")},
            ),
            PlanStep(
                step_id="s3",
                workflow_key=WorkflowKey.CREATE_USER,
                event_type=CanonicalEventType.CREATE_USER_REQUESTED,
                fields={"full_name": "Hysam"},
            ),
        ),
    )


def test_summarize_step_outcome_matches_workflows_batch_wording_exactly():
    """Phase A1 (docs/execution/UNIFIED_UNDERSTANDING_PIPELINE.md) ports
    workflows/batch.py's summarize_batch_outcome verbatim, since a user
    cannot tell which mechanism produced their message. This locks the
    wording to the source it was ported from -- see
    test_batch_workflow.py::test_summarize_batch_outcome_* for the original.

    ALREADY_RESOLVED/NOT_RESUMABLE are ported for wording parity but are not
    currently reachable through advance_plan (which leaves the plan
    untouched for those two statuses, unchanged from before this port --
    see test_already_resolved_leaves_the_plan_untouched below)."""
    from runtime.plan_executor import _summarize_step_outcome

    rejected = WorkflowResumeResult(
        status=WorkflowResumeStatus.REJECTED, workflow_instance_id="wf_1", correlation_id="c"
    )
    cancelled = WorkflowResumeResult(
        status=WorkflowResumeStatus.CANCELLED, workflow_instance_id="wf_1", correlation_id="c"
    )
    already_resolved = WorkflowResumeResult(
        status=WorkflowResumeStatus.ALREADY_RESOLVED, workflow_instance_id="wf_1", correlation_id="c"
    )
    not_resumable = WorkflowResumeResult(
        status=WorkflowResumeStatus.NOT_RESUMABLE, workflow_instance_id="wf_1", correlation_id="c"
    )
    _draft = DraftActionV2(
        draft_id="draft_x",
        correlation_id="c",
        workflow_instance_id="wf_1",
        action_type=DraftActionType.CREATE_PROJECT,
        organization_id=ORG,
        user_id=USR,
        project_id=None,
        site_id=None,
        fields={},
    )
    confirmed = WorkflowResumeResult(
        status=WorkflowResumeStatus.CONFIRMED,
        workflow_instance_id="wf_1",
        correlation_id="c",
        confirmed_action=ConfirmedActionV2(
            confirmed_action_id="conf_x",
            workflow_instance_id="wf_1",
            correlation_id="c",
            draft_action=_draft,
            confirmed_by_user_id=USR,
        ),
    )

    assert _summarize_step_outcome(rejected, None) == "Discarded."
    assert _summarize_step_outcome(cancelled, None) == "Cancelled."
    assert _summarize_step_outcome(already_resolved, None) == "Already handled."
    assert _summarize_step_outcome(not_resumable, None) == "Couldn't be resumed."
    assert _summarize_step_outcome(confirmed, None) == "Confirmed."
    assert (
        _summarize_step_outcome(
            confirmed,
            ExecutionResult(status=ExecutionStatus.SUCCEEDED, idempotency_key="k", material_row_id="r"),
        )
        == "Recorded."
    )
    assert (
        _summarize_step_outcome(
            confirmed,
            ExecutionResult(
                status=ExecutionStatus.SUCCEEDED,
                idempotency_key="k",
                material_row_id="r",
                conflict_note="Note: x.",
            ),
        )
        == "Recorded. Note: x."
    )
    assert (
        _summarize_step_outcome(
            confirmed,
            ExecutionResult(
                status=ExecutionStatus.REJECTED, idempotency_key="k", rejection_reasons=["unit is required", "a b c"]
            ),
        )
        == "Which unit is that in — bags, kg, sqm, nos?"
    )
    assert (
        _summarize_step_outcome(
            confirmed, ExecutionResult(status=ExecutionStatus.FAILED, idempotency_key="k")
        )
        == "Something went wrong — please resend this part."
    )


async def test_no_plan_is_a_silent_no_op():
    store = _plan_store()
    runtime = _FakeWorkflowRuntime([])
    reply = await advance_plan(
        _confirmation("wf_x", action_type=DraftActionType.CREATE_USER),
        plan_store=store,
        workflow_runtime=runtime,
        actor=_Actor(),
    )
    assert reply is None
    assert runtime.start_calls == []


async def test_confirming_step_one_publishes_its_id_and_starts_step_two_bound_to_it():
    """The whole point: the site step's StepRef resolves to the project just
    created, and lands on the event's project_id -- not in fields."""
    store = _plan_store()
    await store.start_plan(plan=_starship_plan())
    runtime = _FakeWorkflowRuntime([_started(WorkflowKey.SITE_CREATE, "Create Site A?", "wf_2")])

    reply = await advance_plan(
        _confirmation("wf_1", action_type=DraftActionType.CREATE_PROJECT, row_id=PRJ),
        plan_store=store,
        workflow_runtime=runtime,
        actor=_Actor(),
    )

    assert reply is not None
    assert "Create Site A?" in reply.text
    assert len(runtime.start_calls) == 1
    _decision, event = runtime.start_calls[0]
    assert str(event.project_id) == PRJ  # the ref resolved, onto scope
    assert "project_id" not in event.fields

    plan = await store.get_plan(user_id=USR)
    assert plan.step("s1").status is StepStatus.DONE
    assert plan.step("s1").outputs["project_id"] == PRJ
    assert plan.step("s2").status is StepStatus.RUNNING
    assert plan.step("s2").workflow_instance_id == "wf_2"


async def test_progress_prefix_tells_the_user_where_they_are():
    store = _plan_store()
    await store.start_plan(plan=_starship_plan())
    runtime = _FakeWorkflowRuntime([_started(WorkflowKey.SITE_CREATE, "Create Site A?", "wf_2")])

    reply = await advance_plan(
        _confirmation("wf_1", action_type=DraftActionType.CREATE_PROJECT),
        plan_store=store,
        workflow_runtime=runtime,
        actor=_Actor(),
    )
    assert reply.text.startswith("(2 of 3) ")


async def test_a_confirmation_for_a_different_instance_is_ignored_and_leaves_the_plan_intact():
    """The hijack guard, generalized. A plan waiting on wf_1 must not
    advance on some unrelated workflow's confirmation."""
    store = _plan_store()
    await store.start_plan(plan=_starship_plan())
    runtime = _FakeWorkflowRuntime([])

    reply = await advance_plan(
        _confirmation("wf_somebody_else", action_type=DraftActionType.CREATE_USER),
        plan_store=store,
        workflow_runtime=runtime,
        actor=_Actor(),
    )

    assert reply is None
    assert runtime.start_calls == []
    plan = await store.get_plan(user_id=USR)
    assert plan is not None  # untouched, not cleared
    assert plan.step("s1").status is StepStatus.RUNNING


async def test_rejecting_a_step_cancels_its_dependents_but_runs_independent_ones():
    """ADR-C4. Declining the project means no site can be created under it,
    but creating the user was never contingent on it."""
    store = _plan_store()
    await store.start_plan(plan=_starship_plan())
    runtime = _FakeWorkflowRuntime(
        [_started(WorkflowKey.CREATE_USER, "What's their number?", "wf_3")]
    )

    reply = await advance_plan(
        _confirmation(
            "wf_1",
            action_type=DraftActionType.CREATE_PROJECT,
            status=WorkflowResumeStatus.REJECTED,
        ),
        plan_store=store,
        workflow_runtime=runtime,
        actor=_Actor(),
    )

    assert reply is not None
    assert "What's their number?" in reply.text
    plan = await store.get_plan(user_id=USR)
    assert plan.step("s1").status is StepStatus.FAILED
    assert plan.step("s2").status is StepStatus.CANCELLED  # depended on s1
    assert plan.step("s3").status is StepStatus.RUNNING  # independent


async def test_a_confirmed_step_whose_write_failed_is_treated_as_a_failure():
    """"Yes" followed by a domain rejection means the project does not
    exist, so the site step must not run against a phantom parent."""
    store = _plan_store()
    await store.start_plan(plan=_starship_plan())
    runtime = _FakeWorkflowRuntime(
        [_started(WorkflowKey.CREATE_USER, "What's their number?", "wf_3")]
    )

    await advance_plan(
        _confirmation(
            "wf_1",
            action_type=DraftActionType.CREATE_PROJECT,
            execution_status=ExecutionStatus.FAILED,
        ),
        plan_store=store,
        workflow_runtime=runtime,
        actor=_Actor(),
    )

    plan = await store.get_plan(user_id=USR)
    assert plan.step("s1").status is StepStatus.FAILED
    assert plan.step("s2").status is StepStatus.CANCELLED


async def test_a_conflict_note_on_success_is_appended_to_the_summary_line():
    """Phase A1: outcome_detail carries workflows/batch.py's
    summarize_batch_outcome wording, including a conflict note on an
    otherwise-successful write (#12 Conflict Resolution) -- not just a bare
    "recorded"."""
    store = _plan_store()
    plan = Plan(
        plan_id="plan_conflict",
        correlation_id="cor_conflict",
        user_id=USR,
        organization_id=ORG,
        origin=PlanOrigin.DECOMPOSITION,
        steps=(
            PlanStep(
                step_id="s1",
                workflow_key=WorkflowKey.PROJECT_CREATE,
                event_type=CanonicalEventType.PROJECT_CREATE_REQUESTED,
                fields={"name": "Starship"},
                status=StepStatus.RUNNING,
                workflow_instance_id="wf_1",
            ),
        ),
    )
    await store.start_plan(plan=plan)
    runtime = _FakeWorkflowRuntime([])

    draft = DraftActionV2(
        draft_id="draft_wf_1",
        correlation_id="cor_wf_1",
        workflow_instance_id="wf_1",
        action_type=DraftActionType.CREATE_PROJECT,
        organization_id=ORG,
        user_id=USR,
        project_id=None,
        site_id=None,
        fields={},
    )
    confirmed = ConfirmedActionV2(
        confirmed_action_id="conf_wf_1",
        workflow_instance_id="wf_1",
        correlation_id="cor_wf_1",
        draft_action=draft,
        confirmed_by_user_id=USR,
    )
    handled = InteractionHandled(
        result=WorkflowResumeResult(
            status=WorkflowResumeStatus.CONFIRMED,
            workflow_instance_id="wf_1",
            correlation_id="cor_wf_1",
            confirmed_action=confirmed,
        ),
        reply_text="ok",
        execution_result=ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            idempotency_key="wf_1",
            material_row_id=PRJ,
            conflict_note="Note: already marked Completed.",
        ),
    )

    reply = await advance_plan(handled, plan_store=store, workflow_runtime=runtime, actor=_Actor())

    assert reply is not None
    assert "Recorded. Note: already marked Completed." in reply.text


async def test_a_domain_rejection_reason_is_named_in_the_summary_line():
    """Same wording source as above -- a REJECTED execution names the actual
    rejection reason(s), not a generic "couldn't be completed"."""
    store = _plan_store()
    plan = Plan(
        plan_id="plan_rejected",
        correlation_id="cor_rejected",
        user_id=USR,
        organization_id=ORG,
        origin=PlanOrigin.DECOMPOSITION,
        steps=(
            PlanStep(
                step_id="s1",
                workflow_key=WorkflowKey.PROJECT_CREATE,
                event_type=CanonicalEventType.PROJECT_CREATE_REQUESTED,
                fields={"name": "Starship"},
                status=StepStatus.RUNNING,
                workflow_instance_id="wf_1",
            ),
        ),
    )
    await store.start_plan(plan=plan)
    runtime = _FakeWorkflowRuntime([])

    draft = DraftActionV2(
        draft_id="draft_wf_1",
        correlation_id="cor_wf_1",
        workflow_instance_id="wf_1",
        action_type=DraftActionType.CREATE_PROJECT,
        organization_id=ORG,
        user_id=USR,
        project_id=None,
        site_id=None,
        fields={},
    )
    confirmed = ConfirmedActionV2(
        confirmed_action_id="conf_wf_1",
        workflow_instance_id="wf_1",
        correlation_id="cor_wf_1",
        draft_action=draft,
        confirmed_by_user_id=USR,
    )
    handled = InteractionHandled(
        result=WorkflowResumeResult(
            status=WorkflowResumeStatus.CONFIRMED,
            workflow_instance_id="wf_1",
            correlation_id="cor_wf_1",
            confirmed_action=confirmed,
        ),
        reply_text="ok",
        execution_result=ExecutionResult(
            status=ExecutionStatus.REJECTED,
            idempotency_key="wf_1",
            rejection_reasons=["a project with this name already exists"],
        ),
    )

    reply = await advance_plan(handled, plan_store=store, workflow_runtime=runtime, actor=_Actor())

    assert reply is not None
    assert "That already exists, so I didn't add it again." in reply.text
    assert "a project with this name already exists" not in reply.text
    assert "New project" in reply.text  # named in plain words, not the workflow key


async def test_the_last_step_completing_clears_the_plan_and_returns_a_summary():
    store = _plan_store()
    plan = Plan(
        plan_id="plan_1",
        correlation_id="cor_1",
        user_id=USR,
        organization_id=ORG,
        origin=PlanOrigin.DECOMPOSITION,
        steps=(
            PlanStep(
                step_id="s1",
                workflow_key=WorkflowKey.PROJECT_CREATE,
                event_type=CanonicalEventType.PROJECT_CREATE_REQUESTED,
                fields={"name": "Starship"},
                status=StepStatus.RUNNING,
                workflow_instance_id="wf_1",
            ),
        ),
    )
    await store.start_plan(plan=plan)
    runtime = _FakeWorkflowRuntime([])

    reply = await advance_plan(
        _confirmation("wf_1", action_type=DraftActionType.CREATE_PROJECT),
        plan_store=store,
        workflow_runtime=runtime,
        actor=_Actor(),
    )

    assert reply is not None
    assert "Here's what I did" in reply.text
    # "Recorded." (not the older generic "recorded") -- Phase A1 of
    # docs/execution/UNIFIED_UNDERSTANDING_PIPELINE.md ports
    # workflows/batch.py's summarize_batch_outcome wording onto
    # PlanStep.outcome_detail, since it is strictly more informative (a
    # conflict note, a specific rejection reason) than a bare status label.
    assert "Recorded." in reply.text
    assert await store.get_plan(user_id=USR) is None  # released


async def test_a_step_that_fails_to_start_does_not_stall_the_plan():
    """The loop must move past a step that raises on start, rather than
    waiting forever for a confirmation that will never arrive."""
    store = _plan_store()
    await store.start_plan(plan=_starship_plan())
    runtime = _FakeWorkflowRuntime(
        [
            RuntimeError("site create blew up"),
            _started(WorkflowKey.CREATE_USER, "What's their number?", "wf_3"),
        ]
    )

    reply = await advance_plan(
        _confirmation("wf_1", action_type=DraftActionType.CREATE_PROJECT),
        plan_store=store,
        workflow_runtime=runtime,
        actor=_Actor(),
    )

    assert reply is not None
    assert "What's their number?" in reply.text
    plan = await store.get_plan(user_id=USR)
    assert plan.step("s2").status is StepStatus.FAILED
    assert plan.step("s3").status is StepStatus.RUNNING


async def test_already_resolved_leaves_the_plan_untouched():
    store = _plan_store()
    await store.start_plan(plan=_starship_plan())
    runtime = _FakeWorkflowRuntime([])

    reply = await advance_plan(
        _confirmation(
            "wf_1",
            action_type=DraftActionType.CREATE_PROJECT,
            status=WorkflowResumeStatus.ALREADY_RESOLVED,
        ),
        plan_store=store,
        workflow_runtime=runtime,
        actor=_Actor(),
    )

    assert reply is None
    plan = await store.get_plan(user_id=USR)
    assert plan.step("s1").status is StepStatus.RUNNING


async def test_summary_reports_every_step_honestly_including_failures():
    plan = Plan(
        plan_id="p",
        correlation_id="c",
        user_id=USR,
        organization_id=ORG,
        origin=PlanOrigin.DECOMPOSITION,
        steps=(
            PlanStep(
                step_id="s1",
                workflow_key=WorkflowKey.PROJECT_CREATE,
                event_type=CanonicalEventType.PROJECT_CREATE_REQUESTED,
                fields={},
                status=StepStatus.DONE,
            ),
            PlanStep(
                step_id="s2",
                workflow_key=WorkflowKey.SITE_CREATE,
                event_type=CanonicalEventType.SITE_CREATE_REQUESTED,
                fields={},
                status=StepStatus.FAILED,
            ),
            PlanStep(
                step_id="s3",
                workflow_key=WorkflowKey.SITE_UPDATE,
                event_type=CanonicalEventType.GENERAL_SITE_UPDATE_REQUESTED,
                fields={},
                status=StepStatus.CANCELLED,
            ),
        ),
    )
    summary = format_plan_summary(plan)
    assert "recorded" in summary
    assert "couldn't be completed" in summary
    assert "skipped" in summary
    # Never a blanket "all done" that hides the two that didn't happen (P4).
    assert summary.count("\n") == 3


async def test_start_plan_persists_and_starts_the_first_runnable_step():
    """A brand-new decomposed plan (no confirmation yet) starts through the
    exact same loop that advances one already in progress -- §4.2's
    one-plan-one-executor invariant."""
    plan = Plan(
        plan_id="plan_new",
        correlation_id="cor_new",
        user_id=USR,
        organization_id=ORG,
        origin=PlanOrigin.DECOMPOSITION,
        source_message_id="msg_new",
        steps=(
            PlanStep(
                step_id="s1",
                workflow_key=WorkflowKey.PROJECT_CREATE,
                event_type=CanonicalEventType.PROJECT_CREATE_REQUESTED,
                fields={"name": "Starship"},
            ),
            PlanStep(
                step_id="s2",
                workflow_key=WorkflowKey.SITE_CREATE,
                event_type=CanonicalEventType.SITE_CREATE_REQUESTED,
                fields={"name": "Site A"},
                scope={"project_id": StepRef("s1", "project_id")},
            ),
        ),
    )
    store = _plan_store()
    runtime = _FakeWorkflowRuntime([_started(WorkflowKey.PROJECT_CREATE, "Create Starship?", "wf_1")])

    from runtime.plan_executor import start_plan

    reply = await start_plan(plan, plan_store=store, workflow_runtime=runtime)

    assert reply is not None
    assert "(1 of 2)" in reply.text
    assert "Create Starship?" in reply.text
    stored = await store.get_plan(user_id=USR)
    assert stored is not None
    assert stored.step("s1").status is StepStatus.RUNNING
    assert stored.step("s1").workflow_instance_id == "wf_1"


async def test_start_plan_with_no_runnable_step_reports_the_summary_immediately():
    """Every step already terminal (an edge case, but the loop must not
    crash on it) -- start_plan should report and release rather than hang."""
    plan = Plan(
        plan_id="plan_done",
        correlation_id="cor_done",
        user_id=USR,
        organization_id=ORG,
        origin=PlanOrigin.DECOMPOSITION,
        steps=(
            PlanStep(
                step_id="s1",
                workflow_key=WorkflowKey.PROJECT_CREATE,
                event_type=CanonicalEventType.PROJECT_CREATE_REQUESTED,
                fields={},
                status=StepStatus.DONE,
            ),
        ),
    )
    store = _plan_store()
    runtime = _FakeWorkflowRuntime([])

    from runtime.plan_executor import start_plan

    reply = await start_plan(plan, plan_store=store, workflow_runtime=runtime)

    assert reply is not None
    assert "Here's what I did" in reply.text
    assert await store.get_plan(user_id=USR) is None
