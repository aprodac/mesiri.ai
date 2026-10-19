"""Labour attendance must not save without an explicit YES.

Written after a report from the deployed build that an attendance "got
recorded but I didn't get a preview". That is the one failure mode principle
P2 exists to prevent — nothing is persisted before an explicit confirmation —
so it needs a test that drives the *real* graph and the *real* runtime rather
than fakes standing in for both.

Uses the real compiled LangGraph via WorkflowRegistry, so it is skipped when
langgraph isn't installed (optional `workflow` group), same as the sibling
graph tests. The execution side is the real Phase 5 Handler/Dispatcher
(application/labour/), backed by FakeLabourExecutionRepository rather than a
live database -- no stub anywhere in this file.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytest.importorskip("langgraph")

from interactions import InteractionHandler  # noqa: E402
from mesiri.application.labour.dispatcher import LabourExecutionDispatcher  # noqa: E402
from mesiri.application.labour.fakes import (  # noqa: E402
    FakeDatabase,
    FakeLabourExecutionRepository,
)
from mesiri.application.labour.handlers import ExecuteConfirmedLabourAttendanceHandler  # noqa: E402
from mesiri_contracts.application.results.execution_result import ExecutionStatus  # noqa: E402
from mesiri_contracts.assistant.canonical_event import (  # noqa: E402
    CanonicalEventType,
    IntentCompleteness,
)
from mesiri_contracts.assistant.enums import InputModality  # noqa: E402
from mesiri_contracts.assistant.normalized_message import (  # noqa: E402
    NormalizedMessage,
    SenderInfo,
)
from mesiri_contracts.assistant.planner_decision import (  # noqa: E402
    PlannerDecisionType,
    PlannerPriority,
    WorkflowKey,
)
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2  # noqa: E402
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2  # noqa: E402
from mesiri_contracts.context.enums import WorkflowPhase  # noqa: E402
from workflows import WorkflowRunStatus, WorkflowRuntime  # noqa: E402
from workflows.fakes import FakeWorkflowInstanceRepository  # noqa: E402
from workflows.registry import WorkflowRegistry  # noqa: E402

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "44444444-4444-4444-8444-444444444444"

LINES = [
    {"worker_name": "Ravi", "trade": "mason", "headcount": 1},
    {"worker_name": None, "trade": "helper", "headcount": 12},
]


class _CountingDispatcher:
    """Wraps the real Phase 5 dispatcher (fakes-backed, no live DB) so the
    test can assert nothing was executed until confirmation."""

    def __init__(self) -> None:
        self.calls = 0
        handler = ExecuteConfirmedLabourAttendanceHandler(
            db=FakeDatabase(), repo=FakeLabourExecutionRepository()
        )
        self._inner = LabourExecutionDispatcher(handler)

    async def dispatch(self, confirmed):
        self.calls += 1
        return await self._inner.dispatch(confirmed)


def _decision() -> PlannerDecisionV2:
    return PlannerDecisionV2(
        correlation_id="cor_1",
        source_message_id="msg_1",
        decision_type=PlannerDecisionType.START_WORKFLOW,
        workflow_key=WorkflowKey.LABOUR_ATTENDANCE,
        reason=CanonicalEventType.LABOUR_ATTENDANCE_REQUESTED,
        priority=PlannerPriority.NORMAL,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        site_id=SITE,
    )


def _event(fields: dict | None = None) -> CanonicalEventV2:
    return CanonicalEventV2(
        event_id="evt_1",
        correlation_id="cor_1",
        source_message_id="msg_1",
        event_type=CanonicalEventType.LABOUR_ATTENDANCE_REQUESTED,
        completeness=IntentCompleteness.ACTIONABLE,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        site_id=SITE,
        fields=fields if fields is not None else {"lines": LINES},
    )


def _message(text: str) -> NormalizedMessage:
    return NormalizedMessage(
        message_id="wamid.1",
        correlation_id="cor_1",
        sender=SenderInfo(wa_id="wa_engineer", profile_name="Engineer"),
        timestamp=datetime(2026, 7, 26, 10, 0, tzinfo=UTC),
        modality=InputModality.TEXT,
        text=text,
    )


def _runtime() -> tuple[WorkflowRuntime, FakeWorkflowInstanceRepository]:
    repo = FakeWorkflowInstanceRepository()
    return WorkflowRuntime(registry=WorkflowRegistry(), repo=repo), repo


async def test_starting_an_attendance_shows_a_preview_and_saves_nothing():
    """The reported failure, pinned: starting the workflow must produce the
    preview and must NOT execute anything."""
    runtime, repo = _runtime()
    dispatcher = _CountingDispatcher()

    result = await runtime.start(_decision(), _event())

    assert result.status is WorkflowRunStatus.STARTED
    assert result.draft_action is not None
    assert dispatcher.calls == 0

    prompt = result.pending_prompt
    assert prompt is not None
    assert "Confirm this record?" in prompt
    assert "Labour Attendance" in prompt
    assert "Ravi" in prompt
    assert "12 × Helper" in prompt
    assert "13 workers" in prompt
    assert "Reply YES to confirm or NO to cancel." in prompt

    assert len(repo.saved) == 1
    assert repo.saved[0].phase is WorkflowPhase.AWAITING_CONFIRMATION


async def test_nothing_executes_until_the_user_says_yes():
    """P2 in one assertion: the record only exists after an explicit YES."""
    runtime, _ = _runtime()
    dispatcher = _CountingDispatcher()
    handler = InteractionHandler(runtime, dispatcher=dispatcher)

    await runtime.start(_decision(), _event())
    assert dispatcher.calls == 0

    handled = await handler.handle_fast_path(USR, _message("yes"))

    assert handled is not None
    assert dispatcher.calls == 1
    assert handled.execution_result is not None
    assert handled.execution_result.status is ExecutionStatus.SUCCEEDED


async def test_saying_no_records_nothing():
    runtime, _ = _runtime()
    dispatcher = _CountingDispatcher()
    handler = InteractionHandler(runtime, dispatcher=dispatcher)

    await runtime.start(_decision(), _event())
    handled = await handler.handle_fast_path(USR, _message("no"))

    assert handled is not None
    assert dispatcher.calls == 0
    assert "Nothing was recorded" in handled.reply_text


async def test_an_unrelated_message_does_not_confirm_the_pending_attendance():
    """A tap on a picker row, or any other stray text, must never be read as
    a YES -- the pending attendance stays pending."""
    runtime, _ = _runtime()
    dispatcher = _CountingDispatcher()
    handler = InteractionHandler(runtime, dispatcher=dispatcher)

    await runtime.start(_decision(), _event())
    for stray in ("Attendance", "Site Update", "Ravi"):
        await handler.handle_fast_path(USR, _message(stray))

    assert dispatcher.calls == 0


async def test_a_second_attendance_is_blocked_rather_than_silently_recorded():
    """The single-active gate. A user who reports again before answering the
    first confirmation gets the ORIGINAL prompt re-shown -- which is the most
    likely explanation for "it recorded but I saw no preview for THIS one",
    so it is worth pinning that the second report neither executes nor
    overwrites."""
    runtime, repo = _runtime()
    dispatcher = _CountingDispatcher()

    await runtime.start(_decision(), _event())
    second = await runtime.start(
        _decision(), _event({"lines": [{"worker_name": "Arun", "trade": "painter", "headcount": 1}]})
    )

    assert second.status is WorkflowRunStatus.BLOCKED_PENDING_CONFIRMATION
    assert "Ravi" in (second.pending_prompt or "")
    assert "Arun" not in (second.pending_prompt or "")
    assert dispatcher.calls == 0
    assert len(repo.saved) == 1


async def test_a_blocked_report_says_plainly_that_it_was_not_saved():
    """The reported confusion, fixed at the wording. What follows the block
    message is the EARLIER report's prompt and the new one is discarded, so
    a reply of "yes" confirms something the user didn't just send. The
    message has to say so, or "Recorded" is read as confirming the new
    report."""
    from interactions.response_handler import render_workflow_run_reply

    runtime, _ = _runtime()
    await runtime.start(_decision(), _event())
    second = await runtime.start(
        _decision(), _event({"lines": [{"worker_name": "Arun", "trade": "painter", "headcount": 1}]})
    )

    reply = render_workflow_run_reply(second, pending_prompt=second.pending_prompt)

    assert "haven't saved what you just sent" in reply
    assert "send yours again" in reply
    # And it still shows the earlier report, so the user knows what they are
    # being asked about.
    assert "Ravi" in reply
