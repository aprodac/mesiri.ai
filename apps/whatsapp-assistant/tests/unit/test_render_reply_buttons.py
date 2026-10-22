"""Unit tests for render_workflow_run_reply_spec's button vs plain-text split.

A confirmation prompt (STARTED, or an old one re-shown via
BLOCKED_PENDING_CONFIRMATION) must carry Yes/No buttons. An informational
reply with nothing to confirm (COMPLETED -- who_am_i, inventory_query) must
stay plain text; showing Yes/No under an answer that was never asking a
question would be actively confusing.
"""

from __future__ import annotations

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from runtime.inbound_journey import render_workflow_run_reply_spec
from workflows import WorkflowRunResult
from workflows.slots import SlotCandidate

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"


def _draft() -> DraftActionV2:
    return DraftActionV2(
        draft_id="draft_1",
        correlation_id="cor_1",
        workflow_instance_id="wf_1",
        action_type=DraftActionType.RECORD_MATERIAL_RECEIPT,
        organization_id=ORG,
        user_id=USR,
        fields={"material_name": "cement", "quantity": 50, "unit": "bags"},
    )


def test_resumed_slot_answer_landing_on_started_gets_yes_no_buttons():
    """The bug a real user hit: answering a mid-workflow slot question (e.g.
    "which account?") and having the graph complete straight to a
    confirmation must still show Yes/No buttons -- runtime/dependencies.py's
    handle_slot_answer fast path used to always send plain text regardless
    of the resumed WorkflowRunResult's status, so this exact "Confirm this
    record?" prompt showed up with no buttons at all. Calls
    render_workflow_run_reply_spec directly, the same function that fast
    path now uses instead of raw send_text."""
    result = WorkflowRunResult.started(
        workflow_key=WorkflowKey.EXPENSE_SUBMIT,
        correlation_id="cor_1",
        workflow_instance_id="wf_1",
        draft_action=_draft(),
        pending_prompt="*Confirm this record?*",
    )
    reply = render_workflow_run_reply_spec(result)
    assert reply.buttons is not None
    assert [b.id for b in reply.buttons] == ["confirm_yes", "confirm_no"]


def test_resumed_slot_answer_landing_on_another_slot_gets_a_list():
    """Same bug, the other shape: a resumed workflow can also land on a
    second AWAITING_INPUT slot (e.g. transfer's from-account then
    to-account) rather than a confirmation."""
    result = WorkflowRunResult.awaiting_input(
        workflow_key=WorkflowKey.TRANSFER,
        correlation_id="cor_1",
        workflow_instance_id="wf_1",
        pending_prompt="Which account should receive it?",
        slot_options=(
            SlotCandidate(value="acc_1", label="Site Cash"),
            SlotCandidate(value="acc_2", label="Company Account"),
        ),
    )
    reply = render_workflow_run_reply_spec(result)
    assert reply.list_rows is not None
    assert [row.id for row in reply.list_rows] == ["acc_1", "acc_2"]


def test_render_workflow_run_reply_spec_handles_failed_status():
    """FAILED can't reach _render_reply's workflow_run branch (excluded on
    purpose, see its docstring), but a resumed slot answer can fail and
    passes straight through render_workflow_run_reply_spec -- must not
    crash, and should say something sensible rather than nothing."""
    result = WorkflowRunResult.failed(workflow_key=WorkflowKey.EXPENSE_SUBMIT, correlation_id="cor_1")
    reply = render_workflow_run_reply_spec(result)
    assert reply.text
    assert reply.buttons is None
    assert reply.list_rows is None
