"""End-to-end reproduction of the live trace: does plan_executor.advance_plan
actually fire after the *real* WorkflowRuntime (not a fake that just replays
canned results) drives CREATE_USER through start -> pause on missing number
-> slot answer -> confirm?

test_member_create_plan.py's own WorkflowRuntime fake only ever replayed
pre-built WorkflowRunResults, so it could never have caught a bug in how
workflow_instance_id actually flows through start()/provide_input()/resume()
-- this file exists specifically to close that gap, using the real
WorkflowRuntime, a real FakeWorkflowInstanceRepository (the same one
workflows/runtime.py's own test suite trusts), and the real compiled
create_user/add_project_member graphs.

Originally exercised resume.py's hand-written advance_member_plan_after_
user_created, hardcoded to this one chain's two step ids. That function is
retired -- message_journey.py now calls plan_executor.advance_plan
generically for every confirmation (docs/execution/
COMPOSITE_REQUEST_PLAN_LAYER.md §4.2's one-plan-one-executor invariant).
This file still proves the exact same real-graph, real-instance-id sequence
survives being driven by the generic executor instead -- the strongest
available evidence for the swap, since it is the only test in the repo that
exercises this chain against actual compiled LangGraph graphs rather than a
canned-result fake.

Skipped automatically when ``langgraph`` isn't installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph")

from typing import Any  # noqa: E402

from memory.recent_turns import ConversationTurn, RecentTurnsStore  # noqa: E402
from mesiri_contracts.application.results.execution_result import (  # noqa: E402
    ExecutionResult,
    ExecutionStatus,
)
from mesiri_contracts.assistant.canonical_event import CanonicalEventType  # noqa: E402
from mesiri_contracts.assistant.canonical_event import (  # noqa: E402
    IntentCompleteness as _IntentCompleteness,
)
from mesiri_contracts.assistant.planner_decision import (  # noqa: E402
    WorkflowKey,
)
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2  # noqa: E402
from planning.plan_store import PlanStore  # noqa: E402
from runtime.member_create_plan import start_member_create_plan  # noqa: E402
from runtime.plan_executor import advance_plan  # noqa: E402
from workflows.add_project_member.graph import build_add_project_member_graph  # noqa: E402
from workflows.create_user.graph import build_create_user_graph  # noqa: E402
from workflows.fakes import FakeWorkflowInstanceRepository, FakeWorkflowRegistry  # noqa: E402
from workflows.runtime import ResumeAction, WorkflowRuntime  # noqa: E402

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


class _Actor:
    def __init__(self):
        self.user_id = USR
        self.organization_id = ORG
        self.role = "PROJECT_MANAGER"


def _original_add_member_event() -> CanonicalEventV2:
    return CanonicalEventV2(
        event_id="evt_orig",
        correlation_id="cor_orig",
        source_message_id="msg_orig",
        event_type=CanonicalEventType.ADD_PROJECT_MEMBER_REQUESTED,
        completeness=_IntentCompleteness.ACTIONABLE,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        fields={
            "member_name": "Hysam",
            "role": "PROJECT_MANAGER",
            "created_by_role": "PROJECT_MANAGER",
        },
    )


def _mock_handled(result, execution=None):
    from types import SimpleNamespace

    return SimpleNamespace(result=result, execution_result=execution, reply_text="", project_id=None, site_id=None)


async def test_the_exact_live_sequence_reaches_the_confirmation_prompt():
    """Reproduces: create Hysam -> Yes, create -> (asks for number) ->
    +91 97781 90485 -> (asks to confirm) -> Yes -> should offer to add Hysam
    to the project, not stop at "user created"."""
    repo = FakeWorkflowInstanceRepository()
    runtime = WorkflowRuntime(
        registry=FakeWorkflowRegistry(
            {
                WorkflowKey.CREATE_USER: build_create_user_graph(),
                WorkflowKey.ADD_PROJECT_MEMBER: build_add_project_member_graph(),
            }
        ),
        repo=repo,
    )
    plan_store = PlanStore(_FakeRedis())
    actor = _Actor()

    # Step 1: "Yes, create" -- starts CREATE_USER with just a name.
    reply1 = await start_member_create_plan(
        name_hint="Hysam",
        original_event=_original_add_member_event(),
        actor=actor,
        plan_store=plan_store,
        workflow_runtime=runtime,
    )
    assert reply1 is not None and "number" in reply1.text.lower(), reply1
    # A plain question (AWAITING_INPUT, no slot_options) -- no buttons yet,
    # unlike the confirmation reply1 becomes once the number is known.
    assert reply1.buttons is None

    # Step 2: the phone number reply. handle_slot_answer's own logic, done
    # directly here to isolate WorkflowRuntime/PlanStore from the interaction
    # layer around it.
    loaded = await runtime.get_awaiting_input(USR)
    assert loaded is not None, "no COLLECTING_FIELDS instance was persisted for the number question"
    run2 = await runtime.provide_input(loaded, "+91 97781 90485")
    assert run2.status.value == "started", run2.status
    assert run2.workflow_instance_id == loaded.state.workflow_instance_id, (
        "provide_input returned a DIFFERENT workflow_instance_id than the one "
        "it was resuming -- this alone would break the plan's instance match"
    )

    # Step 3: "Yes" -- confirms the CREATE_USER draft.
    loaded2 = await runtime.get_awaiting_confirmation(USR)
    assert loaded2 is not None, "no AWAITING_CONFIRMATION instance found after provide_input"
    assert loaded2.state.workflow_instance_id == run2.workflow_instance_id, (
        "get_awaiting_confirmation found a DIFFERENT instance than provide_input just produced"
    )
    resume_result = await runtime.resume(loaded2, ResumeAction.CONFIRM)
    assert resume_result.status.value == "confirmed", resume_result.status
    assert resume_result.workflow_instance_id == loaded.state.workflow_instance_id, (
        "the CONFIRMED result's workflow_instance_id does not match the "
        "original instance start_member_create_plan recorded on the plan -- "
        "THIS is what would make _is_our_instance() reject a legitimate match"
    )

    # Step 4: simulate the execution succeeding (a real Handler would build
    # this from the confirmed draft; hand-built here since no DB is
    # available from this environment).
    execution = ExecutionResult(
        status=ExecutionStatus.SUCCEEDED,
        idempotency_key=resume_result.workflow_instance_id,
        material_row_id="44444444-4444-4444-8444-444444444444",
    )
    handled = _mock_handled(resume_result, execution)

    reply_final = await advance_plan(
        handled, plan_store=plan_store, workflow_runtime=runtime, actor=actor
    )

    assert reply_final is not None, (
        "advance_plan returned None -- the chain stopped at 'user created' "
        "exactly like the live trace showed, instead of continuing to "
        "ADD_PROJECT_MEMBER"
    )
    assert "confirm" in reply_final.text.lower()
    # The live bug this session's user actually hit: a plain-text "Reply
    # YES to confirm or NO to cancel" instead of tappable buttons, because
    # this used to return a bare pending_prompt string.
    assert reply_final.buttons is not None
    assert {b.title for b in reply_final.buttons} == {"Yes", "No"}

    # Step 5: the plan does NOT clear here -- unlike the old hardcoded
    # advance, the generic executor keeps it alive through the final step
    # (§4.2). "Yes" to ADD_PROJECT_MEMBER should close it out with a summary.
    plan_mid = await plan_store.get_plan(user_id=USR)
    assert plan_mid is not None, "the generic executor must keep the plan alive through the final step"
    assert plan_mid.step("add_member").status.value == "running"

    loaded3 = await runtime.get_awaiting_confirmation(USR)
    assert loaded3 is not None, "no AWAITING_CONFIRMATION instance found for ADD_PROJECT_MEMBER"
    resume_result2 = await runtime.resume(loaded3, ResumeAction.CONFIRM)
    assert resume_result2.status.value == "confirmed", resume_result2.status

    execution2 = ExecutionResult(
        status=ExecutionStatus.SUCCEEDED,
        idempotency_key=resume_result2.workflow_instance_id,
        material_row_id="66666666-6666-4666-8666-666666666666",
    )
    handled2 = _mock_handled(resume_result2, execution2)

    reply_closing = await advance_plan(
        handled2, plan_store=plan_store, workflow_runtime=runtime, actor=actor
    )

    assert reply_closing is not None
    assert "here's what i did" in reply_closing.text.lower()
    assert await plan_store.get_plan(user_id=USR) is None, (
        "the plan must be released once every step has reached a terminal status"
    )


# ---------------------------------------------------------------------------
# start_member_create_plan's phone-number recall (memory.recent_turns) --
# the fix for "I already gave you that number" when it was stated in an
# earlier, differently-classified message rather than in reply to CREATE_
# USER's own question.
# ---------------------------------------------------------------------------


async def test_a_number_recalled_from_recent_turns_skips_straight_to_confirmation():
    repo = FakeWorkflowInstanceRepository()
    runtime = WorkflowRuntime(
        registry=FakeWorkflowRegistry({WorkflowKey.CREATE_USER: build_create_user_graph()}),
        repo=repo,
    )
    plan_store = PlanStore(_FakeRedis())
    recent_turns = RecentTurnsStore(_FakeRedis())
    await recent_turns.append(
        user_id=USR,
        turn=ConversationTurn(
            user_text="+91 97781 90485 create Hysam in project hospital",
            assistant_reply="\"Hysam\" isn't an active user yet.",
            correlation_id="cor_orig",
        ),
    )

    reply = await start_member_create_plan(
        name_hint="Hysam",
        original_event=_original_add_member_event(),
        actor=_Actor(),
        plan_store=plan_store,
        workflow_runtime=runtime,
        recent_turns=recent_turns,
    )

    assert reply is not None
    assert "confirm" in reply.text.lower(), (
        f"expected the recalled number to skip straight to a confirmation prompt, got: {reply!r}"
    )
    assert "919778190485" in reply.text
    # This exact case (a recalled number reaching STARTED on the very first
    # call) is what exposed the missing-buttons bug live -- pin it here too.
    assert reply.buttons is not None
    assert {b.title for b in reply.buttons} == {"Yes", "No"}


async def test_no_recent_turns_still_asks_for_the_number_as_before():
    """Purely additive -- nothing mentioned means CREATE_USER's own
    build_draft asks, exactly as it did before recall existed."""
    repo = FakeWorkflowInstanceRepository()
    runtime = WorkflowRuntime(
        registry=FakeWorkflowRegistry({WorkflowKey.CREATE_USER: build_create_user_graph()}),
        repo=repo,
    )
    plan_store = PlanStore(_FakeRedis())
    recent_turns = RecentTurnsStore(_FakeRedis())  # nothing appended

    reply = await start_member_create_plan(
        name_hint="Hysam",
        original_event=_original_add_member_event(),
        actor=_Actor(),
        plan_store=plan_store,
        workflow_runtime=runtime,
        recent_turns=recent_turns,
    )

    assert reply is not None and "number" in reply.text.lower()


async def test_recent_turns_omitted_entirely_still_asks_for_the_number():
    """recent_turns is optional -- an older/unwired caller must behave
    exactly as it did before this parameter existed."""
    repo = FakeWorkflowInstanceRepository()
    runtime = WorkflowRuntime(
        registry=FakeWorkflowRegistry({WorkflowKey.CREATE_USER: build_create_user_graph()}),
        repo=repo,
    )
    plan_store = PlanStore(_FakeRedis())

    reply = await start_member_create_plan(
        name_hint="Hysam",
        original_event=_original_add_member_event(),
        actor=_Actor(),
        plan_store=plan_store,
        workflow_runtime=runtime,
    )

    assert reply is not None and "number" in reply.text.lower()


async def test_an_unrelated_recent_number_like_a_headcount_does_not_get_used():
    repo = FakeWorkflowInstanceRepository()
    runtime = WorkflowRuntime(
        registry=FakeWorkflowRegistry({WorkflowKey.CREATE_USER: build_create_user_graph()}),
        repo=repo,
    )
    plan_store = PlanStore(_FakeRedis())
    recent_turns = RecentTurnsStore(_FakeRedis())
    await recent_turns.append(
        user_id=USR,
        turn=ConversationTurn(
            user_text="12 workers on site today", assistant_reply="Recorded.", correlation_id="c1"
        ),
    )

    reply = await start_member_create_plan(
        name_hint="Hysam",
        original_event=_original_add_member_event(),
        actor=_Actor(),
        plan_store=plan_store,
        workflow_runtime=runtime,
        recent_turns=recent_turns,
    )

    assert reply is not None and "number" in reply.text.lower()
