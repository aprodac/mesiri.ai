"""No open question can trap a worker (request [51]).

Adarsh (17:29-17:34, 17 Oct) answered a worker-promotion question with
"I have a work on new site", "Today 5 workers came", "Hi", "hey mesii" and got
"Sorry, I didn't catch that. Reply with the names of anyone who is a different
person, or none." every time, because every message was routed into the open
question and the question re-asked forever. These tests run the real promotion
graph through the real runtime and handler.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from interactions.handler import InteractionHandler
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from mesiri_contracts.assistant.v2.workflow_state import WorkflowStateV2
from mesiri_contracts.context.enums import WorkflowPhase
from runtime.inbound_journey import render_workflow_run_reply_spec
from workflows import WorkflowRegistry
from workflows.fakes import FakeWorkflowInstanceRepository
from workflows.runtime import WorkflowRunStatus, WorkflowRuntime
from workflows.slots import looks_unrelated

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"

REGISTER = [
    {
        "worker_id": "w1",
        "name": "Rajesh Kumar",
        "trade": "mason",
        "contractor": None,
        "since": "2026-10-02",
    }
]


def _text(text: str) -> NormalizedMessage:
    return NormalizedMessage(
        message_id=f"wamid.{abs(hash(text))}",
        correlation_id=f"cor_{abs(hash(text))}",
        sender=SenderInfo(wa_id="919000000000", profile_name="Adarsh"),
        modality=InputModality.TEXT,
        text=text,
        timestamp=datetime.now(UTC),
    )


def _tap(row_id: str, title: str) -> NormalizedMessage:
    return _text(title).model_copy(
        update={"modality": InputModality.INTERACTIVE, "metadata": {"interactive_reply_id": row_id}}
    )


def _setup(*, workers, slot, prompt="?", register=REGISTER, extra=None):
    repo = FakeWorkflowInstanceRepository()
    repo.seed(
        WorkflowStateV2(
            workflow_instance_id="wf_promo",
            workflow_key=WorkflowKey.WORKER_PROMOTION,
            correlation_id="cor_old",
            organization_id=ORG,
            user_id=USR,
            phase=WorkflowPhase.COLLECTING_FIELDS,
            collected_fields={
                "promotable_workers": workers,
                "_register": register,
                **(extra or {}),
            },
            awaiting_slot=slot,
            pending_prompt=prompt,
        ),
        version=0,
    )
    runtime = WorkflowRuntime(registry=WorkflowRegistry(), repo=repo)
    return runtime, InteractionHandler(workflow_runtime=runtime)


RAJESH = {"name": "Rajesh", "trade": "mason"}


async def _open_duplicate_question():
    """The offer answered "all": Rajesh looks like Rajesh Kumar."""
    runtime, handler = _setup(workers=[RAJESH], slot="promotion_choice")
    handled = await handler.handle_slot_answer(USR, _tap("promo_all", "Add"))
    assert handled is not None
    assert handled.result.status is WorkflowRunStatus.AWAITING_INPUT
    return runtime, handler, handled


async def test_the_question_names_who_and_what_it_matched_with_buttons():
    _, _, handled = await _open_duplicate_question()

    prompt = handled.result.pending_prompt
    assert "Quick check so your worker list stays clean" in prompt
    assert "*Rajesh* looks like *Rajesh Kumar* who's already in your list (mason, since 2 Oct)" in prompt
    spec = render_workflow_run_reply_spec(handled.result)
    assert [b.title for b in spec.buttons] == ["Same person", "New person", "Skip"]
    assert [b.id for b in spec.buttons] == ["dup_same", "dup_new", "dup_skip"]


@pytest.mark.parametrize(
    "message",
    ["I have a work on new site", "Today 5 workers came", "Hi", "hey mesii"],
)
async def test_adarshs_messages_close_the_question_and_are_handled_normally(message):
    runtime, handler, _ = await _open_duplicate_question()

    handled = await handler.handle_slot_answer(USR, _text(message))

    assert handled is not None and handled.closed_question
    assert handled.result.status is WorkflowRunStatus.COMPLETED
    assert "I'll keep *Rajesh* as a separate name for now" in handled.reply_text
    assert "Worker Register" in handled.reply_text
    assert "didn't catch" not in handled.reply_text
    # Nothing is left open: the next message is not read as an answer.
    assert await runtime.get_awaiting_input(USR) is None
    assert await handler.handle_slot_answer(USR, _text(message)) is None


async def test_nobody_is_promoted_when_the_question_is_closed():
    _, handler, _ = await _open_duplicate_question()

    handled = await handler.handle_slot_answer(USR, _text("Today 5 workers came"))

    assert not (handled.result.collected_fields or {}).get("workers_to_create")


async def test_a_short_unclear_reply_gets_exactly_one_friendly_re_ask_then_closes():
    runtime, handler, _ = await _open_duplicate_question()

    first = await handler.handle_slot_answer(USR, _text("hmm"))
    assert first is not None and not first.closed_question
    assert first.result.status is WorkflowRunStatus.AWAITING_INPUT
    assert first.result.pending_prompt.startswith("No worries. Just tap one:")
    assert "*Rajesh*" in first.result.pending_prompt
    assert "*Rajesh Kumar*" in first.result.pending_prompt
    assert len(render_workflow_run_reply_spec(first.result).buttons) == 3

    second = await handler.handle_slot_answer(USR, _text("maybe"))
    assert second is not None and second.closed_question
    assert await runtime.get_awaiting_input(USR) is None


@pytest.mark.parametrize(
    ("row_id", "title", "created"),
    [
        ("dup_same", "Same person", False),
        ("dup_new", "New person", True),
        ("dup_skip", "Skip", False),
        ("dup_new", "പുതിയ ആൾ", True),  # a translated title: the id decides
    ],
)
async def test_the_three_taps(row_id, title, created):
    _, handler, _ = await _open_duplicate_question()

    handled = await handler.handle_slot_answer(USR, _tap(row_id, title))

    assert handled is not None and not handled.closed_question
    assert handled.result.status is WorkflowRunStatus.COMPLETED
    queued = (handled.result.collected_fields or {}).get("workers_to_create") or []
    assert [w["name"] for w in queued] == (["Rajesh"] if created else [])


@pytest.mark.parametrize(
    ("typed", "created"),
    [
        ("same", False),
        ("same person", False),
        ("yes same", False),
        ("new", True),
        ("different", True),
        ("no", True),
        ("none", False),
        ("nobody", False),
        ("skip", False),
        ("cancel", False),
        ("1", False),
        ("2", True),
    ],
)
async def test_typed_equivalents(typed, created):
    _, handler, _ = await _open_duplicate_question()

    handled = await handler.handle_slot_answer(USR, _text(typed))

    assert handled is not None and not handled.closed_question
    queued = (handled.result.collected_fields or {}).get("workers_to_create") or []
    assert [w["name"] for w in queued] == (["Rajesh"] if created else [])


async def test_the_offer_itself_cannot_trap_either():
    runtime, handler = _setup(workers=[RAJESH, {"name": "Anil"}], slot="promotion_choice")

    handled = await handler.handle_slot_answer(USR, _text("I have a work on new site"))

    assert handled is not None and handled.closed_question
    assert "stay as temporary workers" in handled.reply_text
    assert await runtime.get_awaiting_input(USR) is None


async def test_a_workflow_that_needs_its_answer_is_set_aside_not_left_open():
    """The same escape in the other slot workflows (labour_update, site_update,
    expense_capture, petty_cash, transfer): the re-ask they build starts with
    the shared retry prefix, so a second miss -- or a plain sentence -- cancels
    the question instead of repeating it."""
    from workflows.slots import RETRY_PREFIX

    class _Graph:
        async def ainvoke(self, state):
            return {
                "awaiting_slot": "account",
                "pending_prompt": f"{RETRY_PREFIX} Which account?",
                "awaiting_slot_options": [
                    {"value": "a", "label": "Site Cash"},
                    {"value": "b", "label": "Own Pocket"},
                ],
                "collected_fields": state["collected_fields"],
            }

    class _Registry:
        def get_graph(self, key):
            return _Graph()

    repo = FakeWorkflowInstanceRepository()
    repo.seed(
        WorkflowStateV2(
            workflow_instance_id="wf_exp",
            workflow_key=WorkflowKey.EXPENSE_SUBMIT,
            correlation_id="cor_old",
            organization_id=ORG,
            user_id=USR,
            phase=WorkflowPhase.COLLECTING_FIELDS,
            collected_fields={},
            awaiting_slot="account",
            pending_prompt="Which account?",
        ),
        version=0,
    )
    runtime = WorkflowRuntime(registry=_Registry(), repo=repo)
    handler = InteractionHandler(workflow_runtime=runtime)

    sentence = await handler.handle_slot_answer(USR, _text("Today 5 workers came"))

    assert sentence is not None and sentence.closed_question
    assert "set that question aside" in sentence.reply_text
    assert await runtime.get_awaiting_input(USR) is None


async def test_a_short_miss_on_a_plain_question_gets_one_re_ask_with_its_options():
    from workflows.slots import RETRY_PREFIX

    class _Graph:
        async def ainvoke(self, state):
            return {
                "awaiting_slot": "account",
                "pending_prompt": f"{RETRY_PREFIX} Which account?",
                "awaiting_slot_options": [
                    {"value": "a", "label": "Site Cash"},
                    {"value": "b", "label": "Own Pocket"},
                ],
                "collected_fields": state["collected_fields"],
            }

    class _Registry:
        def get_graph(self, key):
            return _Graph()

    repo = FakeWorkflowInstanceRepository()
    repo.seed(
        WorkflowStateV2(
            workflow_instance_id="wf_exp",
            workflow_key=WorkflowKey.EXPENSE_SUBMIT,
            correlation_id="cor_old",
            organization_id=ORG,
            user_id=USR,
            phase=WorkflowPhase.COLLECTING_FIELDS,
            collected_fields={},
            awaiting_slot="account",
            pending_prompt="Which account?",
        ),
        version=0,
    )
    runtime = WorkflowRuntime(registry=_Registry(), repo=repo)
    handler = InteractionHandler(workflow_runtime=runtime)

    first = await handler.handle_slot_answer(USR, _text("cash?"))  # a question: closes
    assert first is not None and first.closed_question

    repo2 = FakeWorkflowInstanceRepository()
    repo2.seed(
        WorkflowStateV2(
            workflow_instance_id="wf_exp2",
            workflow_key=WorkflowKey.EXPENSE_SUBMIT,
            correlation_id="cor_old",
            organization_id=ORG,
            user_id=USR,
            phase=WorkflowPhase.COLLECTING_FIELDS,
            collected_fields={},
            awaiting_slot="account",
            pending_prompt="Which account?",
        ),
        version=0,
    )
    handler2 = InteractionHandler(workflow_runtime=WorkflowRuntime(registry=_Registry(), repo=repo2))
    one = await handler2.handle_slot_answer(USR, _text("cashh"))
    assert one is not None and not one.closed_question
    assert one.result.status is WorkflowRunStatus.AWAITING_INPUT
    two = await handler2.handle_slot_answer(USR, _text("cashhh"))
    assert two is not None and two.closed_question


@pytest.mark.parametrize(
    ("text", "unrelated"),
    [
        ("I have a work on new site", True),
        ("Today 5 workers came", True),
        ("Hi", True),
        ("hey mesii", True),
        ("which one?", True),
        ("hello", True),
        ("Rajeh", False),
        ("same", False),
        ("2", False),
        ("ok", False),
        ("not sure", False),
        ("", False),
    ],
)
def test_what_counts_as_plainly_something_else(text, unrelated):
    assert looks_unrelated(text) is unrelated


async def test_an_open_question_expires_after_two_hours_in_the_database_query():
    """The Postgres repository cancels questions left unanswered for
    CONFIRMATION_TTL_HOURS (the same rule as the YES/NO expiry of request
    [43]). It cannot run here without Postgres; assert the rule is wired."""
    import inspect

    from backend.postgres import workflow_instance as repo

    source = inspect.getsource(repo.PostgresWorkflowInstanceRepository.get_awaiting_input)
    assert "_expire_stale_questions" in source
    sweep = inspect.getsource(repo.PostgresWorkflowInstanceRepository._expire_stale_questions)
    assert "phase = 'collecting_fields'" in sweep
    assert "CONFIRMATION_TTL_HOURS" in sweep
    assert repo.CONFIRMATION_TTL_HOURS == 2
    assert timedelta(hours=repo.CONFIRMATION_TTL_HOURS) == timedelta(hours=2)
