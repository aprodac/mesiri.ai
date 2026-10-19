"""handle_slot_answer's LLM second pass -- exercised against a real
WorkflowRuntime and the real, unchanged match_slot_answer.

Reproduces the reported bug: "Which work is this about? 1. plastering... 2.
This is new work", answered "New cause it's 3rd floor". The deterministic
matcher (workflows/slots.py) can't resolve that (not a substring of either
label), so the graph re-asks. Proves the LLM classifier is consulted only
then, and that feeding its resolved candidate's exact label back through
provide_input lets the real match_slot_answer resolve it on a second,
same-turn pass -- no "I couldn't tell which one you meant" shown to the user, and no
change needed to workflows/slots.py or any workflow node.
"""

from __future__ import annotations

from datetime import UTC, datetime

from interactions.handler import InteractionHandler
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from mesiri_contracts.assistant.v2.workflow_state import WorkflowStateV2
from mesiri_contracts.context.enums import WorkflowPhase
from workflows.fakes import FakeWorkflowInstanceRepository
from workflows.runtime import WorkflowRunStatus, WorkflowRuntime
from workflows.slots import SlotCandidate, match_slot_answer, slot_options

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
WF = "11111111-1111-4111-8111-1111111111aa"

_CANDIDATES = [
    SlotCandidate(value="act-1", label="plastering — started plastering on 2nd floor"),
    SlotCandidate(value="new_activity", label="This is new work"),
]


class _PickerGraph:
    """Minimal stand-in for site_update's resolve_target: asks a single-
    choice slot and matches the reply with the real, unmodified
    match_slot_answer -- so a passing test proves the LLM's resolved label
    is something the deterministic matcher genuinely accepts, not a
    special-cased bypass."""

    def __init__(self) -> None:
        self.invocations = 0

    async def ainvoke(self, state: dict) -> dict:
        self.invocations += 1
        answer_text = state["collected_fields"].get("_slot_answer_text")
        matched = match_slot_answer(answer_text, _CANDIDATES) if answer_text else None
        if matched is None:
            return {
                "awaiting_slot": "activity_target",
                "pending_prompt": "I couldn't tell which one you meant.\n\nWhich work is this about?",
                "awaiting_slot_options": slot_options(_CANDIDATES),
                "collected_fields": state["collected_fields"],
            }
        draft = DraftActionV2(
            draft_id="d1",
            correlation_id="c1",
            workflow_instance_id=WF,
            action_type=DraftActionType.ADD_PROGRESS_UPDATE,
            organization_id=ORG,
            user_id=USR,
            fields={"activity_id": matched},
        )
        return {
            "draft_action": draft,
            "pending_prompt": "Confirm?",
            "collected_fields": {**state["collected_fields"], "activity_id": matched},
        }


class _FakeSlotAnswerClassifier:
    def __init__(self, response_value: str | None) -> None:
        self.response_value = response_value
        self.calls: list[tuple[str, tuple[SlotCandidate, ...], str]] = []

    async def classify(self, reply_text, candidates, correlation_id):
        self.calls.append((reply_text, candidates, correlation_id))
        return self.response_value


class _ExplodingClassifier:
    async def classify(self, reply_text, candidates, correlation_id):
        raise AssertionError("classifier should not be called when the deterministic pass already resolved it")


def _runtime_with_open_question() -> WorkflowRuntime:
    from workflows import WorkflowRegistry

    repo = FakeWorkflowInstanceRepository()
    repo.seed(
        WorkflowStateV2(
            workflow_instance_id=WF,
            workflow_key=WorkflowKey.SITE_UPDATE,
            correlation_id="cor_old",
            organization_id=ORG,
            user_id=USR,
            phase=WorkflowPhase.COLLECTING_FIELDS,
            collected_fields={"narrative": "180 sqm done"},
            awaiting_slot="activity_target",
            pending_prompt="Which work is this about?",
        ),
        version=0,
    )
    registry = WorkflowRegistry()
    registry._compiled[WorkflowKey.SITE_UPDATE] = _PickerGraph()
    return WorkflowRuntime(registry=registry, repo=repo)


def _text(body: str) -> NormalizedMessage:
    return NormalizedMessage(
        message_id="wamid.1",
        correlation_id="cor_reply_1",
        sender=SenderInfo(wa_id="919000000000", profile_name="Engineer"),
        modality=InputModality.TEXT,
        text=body,
        timestamp=datetime(2026, 7, 29, 17, 15, tzinfo=UTC),
    )


async def test_llm_resolves_a_reply_the_deterministic_matcher_missed():
    runtime = _runtime_with_open_question()
    classifier = _FakeSlotAnswerClassifier(response_value="new_activity")
    handler = InteractionHandler(workflow_runtime=runtime, slot_answer_classifier=classifier)

    handled = await handler.handle_slot_answer(USR, _text("New cause it's 3rd floor"))

    assert handled is not None
    assert handled.result.status is WorkflowRunStatus.STARTED
    assert handled.result.draft_action.fields["activity_id"] == "new_activity"
    # Deterministic miss, then the LLM-resolved label retried -- two passes.
    assert runtime._registry.get_graph(WorkflowKey.SITE_UPDATE).invocations == 2
    assert len(classifier.calls) == 1
    reply_text, candidates, correlation_id = classifier.calls[0]
    assert reply_text == "New cause it's 3rd floor"
    assert {c.value for c in candidates} == {"act-1", "new_activity"}
    assert correlation_id == "cor_reply_1"


async def test_llm_not_consulted_when_deterministic_match_already_resolves():
    """A plain number never reaches the classifier -- cost principle
    preserved (a plain reply costs no tokens)."""
    runtime = _runtime_with_open_question()
    handler = InteractionHandler(workflow_runtime=runtime, slot_answer_classifier=_ExplodingClassifier())

    handled = await handler.handle_slot_answer(USR, _text("1"))

    assert handled is not None
    assert handled.result.status is WorkflowRunStatus.STARTED
    assert handled.result.draft_action.fields["activity_id"] == "act-1"


async def test_llm_returning_none_falls_back_to_the_original_reask():
    runtime = _runtime_with_open_question()
    classifier = _FakeSlotAnswerClassifier(response_value=None)
    handler = InteractionHandler(workflow_runtime=runtime, slot_answer_classifier=classifier)

    handled = await handler.handle_slot_answer(USR, _text("something totally unrelated"))

    assert handled is not None
    assert handled.result.status is WorkflowRunStatus.AWAITING_INPUT
    assert "I couldn't tell which one you meant" in handled.result.pending_prompt
    assert len(classifier.calls) == 1


async def test_without_a_classifier_wired_behavior_is_unchanged():
    runtime = _runtime_with_open_question()
    handler = InteractionHandler(workflow_runtime=runtime)  # no slot_answer_classifier

    handled = await handler.handle_slot_answer(USR, _text("hmm 3rd"))

    assert handled is not None
    assert handled.result.status is WorkflowRunStatus.AWAITING_INPUT
    assert "I couldn't tell which one you meant" in handled.result.pending_prompt
