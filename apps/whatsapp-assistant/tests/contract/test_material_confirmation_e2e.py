"""End-to-end M8 confirmation flow: user replies "yes" -> M7 resumes the
workflow to CONFIRMED -> M8 executes the domain write -> reply reflects the
real outcome. Fakes only (no live DB), matching the fakes-backed pattern in
test_context_runtime.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from interactions import InteractionHandler
from mesiri.application.materials.dispatcher import MaterialExecutionDispatcher
from mesiri.application.materials.fakes import (
    FakeDatabase,
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
USR = "22222222-2222-4222-8222-222222222222"
WF_ID = "55555555-5555-4555-8555-555555555555"


def _message(text: str) -> NormalizedMessage:
    return NormalizedMessage(
        message_id="wamid.e2e.1",
        correlation_id="cor_e2e_1",
        sender=SenderInfo(wa_id="wa_engineer", profile_name="Engineer"),
        timestamp=datetime(2026, 7, 9, 10, 0, tzinfo=UTC),
        modality=InputModality.TEXT,
        text=text,
    )


def _awaiting_confirmation_state() -> WorkflowStateV2:
    draft = DraftActionV2(
        draft_id="draft_1",
        correlation_id="cor_e2e_1",
        workflow_instance_id=WF_ID,
        action_type=DraftActionType.RECORD_MATERIAL_RECEIPT,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        fields={"material_name": "cement", "quantity": 20, "unit": "bags"},
    )
    return WorkflowStateV2(
        workflow_instance_id=WF_ID,
        workflow_key=WorkflowKey.MATERIAL_RECEIPT,
        correlation_id="cor_e2e_1",
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        phase=WorkflowPhase.AWAITING_CONFIRMATION,
        draft_action=draft,
        pending_prompt="Confirm: 20 bags cement received?",
    )


def _build_interaction_handler(*, workflow_repo: FakeWorkflowInstanceRepository, material_repo):
    workflow_runtime = WorkflowRuntime(
        registry=FakeWorkflowRegistry({WorkflowKey.MATERIAL_RECEIPT: FakeCompiledGraph({})}),
        repo=workflow_repo,
    )
    handler = ExecuteConfirmedMaterialActionHandler(
        db=FakeDatabase(), repo=material_repo, resolver=FakeMaterialResolver()
    )
    dispatcher = MaterialExecutionDispatcher(handler)
    return InteractionHandler(workflow_runtime, dispatcher=dispatcher)


async def test_confirm_reply_executes_domain_write_and_replies_recorded():
    workflow_repo = FakeWorkflowInstanceRepository()
    workflow_repo.seed(_awaiting_confirmation_state(), version=0)
    material_repo = FakeMaterialExecutionRepository(workflow_repo=workflow_repo)
    interaction_handler = _build_interaction_handler(
        workflow_repo=workflow_repo, material_repo=material_repo
    )

    handled = await interaction_handler.handle_fast_path(USR, _message("yes"))

    assert handled is not None
    assert handled.execution_result is not None
    assert handled.execution_result.status is ExecutionStatus.SUCCEEDED
    assert handled.reply_text == "✅ Saved: Cement in: 20 bags"

    assert len(material_repo.material_rows) == 1
    assert material_repo.material_rows[0]["table"] == "material_receipts"
    saved_state, _ = workflow_repo._rows[WF_ID]  # noqa: SLF001 — test assertion
    assert saved_state.phase is WorkflowPhase.COMPLETED


async def test_duplicate_confirm_reply_is_idempotent_and_replies_recorded():
    """A user sending "yes" twice (or a duplicated WhatsApp delivery) must not
    create a second domain row — the second resume() is ALREADY_RESOLVED at
    the M7 layer, so the dispatcher is never even invoked a second time."""
    workflow_repo = FakeWorkflowInstanceRepository()
    workflow_repo.seed(_awaiting_confirmation_state(), version=0)
    material_repo = FakeMaterialExecutionRepository(workflow_repo=workflow_repo)
    interaction_handler = _build_interaction_handler(
        workflow_repo=workflow_repo, material_repo=material_repo
    )

    first = await interaction_handler.handle_fast_path(USR, _message("yes"))
    second = await interaction_handler.handle_fast_path(USR, _message("yes"))

    assert first.execution_result.status is ExecutionStatus.SUCCEEDED
    # No pending workflow left for the second "yes" -> falls through to a new journey.
    assert second is None
    assert len(material_repo.material_rows) == 1


async def test_reject_reply_never_invokes_dispatcher():
    workflow_repo = FakeWorkflowInstanceRepository()
    workflow_repo.seed(_awaiting_confirmation_state(), version=0)
    material_repo = FakeMaterialExecutionRepository(workflow_repo=workflow_repo)
    interaction_handler = _build_interaction_handler(
        workflow_repo=workflow_repo, material_repo=material_repo
    )

    handled = await interaction_handler.handle_fast_path(USR, _message("no"))

    assert handled is not None
    assert handled.execution_result is None
    assert handled.reply_text == "❌ Discarded. Nothing was recorded."
    assert material_repo.material_rows == []
