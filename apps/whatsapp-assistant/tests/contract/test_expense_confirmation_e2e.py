"""End-to-end M8 confirmation flow for Expense capture, mirroring
test_material_confirmation_e2e.py: user replies "yes" -> M7 resumes the
workflow to CONFIRMED -> M8 executes the domain write -> reply reflects the
real outcome. Fakes only (no live DB), matching that file's pattern exactly.

Also covers ActionTypeRoutingDispatcher routing Material vs. Expense confirms
to the correct underlying dispatcher (a scenario Materials' own e2e test
doesn't need, since it predates the router).
"""

from __future__ import annotations

from datetime import UTC, datetime

from interactions import InteractionHandler
from interactions.execution_router import ActionTypeRoutingDispatcher
from mesiri.application.expenses.dispatcher import ExpenseExecutionDispatcher
from mesiri.application.expenses.fakes import (
    FakeDatabase,
    FakeExpenseCategoryResolver,
    FakeExpenseExecutionRepository,
    PersistSuccessRaisesRepository,
    RejectingExpenseCategoryResolver,
)
from mesiri.application.expenses.handlers import RecordExpenseHandler
from mesiri.application.materials.dispatcher import MaterialExecutionDispatcher
from mesiri.application.materials.fakes import FakeDatabase as FakeMaterialDatabase
from mesiri.application.materials.fakes import (
    FakeMaterialExecutionRepository,
    FakeMaterialResolver,
)
from mesiri.application.materials.handlers import ExecuteConfirmedMaterialActionHandler
from mesiri_contracts.application.results.execution_result import ExecutionStatus
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from mesiri_contracts.assistant.v2.workflow_state import WorkflowStateV2
from mesiri_contracts.context.enums import WorkflowPhase
from workflows import WorkflowRuntime
from workflows.fakes import FakeCompiledGraph, FakeWorkflowInstanceRepository, FakeWorkflowRegistry

ORG = "11111111-1111-4111-8111-111111111111"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "66666666-6666-4666-8666-666666666666"
USR = "22222222-2222-4222-8222-222222222222"
WF_ID = "55555555-5555-4555-8555-555555555555"
CAT_TEXT = "materials"


def _message(text: str) -> NormalizedMessage:
    return NormalizedMessage(
        message_id="wamid.e2e.expense.1",
        correlation_id="cor_e2e_expense_1",
        sender=SenderInfo(wa_id="wa_engineer", profile_name="Engineer"),
        timestamp=datetime(2026, 7, 12, 10, 0, tzinfo=UTC),
        modality=InputModality.TEXT,
        text=text,
    )


def _awaiting_confirmation_state() -> WorkflowStateV2:
    draft = DraftActionV2(
        draft_id="draft_1",
        correlation_id="cor_e2e_expense_1",
        workflow_instance_id=WF_ID,
        action_type=DraftActionType.RECORD_EXPENSE,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        site_id=SITE,
        fields={"amount": 250, "category": CAT_TEXT, "description": "cement bags"},
    )
    return WorkflowStateV2(
        workflow_instance_id=WF_ID,
        workflow_key=WorkflowKey.EXPENSE_SUBMIT,
        correlation_id="cor_e2e_expense_1",
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        phase=WorkflowPhase.AWAITING_CONFIRMATION,
        draft_action=draft,
        pending_prompt="Confirm: expense of 250 for materials?",
    )


def _build_interaction_handler(
    *, workflow_repo: FakeWorkflowInstanceRepository, expense_repo, resolver=None
):
    workflow_runtime = WorkflowRuntime(
        registry=FakeWorkflowRegistry({WorkflowKey.EXPENSE_SUBMIT: FakeCompiledGraph({})}),
        repo=workflow_repo,
    )
    handler = RecordExpenseHandler(
        expense_repo, db=FakeDatabase(), resolver=resolver or FakeExpenseCategoryResolver()
    )
    dispatcher = ExpenseExecutionDispatcher(handler)
    return InteractionHandler(workflow_runtime, dispatcher=dispatcher)


async def test_confirm_reply_executes_domain_write_and_replies_recorded():
    workflow_repo = FakeWorkflowInstanceRepository()
    workflow_repo.seed(_awaiting_confirmation_state(), version=0)
    expense_repo = FakeExpenseExecutionRepository(workflow_repo=workflow_repo)
    interaction_handler = _build_interaction_handler(
        workflow_repo=workflow_repo, expense_repo=expense_repo
    )

    handled = await interaction_handler.handle_fast_path(USR, _message("yes"))

    assert handled is not None
    assert handled.execution_result is not None
    assert handled.execution_result.status is ExecutionStatus.SUCCEEDED
    assert handled.reply_text == "✅ Saved: Expense ₹250 (Materials)"

    # Persists exactly once, with the right organization/project/site/amount/
    # source -- category_id comes from the resolver (category_text -> id).
    assert len(expense_repo.expense_rows) == 1
    persisted = expense_repo.expense_rows[0]["command"]
    assert persisted.organization_id == ORG
    assert persisted.project_id == PRJ
    assert persisted.site_id == SITE
    assert persisted.amount == 250
    assert persisted.category_id is not None
    assert persisted.category_text == CAT_TEXT
    assert persisted.source == "whatsapp"

    saved_state, _ = workflow_repo._rows[WF_ID]  # noqa: SLF001 — test assertion
    assert saved_state.phase is WorkflowPhase.COMPLETED


async def test_confirm_with_no_category_field_still_succeeds():
    """The exact production bug: category is optional on the extraction
    side (see mesiri_contracts.assistant.candidates.ExpenseCandidate), so a
    draft with no `category` key at all -- e.g. "spent 250 on cement bags",
    which states no explicit category -- must still record successfully via
    the resolver's default-category fallback, not reply with a rejection."""
    draft = DraftActionV2(
        draft_id="draft_1",
        correlation_id="cor_e2e_expense_1",
        workflow_instance_id=WF_ID,
        action_type=DraftActionType.RECORD_EXPENSE,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        site_id=SITE,
        fields={"amount": 250},
    )
    state = WorkflowStateV2(
        workflow_instance_id=WF_ID,
        workflow_key=WorkflowKey.EXPENSE_SUBMIT,
        correlation_id="cor_e2e_expense_1",
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        phase=WorkflowPhase.AWAITING_CONFIRMATION,
        draft_action=draft,
        pending_prompt="Confirm: expense of 250?",
    )
    workflow_repo = FakeWorkflowInstanceRepository()
    workflow_repo.seed(state, version=0)
    expense_repo = FakeExpenseExecutionRepository(workflow_repo=workflow_repo)
    interaction_handler = _build_interaction_handler(
        workflow_repo=workflow_repo, expense_repo=expense_repo
    )

    handled = await interaction_handler.handle_fast_path(USR, _message("yes"))

    assert handled.execution_result.status is ExecutionStatus.SUCCEEDED
    assert handled.reply_text == "✅ Saved: Expense ₹250"
    assert len(expense_repo.expense_rows) == 1
    persisted = expense_repo.expense_rows[0]["command"]
    assert persisted.category_id is not None
    assert persisted.category_text is None


async def test_duplicate_confirm_reply_is_idempotent_and_replies_recorded():
    """A user sending "yes" twice (or a duplicated WhatsApp delivery) must not
    create a second expense — the second resume() is ALREADY_RESOLVED at the
    M7 layer, so the dispatcher is never even invoked a second time."""
    workflow_repo = FakeWorkflowInstanceRepository()
    workflow_repo.seed(_awaiting_confirmation_state(), version=0)
    expense_repo = FakeExpenseExecutionRepository(workflow_repo=workflow_repo)
    interaction_handler = _build_interaction_handler(
        workflow_repo=workflow_repo, expense_repo=expense_repo
    )

    first = await interaction_handler.handle_fast_path(USR, _message("yes"))
    second = await interaction_handler.handle_fast_path(USR, _message("yes"))

    assert first.execution_result.status is ExecutionStatus.SUCCEEDED
    # No pending workflow left for the second "yes" -> falls through to a new journey.
    assert second is None
    assert len(expense_repo.expense_rows) == 1


async def test_reject_reply_never_invokes_dispatcher():
    workflow_repo = FakeWorkflowInstanceRepository()
    workflow_repo.seed(_awaiting_confirmation_state(), version=0)
    expense_repo = FakeExpenseExecutionRepository(workflow_repo=workflow_repo)
    interaction_handler = _build_interaction_handler(
        workflow_repo=workflow_repo, expense_repo=expense_repo
    )

    handled = await interaction_handler.handle_fast_path(USR, _message("no"))

    assert handled is not None
    assert handled.execution_result is None
    assert handled.reply_text == "❌ Discarded. Nothing was recorded."
    assert expense_repo.expense_rows == []


async def test_unresolvable_category_is_rejected_and_workflow_reaches_execution_rejected():
    """A domain-level rejection (unresolvable category) is not the same as a
    user "no" -- the workflow still moves through CONFIRMED, but lands at
    EXECUTION_REJECTED rather than COMPLETED, and no expense is persisted."""
    workflow_repo = FakeWorkflowInstanceRepository()
    workflow_repo.seed(_awaiting_confirmation_state(), version=0)
    expense_repo = FakeExpenseExecutionRepository(workflow_repo=workflow_repo)
    interaction_handler = _build_interaction_handler(
        workflow_repo=workflow_repo,
        expense_repo=expense_repo,
        resolver=RejectingExpenseCategoryResolver(["category 'materials' not found"]),
    )

    handled = await interaction_handler.handle_fast_path(USR, _message("yes"))

    assert handled.execution_result.status is ExecutionStatus.REJECTED
    assert "couldn't record" in handled.reply_text.lower()
    assert expense_repo.expense_rows == []

    saved_state, _ = workflow_repo._rows[WF_ID]  # noqa: SLF001 — test assertion
    assert saved_state.phase is WorkflowPhase.EXECUTION_REJECTED


async def test_persistence_failure_reports_failed_not_success_and_persists_nothing():
    """A repository that raises mid-persist must never surface as a success
    reply, and must leave no partial expense row -- the Dispatcher's
    try/except converts the exception to FAILED (see dispatcher.py), and the
    fake's persist_success raises before appending anything, standing in for
    "the transaction rolled back, nothing was written"."""
    workflow_repo = FakeWorkflowInstanceRepository()
    workflow_repo.seed(_awaiting_confirmation_state(), version=0)
    interaction_handler = _build_interaction_handler(
        workflow_repo=workflow_repo, expense_repo=PersistSuccessRaisesRepository()
    )

    handled = await interaction_handler.handle_fast_path(USR, _message("yes"))

    assert handled is not None
    assert handled.execution_result is not None
    assert handled.execution_result.status is ExecutionStatus.FAILED
    assert handled.reply_text != "✅ Recorded. Thank you."

    # FAILED leaves the workflow at CONFIRMED (recoverable) -- the Dispatcher
    # never reaches the repository's phase-transition call because the
    # exception propagates out of handle_confirmed() before persist_success
    # returns normally.
    saved_state, _ = workflow_repo._rows[WF_ID]  # noqa: SLF001 — test assertion
    assert saved_state.phase is WorkflowPhase.CONFIRMED


async def test_execution_router_selects_expense_dispatcher_for_record_expense():
    """ActionTypeRoutingDispatcher must route an Expense confirm to the
    Expense dispatcher, not the Material one, when both are registered."""
    workflow_repo = FakeWorkflowInstanceRepository()
    workflow_repo.seed(_awaiting_confirmation_state(), version=0)
    expense_repo = FakeExpenseExecutionRepository(workflow_repo=workflow_repo)
    material_repo = FakeMaterialExecutionRepository(workflow_repo=workflow_repo)

    expense_handler = RecordExpenseHandler(
        expense_repo, db=FakeDatabase(), resolver=FakeExpenseCategoryResolver()
    )
    material_handler = ExecuteConfirmedMaterialActionHandler(
        db=FakeMaterialDatabase(), repo=material_repo, resolver=FakeMaterialResolver()
    )
    router = ActionTypeRoutingDispatcher(
        {
            DraftActionType.RECORD_EXPENSE: ExpenseExecutionDispatcher(expense_handler),
            DraftActionType.RECORD_MATERIAL_RECEIPT: MaterialExecutionDispatcher(material_handler),
            DraftActionType.RECORD_MATERIAL_USAGE: MaterialExecutionDispatcher(material_handler),
        }
    )
    workflow_runtime = WorkflowRuntime(
        registry=FakeWorkflowRegistry({WorkflowKey.EXPENSE_SUBMIT: FakeCompiledGraph({})}),
        repo=workflow_repo,
    )
    interaction_handler = InteractionHandler(workflow_runtime, dispatcher=router)

    handled = await interaction_handler.handle_fast_path(USR, _message("yes"))

    assert handled.execution_result.status is ExecutionStatus.SUCCEEDED
    assert len(expense_repo.expense_rows) == 1
    assert material_repo.material_rows == []


async def test_execution_router_still_selects_material_dispatcher_for_material_receipt():
    """The same routing dispatcher must still send a Material confirm to the
    Material dispatcher -- proves adding Expense didn't change Materials'
    existing routing behavior."""
    material_draft = DraftActionV2(
        draft_id="draft_2",
        correlation_id="cor_e2e_material_1",
        workflow_instance_id=WF_ID,
        action_type=DraftActionType.RECORD_MATERIAL_RECEIPT,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        fields={"material_name": "cement", "quantity": 20, "unit": "bags"},
    )
    material_state = WorkflowStateV2(
        workflow_instance_id=WF_ID,
        workflow_key=WorkflowKey.MATERIAL_RECEIPT,
        correlation_id="cor_e2e_material_1",
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        phase=WorkflowPhase.AWAITING_CONFIRMATION,
        draft_action=material_draft,
        pending_prompt="Confirm: 20 bags cement received?",
    )
    workflow_repo = FakeWorkflowInstanceRepository()
    workflow_repo.seed(material_state, version=0)
    expense_repo = FakeExpenseExecutionRepository(workflow_repo=workflow_repo)
    material_repo = FakeMaterialExecutionRepository(workflow_repo=workflow_repo)

    expense_handler = RecordExpenseHandler(
        expense_repo, db=FakeDatabase(), resolver=FakeExpenseCategoryResolver()
    )
    material_handler = ExecuteConfirmedMaterialActionHandler(
        db=FakeMaterialDatabase(), repo=material_repo, resolver=FakeMaterialResolver()
    )
    router = ActionTypeRoutingDispatcher(
        {
            DraftActionType.RECORD_EXPENSE: ExpenseExecutionDispatcher(expense_handler),
            DraftActionType.RECORD_MATERIAL_RECEIPT: MaterialExecutionDispatcher(material_handler),
        }
    )
    workflow_runtime = WorkflowRuntime(
        registry=FakeWorkflowRegistry({WorkflowKey.MATERIAL_RECEIPT: FakeCompiledGraph({})}),
        repo=workflow_repo,
    )
    interaction_handler = InteractionHandler(workflow_runtime, dispatcher=router)

    handled = await interaction_handler.handle_fast_path(USR, _message("yes"))

    assert handled.execution_result.status is ExecutionStatus.SUCCEEDED
    assert len(material_repo.material_rows) == 1
    assert expense_repo.expense_rows == []
