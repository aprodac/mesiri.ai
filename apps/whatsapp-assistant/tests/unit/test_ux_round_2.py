"""Assistant UX round 2 (request [38]): the one-site message, one question at
a time, optional prompts after the note, Malayalam receipts, two questions in
one message, and where the work was done."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.ports import ProjectSummary, SiteSummary
from channel.friendly_errors import friendly_rejection, is_question_rejection
from interactions.response_handler import render_execution_reply
from interactions.team_photo_hint import TeamPhotoHintStore
from mesiri.domains.progress.validation import validate_create_activity
from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from mesiri_contracts.assistant.canonical_event import CanonicalEventType, IntentCompleteness
from mesiri_contracts.assistant.planner_decision import PlannerDecisionType, WorkflowKey
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.resolved_context import ResolvedContextV2
from planning.plan import Plan, PlanOrigin, PlanStep, StepStatus
from planning.plan_store import PlanStore
from runtime.inbound_journey.decomposed_plan import _inherit_resolved_scope
from runtime.inbound_journey.process import _with_extra_query_answers
from runtime.plan_executor import plan_defers_rejection, plan_has_more_to_do
from runtime.reply_language import localize_fixed_reply
from workflows import (
    WorkflowResumeResult,
    WorkflowResumeStatus,
    WorkflowRunResult,
    WorkflowRunStatus,
)

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "44444444-4444-4444-8444-444444444444"
SITE_2 = "55555555-5555-4555-8555-555555555555"


class _Redis:
    def __init__(self) -> None:
        self._d: dict[str, Any] = {}

    def namespaced(self, *parts: str) -> str:
        return ":".join(parts)

    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        self._d[key] = value

    async def get_json(self, key: str) -> Any | None:
        return self._d.get(key)


def _context(*, project: str | None = None, site: str | None = None) -> ResolvedContextV2:
    return ResolvedContextV2(
        correlation_id="cor",
        source_message_id="msg",
        context_organization_id="ctx_org",
        context_user_id="ctx_user",
        context_project_id="ctx_prj" if project else None,
        context_site_id="ctx_site" if site else None,
        organization_id=ORG,
        user_id=USR,
        project_id=project,
        site_id=site,
        permissions=["progress:write"],
        timezone="Asia/Kolkata",
    )


def _event(*, project: str | None = None, site: str | None = None) -> CanonicalEventV2:
    return CanonicalEventV2(
        event_id="evt",
        correlation_id="cor",
        source_message_id="msg",
        event_type=CanonicalEventType.ACTIVITY_CONTINUATION_REQUESTED,
        completeness=IntentCompleteness.ACTIONABLE,
        organization_id=ORG,
        user_id=USR,
        project_id=project,
        site_id=site,
        permissions=[],
        fields={"narrative": "Plastering done on 2nd floor west side"},
    )


def _actor(sites: list[SiteSummary], projects: list[ProjectSummary] | None = None):
    return SimpleNamespace(
        user_id=USR,
        projects=projects if projects is not None else [ProjectSummary(id=PRJ, name="Green Villa")],
        sites=sites,
    )


# 1. One site: never ask --------------------------------------------------


def test_a_part_with_no_site_takes_the_only_site():
    event = _event()
    _inherit_resolved_scope(event, _context(), _actor([SiteSummary(id=SITE, name="Green Villa, Kakkanad", project_id=PRJ)]))
    assert (event.project_id, event.site_id) == (PRJ, SITE)


def test_a_part_takes_the_messages_resolved_site():
    event = _event()
    _inherit_resolved_scope(event, _context(project=PRJ, site=SITE), None)
    assert (event.project_id, event.site_id) == (PRJ, SITE)


def test_with_two_sites_nothing_is_guessed():
    event = _event(project=PRJ)
    sites = [SiteSummary(id=SITE, name="A", project_id=PRJ), SiteSummary(id=SITE_2, name="B", project_id=PRJ)]
    _inherit_resolved_scope(event, _context(project=PRJ), _actor(sites))
    assert event.site_id is None


def test_a_site_filled_this_way_passes_the_backends_site_check():
    from mesiri.application.progress.mapper import build_create_activity_command
    from mesiri_contracts.assistant.draft_action import DraftActionType
    from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
    from mesiri_contracts.assistant.v2.draft_action import DraftActionV2

    event = _event()
    _inherit_resolved_scope(event, _context(), _actor([SiteSummary(id=SITE, name="G", project_id=PRJ)]))
    draft = DraftActionV2(
        draft_id="d",
        correlation_id="cor",
        workflow_instance_id="wf",
        action_type=DraftActionType.CREATE_ACTIVITY,
        organization_id=ORG,
        user_id=USR,
        project_id=event.project_id,
        site_id=event.site_id,
        fields=dict(event.fields),
    )
    command = build_create_activity_command(
        ConfirmedActionV2(
            confirmed_action_id="c", workflow_instance_id="wf", correlation_id="cor",
            draft_action=draft, confirmed_by_user_id=USR,
        )
    )
    assert validate_create_activity(command) == []


# 4. Wording of a question --------------------------------------------------


def test_a_question_is_not_dressed_as_a_failure():
    result = ExecutionResult(
        status=ExecutionStatus.REJECTED, idempotency_key="k", rejection_reasons=["site is not resolved"]
    )
    text = render_execution_reply(result)
    assert "Couldn't record this" not in text
    assert text == "Not saved yet. Which site is this for?"


def test_a_real_failure_keeps_its_warning():
    result = ExecutionResult(
        status=ExecutionStatus.REJECTED, idempotency_key="k", rejection_reasons=["something odd"]
    )
    assert render_execution_reply(result).startswith("⚠️ Couldn't record this.")
    assert not is_question_rejection(["something odd"])
    assert friendly_rejection(["site is not resolved"]) == "Which site is this for?"


# 5. Malayalam receipts -----------------------------------------------------


def test_receipt_and_draft_note_come_back_in_malayalam():
    english = (
        "✅ Recorded. Thank you.\n\nSaved as a draft. You'll confirm it with tonight's report. "
        "Reply UNDO if it's wrong."
    )
    out = localize_fixed_reply(english, "Malayalam")
    assert "Recorded" not in out and "Saved as a draft" not in out
    assert "രേഖപ്പെടുത്തി" in out and "UNDO" in out
    assert localize_fixed_reply(english, "ml") == out


def test_other_text_and_languages_are_untouched():
    text = "✅ Recorded. Thank you. ₹2,000 · Note"
    assert localize_fixed_reply(text, None) == text
    assert localize_fixed_reply(text, "English") == text
    assert localize_fixed_reply(text, "Tamil") == text
    assert localize_fixed_reply("Total ₹2,000", "Malayalam") == "Total ₹2,000"
    assert "₹2,000" in localize_fixed_reply(text, "Malayalam")


# 2 + 3. One question at a time; optional prompts wait ------------------------


def _step(step_id, status, *, instance=None, fields=None):
    return PlanStep(
        step_id=step_id,
        workflow_key=WorkflowKey.SITE_UPDATE,
        event_type=CanonicalEventType.ACTIVITY_CONTINUATION_REQUESTED,
        fields=fields or {"narrative": "Plastering done on 2nd floor west side"},
        status=status,
        workflow_instance_id=instance,
    )


async def _store_with(steps, origin=PlanOrigin.DECOMPOSITION) -> PlanStore:
    store = PlanStore(_Redis())
    await store.start_plan(
        plan=Plan(
            plan_id="p", correlation_id="c", user_id=USR, organization_id=ORG,
            origin=origin, steps=tuple(steps),
        )
    )
    return store


def _rejected(instance: str, reason: str) -> SimpleNamespace:
    from mesiri_contracts.assistant.draft_action import DraftActionType
    from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
    from mesiri_contracts.assistant.v2.draft_action import DraftActionV2

    draft = DraftActionV2(
        draft_id="d", correlation_id="c", workflow_instance_id=instance,
        action_type=DraftActionType.CREATE_ACTIVITY, organization_id=ORG, user_id=USR,
        project_id=PRJ, site_id=None, fields={},
    )
    return SimpleNamespace(
        result=WorkflowResumeResult(
            status=WorkflowResumeStatus.CONFIRMED,
            workflow_instance_id=instance,
            correlation_id="c",
            confirmed_action=ConfirmedActionV2(
                confirmed_action_id="ca", workflow_instance_id=instance, correlation_id="c",
                draft_action=draft, confirmed_by_user_id=USR,
            ),
        ),
        execution_result=ExecutionResult(
            status=ExecutionStatus.REJECTED, idempotency_key=instance, rejection_reasons=[reason]
        ),
    )


@pytest.mark.anyio
async def test_a_rejected_question_waits_when_the_note_has_more_parts():
    store = await _store_with(
        [_step("s1", StepStatus.RUNNING, instance="wf_1"), _step("s2", StepStatus.PENDING)]
    )
    actor = SimpleNamespace(user_id=USR)
    assert await plan_defers_rejection(_rejected("wf_1", "site is not resolved"), plan_store=store, actor=actor)
    # a real failure is not deferred, and neither is the last part
    assert not await plan_defers_rejection(_rejected("wf_1", "boom"), plan_store=store, actor=actor)
    last = await _store_with([_step("s1", StepStatus.RUNNING, instance="wf_1")])
    assert not await plan_defers_rejection(_rejected("wf_1", "site is not resolved"), plan_store=last, actor=actor)


@pytest.mark.anyio
async def test_the_closing_summary_carries_the_question_with_the_words():
    import runtime.inbound_journey  # noqa: F401 -- import order, see test_19_oct_message_plan
    from runtime.plan_executor import _outcome_line

    step = PlanStep(
        step_id="s1",
        workflow_key=WorkflowKey.SITE_UPDATE,
        event_type=CanonicalEventType.ACTIVITY_CONTINUATION_REQUESTED,
        fields={"narrative": "Plastering done on 2nd floor west side"},
        status=StepStatus.FAILED,
        outcome_detail="Not saved yet. Which site is this for?",
    )
    line = _outcome_line(step, 3)
    assert "Plastering done on 2nd floor west side" in line and "Which site is this for?" in line


@pytest.mark.anyio
async def test_optional_prompts_wait_while_the_note_runs():
    mid = await _store_with(
        [_step("s1", StepStatus.RUNNING, instance="wf_1"), _step("s2", StepStatus.PENDING)]
    )
    assert await plan_has_more_to_do(mid, user_id=USR, finishing_instance_id="wf_1")

    last = await _store_with(
        [_step("s1", StepStatus.DONE, instance="wf_0"), _step("s2", StepStatus.RUNNING, instance="wf_1")]
    )
    assert not await plan_has_more_to_do(last, user_id=USR, finishing_instance_id="wf_1")

    single = await _store_with([_step("s1", StepStatus.RUNNING, instance="wf_1")], PlanOrigin.SINGLE_MESSAGE)
    assert not await plan_has_more_to_do(single, user_id=USR)
    assert not await plan_has_more_to_do(PlanStore(_Redis()), user_id=USR)


@pytest.mark.anyio
async def test_the_held_team_photo_offer_is_asked_once_after_the_note():
    store = TeamPhotoHintStore(_Redis())
    await store.set_hint(user_id=USR, report_id="rep_1")  # parked at confirmation
    await store.hold(user_id=USR, report_id="rep_1")
    assert await store.pop_hint(user_id=USR) is None  # no live offer meanwhile
    assert await store.pop_held(user_id=USR) == "rep_1"
    assert await store.pop_held(user_id=USR) is None


# 6. Two questions in one message ---------------------------------------------


class _Planner:
    def decide(self, event):
        return SimpleNamespace(decision_type=PlannerDecisionType.START_WORKFLOW)


class _Runtime:
    def __init__(self, prompts: dict[CanonicalEventType, str]) -> None:
        self._prompts = prompts

    async def start(self, decision, event):
        return WorkflowRunResult(
            status=WorkflowRunStatus.COMPLETED,
            workflow_key=WorkflowKey.MATERIAL_INVENTORY_QUERY,
            correlation_id="c",
            pending_prompt=self._prompts[event.event_type],
        )


def _query(event_type, *, completeness=IntentCompleteness.ACTIONABLE) -> CanonicalEventV2:
    return CanonicalEventV2(
        event_id="e", correlation_id="c", source_message_id="m", event_type=event_type,
        completeness=completeness, organization_id=ORG, user_id=USR, permissions=[], fields={},
    )


@pytest.mark.anyio
async def test_both_parts_of_a_two_part_question_are_answered():
    first = WorkflowRunResult(
        status=WorkflowRunStatus.COMPLETED,
        workflow_key=WorkflowKey.LABOUR_QUERY,
        correlation_id="c",
        pending_prompt="Today: 10 masons, 4 helpers.",
    )
    out = await _with_extra_query_answers(
        first,
        [_query(CanonicalEventType.INVENTORY_QUERY_ASKED)],
        planner=_Planner(),
        workflow_runtime=_Runtime({CanonicalEventType.INVENTORY_QUERY_ASKED: "Cement received: 40 bags."}),
        inventory_query=None,
    )
    assert out.pending_prompt == "Today: 10 masons, 4 helpers.\n\nCement received: 40 bags."


@pytest.mark.anyio
async def test_a_writing_part_is_never_started_as_an_extra():
    first = WorkflowRunResult(
        status=WorkflowRunStatus.COMPLETED,
        workflow_key=WorkflowKey.LABOUR_QUERY,
        correlation_id="c",
        pending_prompt="Today: 10 masons.",
    )
    out = await _with_extra_query_answers(
        first,
        [_query(CanonicalEventType.EXPENSE_REQUESTED)],
        planner=_Planner(),
        workflow_runtime=_Runtime({}),
        inventory_query=None,
    )
    assert out is first


# 7. Where the work was done -------------------------------------------------


def test_the_place_stays_in_the_work_narrative():
    from canonicalization.builder import _ensure_site_update_narrative

    fields = {"narrative": "Plastering done", "location": "2nd floor west side"}
    out = _ensure_site_update_narrative(fields, SimpleNamespace(intents=[1]))
    assert out["narrative"] == "Plastering done (2nd floor west side)"
    already = {"narrative": "Plastering on 2nd floor west side", "location": "2nd floor west side"}
    assert _ensure_site_update_narrative(already, SimpleNamespace(intents=[1])) == already
