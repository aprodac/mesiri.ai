"""_maybe_trigger_worker_promotion (runtime/inbound_journey.py) -- unit tests.

Covers the extraction/filtering logic that decides which confirmed attendance
lines are offered for promotion: named + never matched to a registered
worker. Headcount-only lines and already-matched lines must never reach the
offer, per the plan's rule that promotion applies only to named workers who
are new.

Uses a fake WorkflowRuntime.start() so these stay fast, isolated unit tests;
the real LangGraph executor-thread boundary is covered separately in
tests/integration/test_worker_promotion_graph.py.
"""

from __future__ import annotations

import uuid

from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from runtime.inbound_journey import _maybe_trigger_worker_promotion
from workflows.runtime import WorkflowResumeResult, WorkflowResumeStatus, WorkflowRunResult

ORG = str(uuid.uuid4())
USR = str(uuid.uuid4())
PRJ = str(uuid.uuid4())
RAVI_ID = str(uuid.uuid4())


def _confirmed(lines: list[dict]) -> ConfirmedActionV2:
    draft = DraftActionV2(
        draft_id="draft1",
        correlation_id="cor1",
        workflow_instance_id="wf1",
        action_type=DraftActionType.RECORD_LABOUR_ATTENDANCE,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        fields={"lines": lines},
    )
    return ConfirmedActionV2(
        confirmed_action_id="conf1",
        workflow_instance_id="wf1",
        correlation_id="cor1",
        draft_action=draft,
        confirmed_by_user_id=USR,
    )


def _handled(lines: list[dict], *, succeeded: bool = True):
    from interactions.handler import InteractionHandled

    result = WorkflowResumeResult(
        status=WorkflowResumeStatus.CONFIRMED,
        workflow_instance_id="wf1",
        correlation_id="cor1",
        confirmed_action=_confirmed(lines),
    )
    execution_result = ExecutionResult(
        status=ExecutionStatus.SUCCEEDED if succeeded else ExecutionStatus.FAILED,
        idempotency_key="idem1",
        material_row_id="row1" if succeeded else None,
    )
    return InteractionHandled(result=result, reply_text="ok", execution_result=execution_result)


class _FakeActor:
    def __init__(self) -> None:
        self.organization_id = ORG
        self.user_id = USR


class _FakeWorkforceQuery:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.candidates: list[dict] = []

    async def list_worker_candidates(self, **kwargs):
        return self.candidates

    async def create_worker(self, **kwargs):
        self.created.append(kwargs)
        return "new-id"


class _FakeWorkflowRuntime:
    """Records the decision/event it was asked to start; never runs a graph."""

    def __init__(self, pending_prompt: str | None = "offer sent") -> None:
        self.started_with: tuple | None = None
        self._pending_prompt = pending_prompt

    async def abandon_optional_question(self, user_id: str) -> bool:
        return False

    async def start(self, decision, event):
        self.started_with = (decision, event)
        return WorkflowRunResult.awaiting_input(
            workflow_key=WorkflowKey.WORKER_PROMOTION,
            correlation_id=event.correlation_id,
            workflow_instance_id="wf_promo",
            pending_prompt=self._pending_prompt,
        )


async def _send_text_recorder():
    sent: list[tuple[str, str]] = []

    async def send_text(wa_id: str, text: str):
        sent.append((wa_id, text))

    return sent, send_text


async def test_only_named_unmatched_lines_are_offered():
    """Headcount-only lines ("12 helpers") have nobody to promote, and a line
    already matched to a registered worker is by definition not new."""
    handled = _handled(
        [
            {"worker_name": "Ravi", "trade": "mason", "worker_id": None, "daily_wage": "800"},
            {"worker_name": None, "trade": "helper", "headcount": 12, "worker_id": None},
            {"worker_name": "Suresh", "trade": "painter", "worker_id": RAVI_ID},
        ]
    )
    runtime = _FakeWorkflowRuntime()
    workforce_query = _FakeWorkforceQuery()
    sent, send_text = await _send_text_recorder()

    await _maybe_trigger_worker_promotion(
        handled, runtime, workforce_query, _FakeActor(), "wa123", send_text
    )

    assert runtime.started_with is not None
    _decision, event = runtime.started_with
    promotable = event.fields["promotable_workers"]
    assert [w["name"] for w in promotable] == ["Ravi"]


async def test_the_register_is_seeded_for_the_duplicate_check():
    """The node must never query a repository itself, so the register it
    screens against has to arrive in the event fields."""
    handled = _handled([{"worker_name": "Ravi", "trade": "mason", "worker_id": None}])
    runtime = _FakeWorkflowRuntime()
    workforce_query = _FakeWorkforceQuery()
    workforce_query.candidates = [
        {"worker_id": "w1", "name": "Ravi Kumar", "trade": "mason", "contractor": None}
    ]
    _sent, send_text = await _send_text_recorder()

    await _maybe_trigger_worker_promotion(
        handled, runtime, workforce_query, _FakeActor(), "wa123", send_text
    )

    _decision, event = runtime.started_with
    assert event.fields["_register"] == workforce_query.candidates


async def test_a_failing_register_read_never_blocks_the_promotion_offer():
    """Attendance is already saved. If the register read fails, offering
    promotion without the duplicate screen still beats offering nothing."""

    class _BrokenQuery(_FakeWorkforceQuery):
        async def list_worker_candidates(self, **kwargs):
            raise RuntimeError("db down")

    handled = _handled([{"worker_name": "Ravi", "trade": "mason", "worker_id": None}])
    runtime = _FakeWorkflowRuntime()
    _sent, send_text = await _send_text_recorder()

    await _maybe_trigger_worker_promotion(
        handled, runtime, _BrokenQuery(), _FakeActor(), "wa123", send_text
    )

    _decision, event = runtime.started_with
    assert event.fields["_register"] == []


async def test_no_named_new_workers_never_starts_the_promotion_workflow():
    handled = _handled(
        [{"worker_name": None, "trade": "helper", "headcount": 12, "worker_id": None}]
    )
    runtime = _FakeWorkflowRuntime()
    _sent, send_text = await _send_text_recorder()

    await _maybe_trigger_worker_promotion(
        handled, runtime, _FakeWorkforceQuery(), _FakeActor(), "wa123", send_text
    )

    assert runtime.started_with is None


async def test_failed_execution_never_triggers_promotion():
    handled = _handled(
        [{"worker_name": "Ravi", "trade": "mason", "worker_id": None}], succeeded=False
    )
    runtime = _FakeWorkflowRuntime()
    _sent, send_text = await _send_text_recorder()

    await _maybe_trigger_worker_promotion(
        handled, runtime, _FakeWorkforceQuery(), _FakeActor(), "wa123", send_text
    )

    assert runtime.started_with is None


async def test_the_offer_message_is_sent_to_the_reporting_user():
    handled = _handled([{"worker_name": "Ravi", "trade": "mason", "worker_id": None}])
    runtime = _FakeWorkflowRuntime(pending_prompt="I found these new named workers")
    sent, send_text = await _send_text_recorder()

    await _maybe_trigger_worker_promotion(
        handled, runtime, _FakeWorkforceQuery(), _FakeActor(), "wa123", send_text
    )

    assert sent == [("wa123", "I found these new named workers")]


async def test_promotion_start_failure_never_raises():
    """Promotion is a courtesy follow-up -- attendance is already confirmed
    and saved by the time this runs, so a failure here must never surface as
    an error to the user or block anything upstream."""

    class _BrokenRuntime:
        async def abandon_optional_question(self, user_id: str) -> bool:
            return False

        async def start(self, decision, event):
            raise RuntimeError("boom")

    handled = _handled([{"worker_name": "Ravi", "trade": "mason", "worker_id": None}])
    _sent, send_text = await _send_text_recorder()

    await _maybe_trigger_worker_promotion(
        handled, _BrokenRuntime(), _FakeWorkforceQuery(), _FakeActor(), "wa123", send_text
    )


async def test_an_earlier_offer_is_replaced_not_stacked():
    """The list a supervisor sees must describe the report they just filed.

    Two offers open at once means get_awaiting_input() answers whichever is
    newest while the older list lingers -- which is how a newly named worker
    appeared to "never show up" in the promotion list.
    """
    abandoned: list[str] = []

    class _RuntimeRecordingAbandon(_FakeWorkflowRuntime):
        async def abandon_optional_question(self, user_id: str) -> bool:
            abandoned.append(user_id)
            return True

    handled = _handled([{"worker_name": "Ravi", "trade": "mason", "worker_id": None}])
    runtime = _RuntimeRecordingAbandon()
    _sent, send_text = await _send_text_recorder()

    await _maybe_trigger_worker_promotion(
        handled, runtime, _FakeWorkforceQuery(), _FakeActor(), "wa123", send_text
    )

    assert abandoned == [USR], "the previous offer must be closed before a new one opens"
    assert runtime.started_with is not None


async def test_the_offer_lists_exactly_the_new_named_workers_of_this_report():
    """Built from this report's own lines every time -- never carried over."""
    handled = _handled(
        [
            {"worker_name": "Ravi", "trade": "mason", "worker_id": None},
            {"worker_name": "Niyas", "trade": "helper", "worker_id": None},
            {"worker_name": "Ajith", "trade": "painter", "worker_id": None},
            {"worker_name": "Ilan", "trade": "carpenter", "worker_id": RAVI_ID},
            {"worker_name": None, "trade": "helper", "headcount": 12, "worker_id": None},
        ]
    )
    runtime = _FakeWorkflowRuntime()
    _sent, send_text = await _send_text_recorder()

    await _maybe_trigger_worker_promotion(
        handled, runtime, _FakeWorkforceQuery(), _FakeActor(), "wa123", send_text
    )

    _decision, event = runtime.started_with
    assert [w["name"] for w in event.fields["promotable_workers"]] == [
        "Ravi",
        "Niyas",
        "Ajith",
    ]


async def test_the_offer_goes_out_with_its_buttons_when_the_caller_takes_specs():
    """Request [51]: the offer is handed over as a ReplySpec with its three
    buttons (the journey folds it into the one reply), not as bare text."""
    from workflows.slots import SlotCandidate

    class _Runtime(_FakeWorkflowRuntime):
        async def start(self, decision, event):
            return WorkflowRunResult.awaiting_input(
                workflow_key=WorkflowKey.WORKER_PROMOTION,
                correlation_id=event.correlation_id,
                workflow_instance_id="wf_promo",
                pending_prompt="Quick check 👇",
                slot_options=(
                    SlotCandidate("promo_all", "Add"),
                    SlotCandidate("promo_none", "Not now"),
                ),
            )

    handled = _handled([{"worker_name": "Ravi", "trade": "mason", "worker_id": None}])
    sent, send_text = await _send_text_recorder()
    specs: list = []

    async def send_spec(spec, wa_id):
        specs.append(spec)

    offered = await _maybe_trigger_worker_promotion(
        handled,
        _Runtime(),
        _FakeWorkforceQuery(),
        _FakeActor(),
        "wa123",
        send_text,
        send_spec_fn=send_spec,
    )

    assert offered is True
    assert sent == []
    assert [b.id for b in specs[0].buttons] == ["promo_all", "promo_none"]
