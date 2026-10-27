"""ARCH-04: an entry finished by answering the workflow's own question waits on
Save / Cancel like every agent entry, never "Saved" with Undo.

Since WA-77 nothing counts until Save is tapped; a draft finished by a slot
answer ("which activity?", "which worker?") used to be sent with the old Undo
button, so there was no Save to tap and the entry stayed off the report."""

from __future__ import annotations

import functools
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.application.results.execution_result import ExecutionStatus
from mesiri_contracts.assistant.draft_action import DraftActionType
from runtime import message_journey as mj
from runtime.agent import cards as c
from runtime.agent import save_button as sb
from runtime.reply_composer import UNDO_ROW
from workflows.runtime import WorkflowRunResult, WorkflowRunStatus

from .test_agent_routing import _build, _message
from .test_request116_saved_line import _Redis

ROW_ID = uuid.uuid4()


def _started() -> WorkflowRunResult:
    """A resumed run whose draft is ready (only its status is read here)."""
    run = object.__new__(WorkflowRunResult)
    object.__setattr__(run, "status", WorkflowRunStatus.STARTED)
    return run


def _handled(action_type: DraftActionType, *, row_id=ROW_ID):  # type: ignore[no-untyped-def]
    draft = SimpleNamespace(action_type=action_type, site_id=None, fields={}, organization_id=None)
    return SimpleNamespace(
        result=SimpleNamespace(confirmed_action=SimpleNamespace(draft_action=draft), workflow_instance_id=None),
        reply_text="✅ Saved:\n• Plastering 50 sq ft",
        execution_result=SimpleNamespace(status=ExecutionStatus.SUCCEEDED, material_row_id=str(row_id)),
        saved_draft=True,
        receipt_coro=None,
        next_segment_reply=None,
        project_id=None,
        site_id=None,
    )


def _wire(monkeypatch, saved, store=None):  # type: ignore[no-untyped-def]
    built = mj.build_message_handlers

    @functools.wraps(built)
    def with_cards(**kw):
        return built(**kw, cards=store)

    monkeypatch.setattr(mj, "build_message_handlers", with_cards)
    on_normalized, deps, _ = _build(monkeypatch, mode="agent", provider=FakeToolCallingProvider(["unused"]))
    handler = deps["interaction_handler"]
    handler.handle_slot_answer.return_value = SimpleNamespace(
        closed_question=False, result=_started(), project_id=None, site_id=None
    )
    handler.save_now = AsyncMock(return_value=saved)
    deps["plan_store"].get_active.return_value = None
    return on_normalized, deps


def _sent_ids(deps) -> list[str]:  # type: ignore[no-untyped-def]
    sender = deps["sender"]
    for call in (*sender.send_button.await_args_list, *sender.send_list.await_args_list):
        rows = call.kwargs.get("buttons") or call.kwargs.get("rows") or ()
        if rows:
            return [r.id for r in rows]
    return []


async def test_a_slot_answer_that_finishes_a_draft_gets_save_and_cancel(monkeypatch):
    on_normalized, deps = _wire(monkeypatch, _handled(DraftActionType.CREATE_ACTIVITY))
    await on_normalized(_message("the plastering one"), {})
    ids = _sent_ids(deps)
    facts = [("activity", ROW_ID)]
    assert ids[:2] == [sb.tap_id(sb.SAVE, facts), sb.tap_id(sb.CANCEL, facts)]
    assert UNDO_ROW.id not in ids
    assert sb.TO_SAVE_HEADER in str(deps["sender"].mock_calls)


async def test_the_card_is_remembered_so_the_save_tap_names_what_it_saved(monkeypatch):
    store = c.CardStore(_Redis())
    on_normalized, deps = _wire(monkeypatch, _handled(DraftActionType.CREATE_ACTIVITY), store)
    await on_normalized(_message("the plastering one"), {})
    (card,) = [c.Card.from_json(v) for v in store._redis.data.values()]  # type: ignore[attr-defined]
    assert card is not None and card.state == c.OPEN
    assert [i.fact for i in card.items] == [("activity", ROW_ID)]
    assert card.items[0].tool == ""  # update_pending_card refuses it: nothing withdrawn


async def test_a_draft_the_review_log_does_not_cover_keeps_its_old_reply(monkeypatch):
    on_normalized, deps = _wire(monkeypatch, _handled(DraftActionType.ADD_PROGRESS_UPDATE))
    await on_normalized(_message("the plastering one"), {})
    ids = _sent_ids(deps)
    assert not any(i.startswith(sb.TAP_PREFIX) for i in ids)
