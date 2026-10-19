"""The 19 Oct live-test message, end to end up to the database write (request [37]).

"Today at Green Villa: 12 masons and 6 helpers. Plastering done on 2nd floor
east side. Received 40 bags cement from Sharma Traders. Paid 1500 rupees for
JCB." was split into parts. With the AI returning what it really returned,
the work-done part was rejected by the backend ("activity must have a
narrative or at least one quantity") and the cement part saved with no
supplier. This drives each part through the real segment understanding,
canonicalization, plan linking and workflow draft building, then the
backend's own command mapper and validators, and asserts the three parts
would save, with the supplier kept and the sender's words in the narrative.
"""

from __future__ import annotations

import dataclasses

import pytest

from canonicalization import build_canonical_event
from mesiri.application.expenses.mapper import build_command as build_expense_command
from mesiri.application.expenses.validation import validate as validate_expense
from mesiri.application.materials.mapper import build_command as build_material_command
from mesiri.application.progress.mapper import build_create_activity_command
from mesiri.domains.materials.validation import validate_receipt
from mesiri.domains.progress.validation import validate_create_activity
from mesiri.infrastructure.objectstorage.fake import FakeObjectStorage
from mesiri_ai.fakes import FakeVisionProvider, FakeVoiceExtractionProvider
from mesiri_ai.models import ExtractionResult
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
from mesiri_contracts.assistant.v2.resolved_context import ResolvedContextV2
from planning.binding import build_event
from planning.decomposition import build_plan_from_segments
from understanding.pipeline import UnderstandingPipeline
from workflows.expense_capture import nodes as expense_nodes
from workflows.material import nodes as material_nodes
from workflows.site_update import nodes as site_nodes

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "44444444-4444-4444-8444-444444444444"

# What the AI returned for each part on 19 Oct: the work-done part with no
# narrative, the cement part under an aliased supplier key.
SEGMENTS = {
    "Plastering done on 2nd floor east side": ExtractionResult(
        semantic_type="general_site_update",
        fields={"work_type": "plastering", "location": "2nd floor east side"},
        provider="fake",
    ),
    "Received 40 bags cement from Sharma Traders": ExtractionResult(
        semantic_type="material_update",
        fields={
            "material_name": "cement",
            "quantity": 40,
            "unit": "bags",
            "direction": "received",
            "supplier_name": "Sharma Traders",
        },
        provider="fake",
    ),
    "Paid 1500 rupees for JCB": ExtractionResult(
        semantic_type="expense",
        fields={"amount": 1500, "currency": "rupees", "vendor": "JCB", "category": "Equipment rental"},
        provider="fake",
    ),
}


class _PerTextExtraction:
    provider = "fake"

    async def extract(self, text, **kwargs):
        return SEGMENTS[text]


def _context() -> ResolvedContextV2:
    return ResolvedContextV2(
        correlation_id="cor_19oct",
        source_message_id="msg_19oct",
        context_organization_id="ctx_org",
        context_user_id="ctx_user",
        context_project_id="ctx_prj",
        context_site_id="ctx_site",
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        site_id=SITE,
        permissions=["progress:write"],
        timezone="Asia/Kolkata",
    )


def _state(step_event, workflow_key: WorkflowKey, instance: str) -> dict:
    return {
        "workflow_key": workflow_key.value,
        "correlation_id": "cor_19oct",
        "workflow_instance_id": instance,
        "organization_id": ORG,
        "user_id": USR,
        "project_id": PRJ,
        "site_id": SITE,
        "collected_fields": dict(step_event.fields),
    }


def _confirmed(draft, instance: str) -> ConfirmedActionV2:
    return ConfirmedActionV2(
        confirmed_action_id=f"conf_{instance}",
        workflow_instance_id=instance,
        correlation_id="cor_19oct",
        draft_action=draft,
        confirmed_by_user_id=USR,
    )


async def _plan():
    pipeline = UnderstandingPipeline(
        voice_extraction=FakeVoiceExtractionProvider(),
        vision=FakeVisionProvider(),
        extraction=_PerTextExtraction(),
        object_storage=FakeObjectStorage(),
    )
    events = []
    for text in SEGMENTS:
        understanding = await pipeline.understand_text_segment(
            text, source_message_id="msg_19oct", correlation_id="cor_19oct"
        )
        events.append(build_canonical_event(understanding, _context()))
    result = build_plan_from_segments(events, plan_id="plan_19oct")
    assert result.plan is not None and not result.skipped
    return result.plan


@pytest.mark.anyio
async def test_all_three_parts_would_save_with_supplier_and_narrative():
    plan = await _plan()
    keys = [step.workflow_key for step in plan.steps]
    assert keys == [WorkflowKey.SITE_UPDATE, WorkflowKey.MATERIAL_RECEIPT, WorkflowKey.EXPENSE_SUBMIT]

    site_step, material_step, expense_step = plan.steps

    # 1. Work done: the sender's words are the narrative, so the backend accepts it.
    event = build_event(site_step, plan)
    draft = site_nodes.build_draft(_state(event, WorkflowKey.SITE_UPDATE, "wf_1"))["draft_action"]
    command = build_create_activity_command(_confirmed(draft, "wf_1"))
    assert command.narrative == "Plastering done on 2nd floor east side"
    assert validate_create_activity(command) == []

    # 2. Material received: supplier carried through to the receipt command.
    event = build_event(material_step, plan)
    draft = material_nodes.build_draft(_state(event, WorkflowKey.MATERIAL_RECEIPT, "wf_2"))["draft_action"]
    material_command = build_material_command(_confirmed(draft, "wf_2"))
    assert material_command.supplier == "Sharma Traders"
    assert validate_receipt(material_command) == []
    assert "Supplier: Sharma Traders" in material_nodes.request_confirmation(
        {"draft_action": draft}
    )["pending_prompt"]

    # 3. Expense: valid, and the confirmation reads in plain words.
    event = build_event(expense_step, plan)
    resolved = expense_nodes.resolve_account(
        {"collected_fields": {**event.fields, "account_candidates": []}}
    )["collected_fields"]
    state = _state(event, WorkflowKey.EXPENSE_SUBMIT, "wf_3")
    state["collected_fields"] = resolved
    draft = expense_nodes.build_draft(state)["draft_action"]
    assert validate_expense(build_expense_command(_confirmed(draft, "wf_3"))) == []
    prompt = expense_nodes.request_confirmation({"draft_action": draft})["pending_prompt"]
    assert "Amount: ₹1,500" in prompt
    assert "For: JCB" in prompt
    assert "Category: Equipment rental" in prompt
    assert "Paid: own pocket (no company account set up yet)" in prompt
    for raw in ("paid_from_own_pocket", "currency", "amount:", "own_pocket_assumed"):
        assert raw not in prompt


@pytest.mark.anyio
async def test_the_summary_names_work_in_plain_words():
    # runtime.inbound_journey first: runtime.plan_executor and it import each
    # other, and only that order resolves.
    import runtime.inbound_journey  # noqa: F401
    from planning.plan import StepStatus
    from runtime.plan_executor import format_plan_summary

    plan = await _plan()
    done = dataclasses.replace(
        plan, steps=tuple(dataclasses.replace(s, status=StepStatus.DONE) for s in plan.steps)
    )
    summary = format_plan_summary(done)
    assert "Work done" in summary and "Material received" in summary and "Expense" in summary
    for raw in ("site.update", "material.receipt", "expense.submit"):
        assert raw not in summary
