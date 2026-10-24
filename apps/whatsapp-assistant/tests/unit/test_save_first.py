"""WA-01: capture updates are saved straight away as drafts.

Two halves:
- InteractionHandler.save_now: runs the same path a "YES" takes, then marks
  the saved item as a draft and adds the "saved as a draft" line -- only for
  the capture flows, only when the company saves first.
- runtime/save_first.SaveFirstService: which flows/companies save first, the
  draft + extraction it records, and "UNDO" of the sender's latest draft.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest

from interactions.handler import InteractionHandler
from interactions.ports import ExecutionDispatcher
from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from mesiri_contracts.assistant.v2.workflow_state import WorkflowStateV2
from mesiri_contracts.context.enums import WorkflowPhase
from runtime import save_first as save_first_module
from runtime.save_first import DRAFT_NOTE, SAVE_FIRST_KEYS, SaveFirstService, canonical_uuid
from workflows import WorkflowRegistry, WorkflowRuntime
from workflows.fakes import FakeWorkflowInstanceRepository

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
REPORT = "33333333-3333-4333-8333-333333333333"
WF = "11111111-1111-4111-8111-1111111111aa"


# ---------------------------------------------------------------------------
# InteractionHandler.save_now
# ---------------------------------------------------------------------------


class _Dispatcher(ExecutionDispatcher):
    def __init__(self, status=ExecutionStatus.SUCCEEDED) -> None:
        self.status = status
        self.dispatched: list[ConfirmedActionV2] = []

    async def dispatch(self, confirmed: ConfirmedActionV2) -> ExecutionResult:
        self.dispatched.append(confirmed)
        return ExecutionResult(
            status=self.status,
            idempotency_key="idem_1",
            material_row_id=REPORT if self.status is ExecutionStatus.SUCCEEDED else None,
            rejection_reasons=[] if self.status is ExecutionStatus.SUCCEEDED else ["no"],
        )


class _FakeSaveFirst:
    def __init__(self, *, applies: bool = True) -> None:
        self._applies = applies
        self.drafts: list[dict] = []

    async def applies(self, *, workflow_key, organization_id) -> bool:
        return self._applies and workflow_key in SAVE_FIRST_KEYS

    async def record_draft(self, **kwargs) -> bool:
        self.drafts.append(kwargs)
        return True

    async def note_for(self, **kwargs) -> str:
        # An open day: the usual draft note (BE-13's late-entry notes are
        # covered against a real database).
        return DRAFT_NOTE

    async def undo_latest_draft(self, **kwargs):
        return None


class _NoopGraph:
    async def ainvoke(self, state: dict) -> dict:
        return {}


def _state(key: WorkflowKey, action: DraftActionType) -> WorkflowStateV2:
    draft = DraftActionV2(
        draft_id="d1",
        correlation_id="c1",
        workflow_instance_id=WF,
        action_type=action,
        organization_id=ORG,
        user_id=USR,
        fields={"lines": [{"worker_name": "Ramesh", "trade": "mason"}]},
    )
    return WorkflowStateV2(
        workflow_instance_id=WF,
        workflow_key=key,
        correlation_id="c1",
        organization_id=ORG,
        user_id=USR,
        phase=WorkflowPhase.AWAITING_CONFIRMATION,
        draft_action=draft,
        pending_prompt="Confirm?",
    )


def _handler(state, *, dispatcher=None, save_first=None):
    repo = FakeWorkflowInstanceRepository()
    if state is not None:
        repo.seed(state, version=0)
    registry = WorkflowRegistry()
    registry._compiled[state.workflow_key if state else WorkflowKey.LABOUR_ATTENDANCE] = _NoopGraph()
    dispatcher = dispatcher or _Dispatcher()
    handler = InteractionHandler(
        WorkflowRuntime(registry=registry, repo=repo),
        dispatcher=dispatcher,
        save_first=save_first if save_first is not None else _FakeSaveFirst(),
    )
    return handler, dispatcher


async def test_a_waiting_attendance_is_saved_marked_draft_and_says_so():
    save_first = _FakeSaveFirst()
    handler, dispatcher = _handler(
        _state(WorkflowKey.LABOUR_ATTENDANCE, DraftActionType.RECORD_LABOUR_ATTENDANCE),
        save_first=save_first,
    )

    handled = await handler.save_now(USR)

    assert handled is not None
    assert len(dispatcher.dispatched) == 1  # the same dispatch a "YES" runs
    assert handled.reply_text.endswith(DRAFT_NOTE)
    [draft] = save_first.drafts
    assert draft["fact_id"] == REPORT
    assert draft["action_type"] is DraftActionType.RECORD_LABOUR_ATTENDANCE
    assert draft["organization_id"] == ORG
    assert draft["correlation_id"] == "c1"


async def test_usage_beyond_stock_is_saved_and_the_reply_says_it_is_flagged():
    """WA-03: not asked during the day; the saved reply carries the line."""
    state = _state(WorkflowKey.MATERIAL_USAGE, DraftActionType.RECORD_MATERIAL_USAGE)
    draft = state.draft_action.model_copy(
        update={"fields": {"material_name": "Cement", "quantity": 70, "unit": "bags"}}
    )
    state = state.model_copy(
        update={"draft_action": draft, "collected_fields": {"available_stock": 50}}
    )
    handler, dispatcher = _handler(state)

    handled = await handler.save_now(USR)

    assert handled is not None and len(dispatcher.dispatched) == 1
    assert handled.reply_text.endswith(
        "That's more than the 50 bags in stock, so it's flagged on tonight's report.\n"
        + DRAFT_NOTE
    )


async def test_nothing_waiting_means_nothing_saved():
    handler, dispatcher = _handler(None)
    assert await handler.save_now(USR) is None
    assert dispatcher.dispatched == []


async def test_a_non_capture_draft_still_asks():
    handler, dispatcher = _handler(_state(WorkflowKey.CREATE_USER, DraftActionType.CREATE_USER))
    assert await handler.save_now(USR) is None
    assert dispatcher.dispatched == []


async def test_a_company_switched_to_confirm_first_still_asks():
    handler, dispatcher = _handler(
        _state(WorkflowKey.MATERIAL_RECEIPT, DraftActionType.RECORD_MATERIAL_RECEIPT),
        save_first=_FakeSaveFirst(applies=False),
    )
    assert await handler.save_now(USR) is None
    assert dispatcher.dispatched == []


async def test_a_refused_save_is_not_called_a_draft():
    save_first = _FakeSaveFirst()
    handler, _ = _handler(
        _state(WorkflowKey.SITE_ISSUE_REPORT, DraftActionType.RECORD_SITE_ISSUE),
        dispatcher=_Dispatcher(status=ExecutionStatus.REJECTED),
        save_first=save_first,
    )

    handled = await handler.save_now(USR)

    assert handled is not None
    assert DRAFT_NOTE not in handled.reply_text
    assert save_first.drafts == []


async def test_without_save_first_wired_nothing_changes():
    repo = FakeWorkflowInstanceRepository()
    repo.seed(_state(WorkflowKey.LABOUR_ATTENDANCE, DraftActionType.RECORD_LABOUR_ATTENDANCE), version=0)
    registry = WorkflowRegistry()
    handler = InteractionHandler(WorkflowRuntime(registry=registry, repo=repo), dispatcher=_Dispatcher())

    assert await handler.saves_first(workflow_key=WorkflowKey.LABOUR_ATTENDANCE, organization_id=ORG) is False
    assert await handler.save_now(USR) is None


# ---------------------------------------------------------------------------
# SaveFirstService
# ---------------------------------------------------------------------------


def test_ids_with_the_whatsapp_prefix_become_database_ids():
    assert canonical_uuid(f"ctx_user_{USR}") == uuid.UUID(USR)
    assert canonical_uuid(USR) == uuid.UUID(USR)
    assert canonical_uuid("not-an-id") is None
    assert canonical_uuid(None) is None


class _Settings:
    def __init__(self, value):
        self.value = value

    async def get(self, *, organization_id, key):
        assert key == "capture_mode"
        return self.value


@pytest.mark.parametrize(
    ("key", "stored", "expected"),
    [
        (WorkflowKey.LABOUR_ATTENDANCE, None, True),
        (WorkflowKey.SITE_UPDATE, "save_first", True),
        (WorkflowKey.MATERIAL_USAGE, "confirm_first", False),
        (WorkflowKey.REVERSE, "save_first", False),
        (WorkflowKey.CREATE_USER, None, False),
    ],
)
async def test_which_flows_and_companies_save_first(key, stored, expected):
    service = SaveFirstService(db=None, org_settings_query=_Settings(stored))
    assert await service.applies(workflow_key=key, organization_id=ORG) is expected


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(self, answers=None):
        self.answers = answers or {}

    async def execute(self, statement, params=None):
        sql = str(statement)
        for fragment, result in self.answers.items():
            if fragment in sql:
                return result
        return _Result()


class _Db:
    def __init__(self, conn):
        self.conn = conn

    @contextlib.asynccontextmanager
    async def transaction(self):
        yield self.conn


@pytest.fixture
def reviews(monkeypatch):
    calls: dict[str, list] = {"extraction": [], "draft": [], "reject": []}

    from mesiri.infrastructure.postgres.repositories import fact_reviews

    class _Repo:
        def __init__(self, conn):
            pass

        async def record_extraction(self, **kwargs):
            calls["extraction"].append(kwargs)
            return uuid.UUID("44444444-4444-4444-8444-444444444444")

        async def mark_draft(self, **kwargs):
            calls["draft"].append(kwargs)

        async def reject(self, **kwargs):
            calls["reject"].append(kwargs)
            if calls.get("refuse"):
                from mesiri.application.dpr.fact_review import FactReviewError

                raise FactReviewError("this day's DPR is already confirmed; revise it instead")

    monkeypatch.setattr(fact_reviews, "PostgresFactReviewRepository", _Repo)
    return calls


async def test_record_draft_keeps_what_the_ai_read_and_marks_the_draft(reviews):
    conn = _Conn(
        {"FROM provider_executions": _Result([{"id": uuid.uuid4(), "provider": "gemini", "model": "gemini-2.5-flash"}])}
    )
    service = SaveFirstService(db=_Db(conn))

    ok = await service.record_draft(
        organization_id=ORG,
        actor_user_id=f"ctx_user_{USR}",
        action_type=DraftActionType.RECORD_LABOUR_ATTENDANCE,
        fact_id=REPORT,
        fields={"lines": []},
        correlation_id="c1",
    )

    assert ok
    [extraction] = reviews["extraction"]
    assert extraction["model"] == "gemini-2.5-flash"
    assert extraction["extracted"]["action_type"] == "record_labour_attendance"
    [draft] = reviews["draft"]
    assert draft["fact_type"] == "labour_report"
    assert draft["fact_id"] == uuid.UUID(REPORT)
    assert draft["actor_user_id"] == uuid.UUID(USR)


async def test_a_progress_update_is_saved_but_not_reviewed_on_its_own(reviews):
    service = SaveFirstService(db=_Db(_Conn()))
    ok = await service.record_draft(
        organization_id=ORG,
        actor_user_id=USR,
        action_type=DraftActionType.ADD_PROGRESS_UPDATE,
        fact_id=REPORT,
        fields={},
        correlation_id=None,
    )
    assert ok is False
    assert reviews["draft"] == []


async def test_a_failed_draft_mark_never_raises(monkeypatch):
    class _BrokenDb:
        @contextlib.asynccontextmanager
        async def transaction(self):
            raise RuntimeError("db down")
            yield  # pragma: no cover

    service = SaveFirstService(db=_BrokenDb())
    ok = await service.record_draft(
        organization_id=ORG,
        actor_user_id=USR,
        action_type=DraftActionType.CREATE_ACTIVITY,
        fact_id=REPORT,
        fields={},
        correlation_id=None,
    )
    assert ok is False


async def test_undo_removes_the_senders_latest_draft(reviews):
    conn = _Conn({"WHERE state = 'draft' AND actor_user_id": _Result([{"fact_type": "material_usage", "fact_id": uuid.UUID(REPORT)}])})
    service = SaveFirstService(db=_Db(conn))

    reply = await service.undo_latest_draft(organization_id=ORG, actor_user_id=f"ctx_user_{USR}")

    assert reply == "Done. I've removed the material used."
    [call] = reviews["reject"]
    assert call["fact_type"] == "material_usage" and call["actor_user_id"] == uuid.UUID(USR)


async def test_undo_with_no_recent_draft_falls_back(reviews):
    service = SaveFirstService(db=_Db(_Conn()))
    assert await service.undo_latest_draft(organization_id=ORG, actor_user_id=USR) is None
    assert reviews["reject"] == []


async def test_undo_says_why_when_the_day_is_already_confirmed(reviews):
    reviews["refuse"] = True
    conn = _Conn({"WHERE state = 'draft' AND actor_user_id": _Result([{"fact_type": "activity", "fact_id": uuid.UUID(REPORT)}])})
    service = SaveFirstService(db=_Db(conn))

    reply = await service.undo_latest_draft(organization_id=ORG, actor_user_id=USR)

    assert reply.startswith("Couldn't undo that:")


def test_the_reply_line_is_the_approved_wording():
    assert save_first_module.DRAFT_NOTE == (
        "Saved as a draft. You'll confirm it with tonight's report. Reply UNDO if it's wrong."
    )


def test_the_journey_saves_first_after_a_slot_answer_and_in_a_plans_next_step():
    """message_journey saves a save-first draft after a slot answer and in a
    plan's next step (the agent's own saves go through its gateway)."""
    import inspect

    import runtime.message_journey as journey

    source = inspect.getsource(journey)
    assert "and await _save_first_now()" in source  # slot answer
    assert "if plan_reply is not None and await _save_first_now():" in source
    assert "interaction_handler.undo_latest_draft(" in source


def test_over_stock_note_only_for_usage_beyond_stock():
    """WA-03: the saved reply's line for usage beyond known stock."""
    from mesiri_contracts.assistant.draft_action import DraftActionType as _T
    from runtime.save_first import over_stock_note

    usage = _T.RECORD_MATERIAL_USAGE
    assert over_stock_note(usage, 70, "bags", 50) == (
        "That's more than the 50 bags in stock, so it's flagged on tonight's report."
    )
    assert over_stock_note(usage, 50, "bags", 50) is None
    assert over_stock_note(usage, 70, "bags", None) is None
    assert over_stock_note(usage, "lots", "bags", 50) is None
    assert over_stock_note(_T.RECORD_MATERIAL_RECEIPT, 70, "bags", 50) is None


def test_snapshot_note_says_which_figures_a_resend_replaced():
    """BE-10: labour is the latest figure per contractor + trade (or per
    named worker) for the day, and the saved reply says what changed."""
    from mesiri_contracts.assistant.draft_action import DraftActionType as _T
    from runtime.save_first import snapshot_note

    labour = _T.RECORD_LABOUR_ATTENDANCE
    day = [
        {"contractor": "Ravi", "trade": "mason", "headcount": 10},
        {"contractor": "Kumar", "trade": "helper", "headcount": 5},
        {"worker_name": "Raju", "trade": "mason", "headcount": 1},
    ]
    sent = [
        {"contractor": "ravi ", "trade": "Mason", "headcount": 12},
        {"contractor": "Kumar", "trade": "painter", "headcount": 2},
        {"worker_name": "raju", "trade": "mason"},
    ]
    assert snapshot_note(labour, sent, day) == (
        "Updated today's figures: ravi Mason 10 → 12. "
        "Already recorded today, counted once: raju."
    )
    # The same figure again is counted once, and said so.
    assert snapshot_note(labour, [day[1]], day) == (
        "Already recorded today, counted once: Kumar Helper 5."
    )
    # A new crew or trade replaces nothing.
    assert snapshot_note(labour, [sent[1]], day) is None
    # A named worker never replaces a headcount, nor the other way round.
    assert snapshot_note(labour, [{"worker_name": "Ravi", "trade": "mason"}], day) is None
    # A register id matches even when the spelling differs.
    by_id = [{"worker_id": "w1", "worker_name": "Raju K", "headcount": 1}]
    assert snapshot_note(labour, [{"worker_id": "w1", "worker_name": "Rajkumar"}], by_id) == (
        "Already recorded today, counted once: Rajkumar."
    )
    # Nothing on record, or not labour: no note.
    assert snapshot_note(labour, sent, None) is None
    assert snapshot_note(_T.RECORD_MATERIAL_USAGE, sent, day) is None


# ---------------------------------------------------------------------------
# Request 104, A1: nothing is written without a card
# ---------------------------------------------------------------------------


def _action_types_without_a_fact():
    return [t for t in DraftActionType if t not in save_first_module.FACT_TYPE_BY_ACTION]


@pytest.mark.parametrize("action", _action_types_without_a_fact(), ids=lambda a: a.value)
async def test_a_draft_the_review_log_does_not_cover_is_never_saved_first(action):
    """The guard: a save-first flow only commits what a Save card can hold. Any
    other kind (a progress update on an open activity: "JCB worked 6 hours")
    stays a Yes / No question, so nothing is written without a pending card."""
    handler, dispatcher = _handler(_state(WorkflowKey.SITE_UPDATE, action))
    assert await handler.save_now(USR) is None
    assert dispatcher.dispatched == []


@pytest.mark.parametrize(
    "action", list(save_first_module.FACT_TYPE_BY_ACTION), ids=lambda a: a.value
)
async def test_a_reviewable_draft_is_still_saved_first(action):
    key = {
        DraftActionType.CREATE_ACTIVITY: WorkflowKey.SITE_UPDATE,
        DraftActionType.RECORD_LABOUR_ATTENDANCE: WorkflowKey.LABOUR_ATTENDANCE,
        DraftActionType.RECORD_MATERIAL_RECEIPT: WorkflowKey.MATERIAL_RECEIPT,
        DraftActionType.RECORD_MATERIAL_USAGE: WorkflowKey.MATERIAL_USAGE,
        DraftActionType.RECORD_SITE_ISSUE: WorkflowKey.SITE_ISSUE_REPORT,
    }[action]
    handler, dispatcher = _handler(_state(key, action))
    assert await handler.save_now(USR) is not None
    assert len(dispatcher.dispatched) == 1
