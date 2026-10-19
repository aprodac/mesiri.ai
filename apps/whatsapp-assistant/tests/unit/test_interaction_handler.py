"""InteractionHandler — unit tests (fakes only, no LangGraph, no DB)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.ports import ActorIdentity
from channel.replies import CATEGORY_ROWS
from interactions.classifier_port import InteractionClassifierPort
from interactions.handler import InteractionHandler
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from mesiri_contracts.assistant.v2.interaction_spec import (
    FieldCorrection,
    InteractionIntent,
    InteractionSegment,
    InteractionSpecV2,
)
from mesiri_contracts.assistant.v2.workflow_state import WorkflowStateV2
from mesiri_contracts.context.enums import WorkflowPhase
from workflows import WorkflowRegistry, WorkflowResumeStatus, WorkflowRunStatus, WorkflowRuntime
from workflows.fakes import FakeWorkflowInstanceRepository

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
WF = "11111111-1111-4111-8111-1111111111aa"


def _message(text: str) -> NormalizedMessage:
    return NormalizedMessage(
        message_id="wamid.1",
        correlation_id="cor_reply_1",
        sender=SenderInfo(wa_id="919000000000", profile_name="Engineer"),
        timestamp=datetime(2026, 7, 8, 10, 0, tzinfo=UTC),
        modality=InputModality.TEXT,
        text=text,
    )


def _awaiting_state() -> WorkflowStateV2:
    draft = DraftActionV2(
        draft_id="d1",
        correlation_id="c1",
        workflow_instance_id=WF,
        action_type=DraftActionType.RECORD_MATERIAL_RECEIPT,
        organization_id=ORG,
        user_id=USR,
        fields={"material_name": "cement", "quantity": 20, "unit": "bags"},
    )
    return WorkflowStateV2(
        workflow_instance_id=WF,
        workflow_key=WorkflowKey.MATERIAL_RECEIPT,
        correlation_id="c1",
        organization_id=ORG,
        user_id=USR,
        phase=WorkflowPhase.AWAITING_CONFIRMATION,
        draft_action=draft,
        pending_prompt="Confirm?",
    )


class FakeGraph:
    async def ainvoke(self, state: dict) -> dict:
        self.last_state = state
        draft = _awaiting_state().draft_action
        draft.fields = state.get("collected_fields", {})
        return {
            "draft_action": draft,
            "pending_prompt": "Updated prompt",
        }


class FakeInteractionClassifier(InteractionClassifierPort):
    def __init__(self):
        self.next_response: InteractionSpecV2 | None = None
        self.calls = []

    async def classify(
        self,
        original_text: str,
        translated_text: str | None,
        draft_fields: dict[str, Any],
        correlation_id: str,
    ) -> InteractionSpecV2:
        self.calls.append((original_text, translated_text, draft_fields, correlation_id))
        if self.next_response:
            return self.next_response
        return InteractionSpecV2(version="v2", correlation_id=correlation_id, segments=[])


def _handler(
    repo: FakeWorkflowInstanceRepository, classifier: InteractionClassifierPort | None = None
) -> InteractionHandler:
    registry = WorkflowRegistry()
    registry._compiled[WorkflowKey.MATERIAL_RECEIPT] = FakeGraph()
    return InteractionHandler(WorkflowRuntime(registry=registry, repo=repo), classifier=classifier)


async def test_no_active_workflow_returns_none():
    handler = _handler(FakeWorkflowInstanceRepository())
    assert await handler.handle_fast_path(USR, _message("yes")) is None


async def test_confirm_reply_resumes_and_returns_reply():
    repo = FakeWorkflowInstanceRepository()
    repo.seed(_awaiting_state(), version=0)
    handler = _handler(repo)

    handled = await handler.handle_fast_path(USR, _message("yes"))

    assert handled is not None
    assert handled.result.status is WorkflowResumeStatus.CONFIRMED
    assert "Recorded" in handled.reply_text
    assert repo._rows[WF][0].phase is WorkflowPhase.CONFIRMED


async def test_unrelated_reply_falls_through_to_normal_journey():
    """A user with a pending confirmation can still send an unrelated message —
    it must NOT be swallowed by the active workflow."""
    repo = FakeWorkflowInstanceRepository()
    repo.seed(_awaiting_state(), version=0)
    handler = _handler(repo)

    handled = await handler.handle_fast_path(USR, _message("50 bags steel arrived at site B"))

    assert handled is None  # → caller runs the normal pipeline
    assert repo._rows[WF][0].phase is WorkflowPhase.AWAITING_CONFIRMATION  # untouched


async def test_duplicate_confirm_is_idempotent():
    repo = FakeWorkflowInstanceRepository()
    repo.seed(_awaiting_state(), version=0)
    handler = _handler(repo)

    first = await handler.handle_fast_path(USR, _message("yes"))
    assert first.result.status is WorkflowResumeStatus.CONFIRMED

    # The workflow is no longer awaiting → a second "yes" finds nothing to resume.
    second = await handler.handle_fast_path(USR, _message("yes"))
    assert second is None
    assert repo._rows[WF][1] == 1  # exactly one transition applied


async def test_slow_path_correction_resumes_with_new_draft():
    repo = FakeWorkflowInstanceRepository()
    repo.seed(_awaiting_state(), version=0)

    classifier = FakeInteractionClassifier()
    spec = InteractionSpecV2(
        correlation_id="c1",
        segments=[
            InteractionSegment(
                intent=InteractionIntent.CORRECTION,
                segment_text="make it 60",
                corrections=[FieldCorrection(field_name="quantity", new_value=60)],
            )
        ],
    )
    classifier.next_response = spec

    handler = _handler(repo, classifier=classifier)

    handled = await handler.handle_slow_path(USR, _message("make it 60"), "make it 60", None)

    assert handled is not None
    assert handled.result.status is WorkflowRunStatus.STARTED
    assert handled.reply_text == "Updated prompt"

    # Check that it updated the state in the repo but stayed AWAITING_CONFIRMATION
    updated_state = repo._rows[WF][0]
    assert updated_state.phase is WorkflowPhase.AWAITING_CONFIRMATION
    assert updated_state.collected_fields["quantity"] == 60
    assert updated_state.draft_action.fields["quantity"] == 60


async def test_slow_path_unrelated_falls_through():
    repo = FakeWorkflowInstanceRepository()
    repo.seed(_awaiting_state(), version=0)

    classifier = FakeInteractionClassifier()
    spec = InteractionSpecV2(
        correlation_id="c1",
        segments=[InteractionSegment(intent=InteractionIntent.UNRELATED, segment_text="unrelated")],
    )
    classifier.next_response = spec

    handler = _handler(repo, classifier=classifier)

    handled = await handler.handle_slow_path(USR, _message("unrelated"), "unrelated", None)

    assert handled is None
    assert repo._rows[WF][0].phase is WorkflowPhase.AWAITING_CONFIRMATION


async def test_slow_path_concurrent_corrections_rejected():
    repo = FakeWorkflowInstanceRepository()
    repo.seed(_awaiting_state(), version=0)

    classifier = FakeInteractionClassifier()
    spec = InteractionSpecV2(
        correlation_id="c1",
        segments=[
            InteractionSegment(
                intent=InteractionIntent.CORRECTION,
                segment_text="make it 60",
                corrections=[FieldCorrection(field_name="quantity", new_value=60)],
            )
        ],
    )
    classifier.next_response = spec

    handler = _handler(repo, classifier=classifier)

    # Instead of modifying the repo before calling the handler, we'll
    # override the transition method to simulate it failing due to OCC.
    async def failing_transition(*args, **kwargs):
        return False

    repo.transition = failing_transition

    handled = await handler.handle_slow_path(USR, _message("make it 60"), "make it 60", None)

    assert handled is not None
    assert handled.result.status is WorkflowRunStatus.FAILED
    assert handled.reply_text == "Sorry, I couldn't apply that update — please try again."


async def test_slow_path_sibling_segments():
    repo = FakeWorkflowInstanceRepository()
    repo.seed(_awaiting_state(), version=0)

    classifier = FakeInteractionClassifier()
    # A single message produces TWO segments: a CORRECTION and an UNRELATED
    spec = InteractionSpecV2(
        correlation_id="c1",
        segments=[
            InteractionSegment(
                intent=InteractionIntent.CORRECTION,
                segment_text="make it 60",
                corrections=[FieldCorrection(field_name="quantity", new_value=60)],
            ),
            InteractionSegment(
                intent=InteractionIntent.UNRELATED, segment_text="also 5 workers arrived"
            ),
        ],
    )
    classifier.next_response = spec

    handler = _handler(repo, classifier=classifier)

    handled = await handler.handle_slow_path(
        USR,
        _message("make it 60, also 5 workers arrived"),
        "make it 60, also 5 workers arrived",
        None,
    )

    assert handled is not None
    # 1. The CORRECTION updated the pending workflow
    assert handled.result.status is WorkflowRunStatus.STARTED
    # 2. The UNRELATED segment was collected and returned
    assert handled.unrelated_text == "also 5 workers arrived"

    # Verify the workflow was actually updated
    updated_state = repo._rows[WF][0]
    assert updated_state.draft_action.fields["quantity"] == 60


def _interactive_message(row_id: str, title: str = "Material") -> NormalizedMessage:
    return NormalizedMessage(
        message_id="wamid.tap",
        correlation_id="cor_tap_1",
        sender=SenderInfo(wa_id="919000000000", profile_name="Engineer"),
        timestamp=datetime(2026, 7, 8, 10, 0, tzinfo=UTC),
        modality=InputModality.INTERACTIVE,
        text=title,
        metadata={"interactive_reply_id": row_id, "interactive_reply_type": "list_reply"},
    )


def test_category_tap_returns_the_workflows_inside_that_category():
    """Tapping a category opens the second tier: the workflows it contains,
    as a list. Material still surfaces Arrived/Used, but as list rows
    carrying the same dir_* ids the direction-lock handler already owns --
    so the direction is still locked by a tap, never inferred from speech."""
    handler = _handler(FakeWorkflowInstanceRepository())
    prompt = handler.handle_category_tap(_interactive_message("cat_material"))
    assert prompt is not None
    assert "material" in prompt.text.lower()
    assert prompt.list_rows is not None
    assert {r.id for r in prompt.list_rows} >= {"dir_received", "dir_used"}


def test_category_tap_offers_every_workflow_in_a_multi_workflow_category():
    """"Money" is the widest category -- the flat v1 menu exposed only
    "Expense" from it, leaving transfers, balances, petty cash and
    reversals undiscoverable despite all four being built."""
    handler = _handler(FakeWorkflowInstanceRepository())
    prompt = handler.handle_category_tap(_interactive_message("cat_finance"))
    assert prompt is not None
    assert prompt.list_rows is not None
    ids = {r.id for r in prompt.list_rows}
    assert {
        "wf_expense.submit",
        "wf_finance.transfer",
        "wf_finance.petty_cash",
        "wf_finance.reverse",
        "wf_finance.account_query",
    } <= ids
    # WhatsApp rejects a list over 10 rows outright.
    assert len(prompt.list_rows) <= 10


def test_workflow_tap_returns_that_workflows_prompt_and_examples():
    handler = _handler(FakeWorkflowInstanceRepository())
    prompt = handler.handle_category_tap(_interactive_message("wf_finance.transfer"))
    assert prompt is not None
    assert "transfer" in prompt.text.lower()
    # The example comes from the registry, so it is the same string the
    # control panel documents for this workflow.
    assert "Company Account" in prompt.text
    assert prompt.list_rows is None


def test_legacy_flat_menu_row_id_still_opens_the_right_category():
    """A menu sent before the tiered rollout can still be sitting in a
    user's chat. An old "cat_expense" tap must land somewhere useful rather
    than fall through to the AI pipeline as unrecognized text."""
    handler = _handler(FakeWorkflowInstanceRepository())
    prompt = handler.handle_category_tap(_interactive_message("cat_expense"))
    assert prompt is not None
    assert prompt.list_rows is not None
    assert "wf_expense.submit" in {r.id for r in prompt.list_rows}


def test_material_direction_ids_fall_through_to_the_direction_handler():
    """dir_received/dir_used are owned by handle_material_direction_tap,
    which sets the direction hint as well as replying. handle_category_tap
    must not answer them first and swallow that."""
    handler = _handler(FakeWorkflowInstanceRepository())
    assert handler.handle_category_tap(_interactive_message("dir_received")) is None
    assert handler.handle_category_tap(_interactive_message("dir_used")) is None


def test_material_direction_tap_returns_tailored_prompt():
    handler = _handler(FakeWorkflowInstanceRepository())
    arrived_prompt = handler.handle_material_direction_tap(_interactive_message("dir_received"))
    assert arrived_prompt is not None
    assert "arrived" in arrived_prompt.lower()

    used_prompt = handler.handle_material_direction_tap(_interactive_message("dir_used"))
    assert used_prompt is not None
    assert "used" in used_prompt.lower()


def test_material_direction_tap_is_none_for_unrelated_ids():
    handler = _handler(FakeWorkflowInstanceRepository())
    assert handler.handle_material_direction_tap(_interactive_message("cat_material")) is None
    assert handler.handle_material_direction_tap(_message("dir_received")) is None


def test_category_tap_is_none_for_plain_text():
    """A regular text message must never be mistaken for a menu tap, even if
    someone happens to type a row id verbatim."""
    handler = _handler(FakeWorkflowInstanceRepository())
    assert handler.handle_category_tap(_message("cat_material")) is None


def test_category_tap_is_none_for_an_unrecognized_row_id():
    handler = _handler(FakeWorkflowInstanceRepository())
    assert handler.handle_category_tap(_interactive_message("cat_does_not_exist")) is None


def test_category_tap_does_not_touch_workflow_state():
    """A category tap is pure UI navigation -- it must never create, resume,
    or otherwise touch a workflow instance."""
    repo = FakeWorkflowInstanceRepository()
    handler = _handler(repo)
    handler.handle_category_tap(_interactive_message("cat_expense"))
    assert repo._rows == {}


def test_image_purpose_tap_returns_the_row_id_for_expense():
    handler = _handler(FakeWorkflowInstanceRepository())
    assert handler.handle_image_purpose_tap(_interactive_message("img_expense")) == "img_expense"


def test_image_purpose_tap_returns_the_row_id_for_site_update():
    handler = _handler(FakeWorkflowInstanceRepository())
    assert (
        handler.handle_image_purpose_tap(_interactive_message("img_site_update"))
        == "img_site_update"
    )


def test_image_purpose_tap_is_none_for_an_unrecognized_row_id():
    handler = _handler(FakeWorkflowInstanceRepository())
    assert handler.handle_image_purpose_tap(_interactive_message("cat_expense")) is None


def test_image_purpose_tap_is_none_for_plain_text():
    handler = _handler(FakeWorkflowInstanceRepository())
    assert handler.handle_image_purpose_tap(_message("img_expense")) is None


def test_greeting_trigger_returns_the_menu_for_a_bare_hi():
    handler = _handler(FakeWorkflowInstanceRepository())
    spec = handler.handle_greeting_trigger(_message("hi"))
    assert spec is not None
    assert spec.list_rows is not None
    # The top tier is one row per category with something built in it, and
    # WhatsApp rejects a list over 10 rows -- the cap that made the menu
    # tiered in the first place, with 24 pickable workflows behind it.
    assert spec.list_rows == CATEGORY_ROWS
    assert 0 < len(spec.list_rows) <= 10


def test_greeting_trigger_is_none_for_a_real_report():
    handler = _handler(FakeWorkflowInstanceRepository())
    assert handler.handle_greeting_trigger(_message("50 bags of cement arrived")) is None


def test_greeting_trigger_is_none_for_voice_even_with_greeting_text():
    """There's no text at normalization time for voice -- this fast path
    only ever applies to TEXT modality (see understanding/pipeline.py for
    the post-transcription check that covers voice instead)."""
    handler = _handler(FakeWorkflowInstanceRepository())
    voice_message = NormalizedMessage(
        message_id="wamid.voice",
        correlation_id="cor_voice_1",
        sender=SenderInfo(wa_id="919000000000", profile_name="Engineer"),
        timestamp=datetime(2026, 7, 8, 10, 0, tzinfo=UTC),
        modality=InputModality.VOICE,
        text="hi",  # even if somehow populated, modality gates this off
    )
    assert handler.handle_greeting_trigger(voice_message) is None


def _actor() -> ActorIdentity:
    return ActorIdentity(
        user_id=USR,
        full_name="Ravi",
        role="SITE_ENGINEER",
        organization_id=ORG,
        org_name="Superman Company",
        org_active=True,
    )


def test_whoami_trigger_returns_the_identity_summary_for_a_bare_whoami():
    handler = _handler(FakeWorkflowInstanceRepository())
    reply = handler.handle_whoami_trigger(_message("who am i"), _actor())
    assert reply is not None
    assert "Ravi" in reply
    assert "Superman Company" in reply


def test_whoami_trigger_is_none_for_a_real_report():
    handler = _handler(FakeWorkflowInstanceRepository())
    assert handler.handle_whoami_trigger(_message("50 bags of cement arrived"), _actor()) is None


def test_whoami_trigger_is_none_for_voice_even_with_whoami_text():
    """Same modality gate as handle_greeting_trigger -- no text at
    normalization time for voice."""
    handler = _handler(FakeWorkflowInstanceRepository())
    voice_message = NormalizedMessage(
        message_id="wamid.voice2",
        correlation_id="cor_voice_2",
        sender=SenderInfo(wa_id="919000000000", profile_name="Engineer"),
        timestamp=datetime(2026, 7, 8, 10, 0, tzinfo=UTC),
        modality=InputModality.VOICE,
        text="who am i",
    )
    assert handler.handle_whoami_trigger(voice_message, _actor()) is None


def _collecting_state() -> WorkflowStateV2:
    return WorkflowStateV2(
        workflow_instance_id=WF,
        workflow_key=WorkflowKey.EXPENSE_SUBMIT,
        correlation_id="c1",
        organization_id=ORG,
        user_id=USR,
        phase=WorkflowPhase.COLLECTING_FIELDS,
        collected_fields={"amount": 250, "account_candidates": [{"id": "a1", "name": "Cash"}]},
        awaiting_slot="account_id",
        pending_prompt="Which account?",
    )


class SlotResolvingFakeGraph:
    """Resolves to a draft once `_slot_answer_text` is present, mirroring
    expense_capture's real resolve_account -> build_draft -> request_confirmation."""

    async def ainvoke(self, state: dict) -> dict:
        fields = dict(state.get("collected_fields") or {})
        if fields.pop("_slot_answer_text", None) == "1":
            fields["account_id"] = "a1"
            draft = DraftActionV2(
                draft_id="d2",
                correlation_id="c1",
                workflow_instance_id=WF,
                action_type=DraftActionType.RECORD_EXPENSE,
                organization_id=ORG,
                user_id=USR,
                fields=fields,
            )
            return {
                "draft_action": draft,
                "pending_prompt": "Confirm?",
                "awaiting_slot": None,
                "collected_fields": fields,
            }
        return {
            "awaiting_slot": "account_id",
            "pending_prompt": "Which account?",
            "collected_fields": fields,
        }


def _handler_for_expense(repo: FakeWorkflowInstanceRepository) -> InteractionHandler:
    registry = WorkflowRegistry()
    registry._compiled[WorkflowKey.EXPENSE_SUBMIT] = SlotResolvingFakeGraph()
    return InteractionHandler(WorkflowRuntime(registry=registry, repo=repo))


async def test_slot_answer_resolves_and_returns_confirmation_prompt():
    repo = FakeWorkflowInstanceRepository()
    repo.seed(_collecting_state(), version=0)
    handler = _handler_for_expense(repo)

    handled = await handler.handle_slot_answer(USR, _message("1"))

    assert handled is not None
    assert handled.result.status is WorkflowRunStatus.STARTED
    assert handled.reply_text == "Confirm?"
    assert repo._rows[WF][0].phase is WorkflowPhase.AWAITING_CONFIRMATION


async def test_slot_answer_no_active_collecting_workflow_returns_none():
    handler = _handler_for_expense(FakeWorkflowInstanceRepository())
    assert await handler.handle_slot_answer(USR, _message("1")) is None


async def test_slot_answer_ignores_voice_modality():
    repo = FakeWorkflowInstanceRepository()
    repo.seed(_collecting_state(), version=0)
    handler = _handler_for_expense(repo)
    voice_message = NormalizedMessage(
        message_id="wamid.voice3",
        correlation_id="cor_voice_3",
        sender=SenderInfo(wa_id="919000000000", profile_name="Engineer"),
        timestamp=datetime(2026, 7, 8, 10, 0, tzinfo=UTC),
        modality=InputModality.VOICE,
        text="1",
    )
    assert await handler.handle_slot_answer(USR, voice_message) is None


def test_greeting_trigger_introduces_mesiri_only_on_the_first_message():
    """The intro copy behind is_first_message existed from the start but
    nothing ever set the flag, so every first-time user got the
    returning-user greeting and was never told what Mesiri is. The handler
    stays synchronous -- the caller does the inbound_messages lookup (see
    runtime/first_message_query.py) and passes the answer in."""
    handler = _handler(FakeWorkflowInstanceRepository())

    first = handler.handle_greeting_trigger(_message("hi"), is_first_message=True)
    returning = handler.handle_greeting_trigger(_message("hi"), is_first_message=False)

    assert first is not None and returning is not None
    assert "I'm Mesiri" in first.text
    assert "I'm Mesiri" not in returning.text
    # Same tappable menu either way -- only the copy above it differs.
    assert first.list_rows == returning.list_rows == CATEGORY_ROWS


def test_greeting_trigger_defaults_to_the_returning_user_copy():
    """False is the safe default: a failed lookup costs a newcomer one
    paragraph, where the opposite error re-introduces Mesiri to a
    months-old user on every "hi"."""
    handler = _handler(FakeWorkflowInstanceRepository())
    spec = handler.handle_greeting_trigger(_message("hi"))
    assert spec is not None
    assert "I'm Mesiri" not in spec.text


async def test_slow_path_does_not_read_a_site_name_as_yes():
    """Request [38]: with a site question and an expense Yes/No open together,
    the reply "Green Villa" was read as the expense confirmation and recorded
    it. A model-labelled CONFIRM only counts when the words are a yes."""
    repo = FakeWorkflowInstanceRepository()
    repo.seed(_awaiting_state(), version=0)
    classifier = FakeInteractionClassifier()
    classifier.next_response = InteractionSpecV2(
        correlation_id="c1",
        segments=[InteractionSegment(intent=InteractionIntent.CONFIRM, segment_text="Green Villa")],
    )
    handler = _handler(repo, classifier=classifier)

    handled = await handler.handle_slow_path(USR, _message("Green Villa"), "Green Villa", None)

    assert handled is None  # a fresh message, not an answer to the open question
    assert repo._rows[WF][0].phase is WorkflowPhase.AWAITING_CONFIRMATION  # nothing recorded


async def test_slow_path_still_confirms_a_real_yes_with_a_correction():
    repo = FakeWorkflowInstanceRepository()
    repo.seed(_awaiting_state(), version=0)
    classifier = FakeInteractionClassifier()
    classifier.next_response = InteractionSpecV2(
        correlation_id="c1",
        segments=[InteractionSegment(intent=InteractionIntent.CONFIRM, segment_text="go ahead")],
    )
    handler = _handler(repo, classifier=classifier)

    handled = await handler.handle_slow_path(USR, _message("go ahead"), "go ahead", None)

    assert handled is not None
    assert handled.unrelated_text is None
    assert handled.result.status is WorkflowResumeStatus.CONFIRMED
