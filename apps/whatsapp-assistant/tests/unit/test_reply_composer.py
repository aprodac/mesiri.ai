"""Request [45]: one reply per site message, in the form that fits.

The composer's choice of form and priority, the reaction + single send for a
saved note, taps and typed answers meaning the same thing, the setup question
waiting for a light message, and the text fallback when an interactive send
fails.
"""

from __future__ import annotations

import datetime as dt
import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

import runtime.message_journey as mj
from channel.replies import TEAM_PHOTO_BUTTONS, ListRow, ReplySpec
from interactions.handler import InteractionHandled
from interactions.offered_choices import OfferedChoicesStore
from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from runtime.agent import save_button as sb
from runtime.reply_composer import (
    PHOTO_ROW,
    QUESTION,
    SETUP_OFFER,
    SETUP_QUESTION,
    TEAM_PHOTO,
    UNDO_ROW,
    Offer,
    compose,
    pick_form,
    resolve_choice,
)
from runtime.reply_dispatch import send_reply_spec
from workflows.runtime import WorkflowResumeResult, WorkflowResumeStatus
from workflows.worker_promotion.wording import NONE_ADDED

ORG = uuid.uuid4()
USR = str(uuid.uuid4())
REPORT = str(uuid.uuid4())
NOTE = "Shuttering done for first floor slab. 8 masons and 3 helpers today. Received 50 bags cement from Ramco."
SAVED = "✅ Saved:\n• Shuttering done, first floor slab\n• 8 masons, 3 helpers\n• 50 bags cement from Ramco"
#: The Save / Cancel ids of a card for the saved attendance (REPORT).
_SAVE_IDS = [sb.tap_id(a, [("labour_report", uuid.UUID(REPORT))]) for a in (sb.SAVE, sb.CANCEL)]


def _rows(n: int) -> list[ListRow]:
    return [ListRow(f"r{i}", f"Option {i}") for i in range(1, n + 1)]


# -- form picking ----------------------------------------------------------------


def test_no_choices_is_plain_text():
    spec = pick_form("Done.", [])
    assert spec == ReplySpec(text="Done.")


@pytest.mark.parametrize("count", [1, 2, 3])
def test_one_to_three_choices_are_buttons(count):
    spec = pick_form("Which?", _rows(count))
    assert [b.id for b in spec.buttons] == [f"r{i}" for i in range(1, count + 1)]
    assert spec.list_rows is None


@pytest.mark.parametrize("count", [4, 10])
def test_four_to_ten_choices_are_a_list(count):
    spec = pick_form("Which site?", _rows(count))
    assert len(spec.list_rows) == count
    assert spec.buttons is None
    assert spec.list_button_label


def test_more_than_ten_is_numbered_text():
    spec = pick_form("Which material?", _rows(11))
    assert spec.buttons is None and spec.list_rows is None
    assert "1. Option 1" in spec.text and "11. Option 11" in spec.text


def test_button_titles_and_body_respect_whatsapp_limits():
    spec = pick_form("x" * 2000, [ListRow("a", "y" * 40)])
    assert len(spec.buttons[0].title) <= 20
    assert len(spec.text) <= 1024


# -- priority --------------------------------------------------------------------

PHOTO = Offer(TEAM_PHOTO, spec=ReplySpec(text="photo?", buttons=TEAM_PHOTO_BUTTONS))
PROMOTION = Offer(QUESTION, text="Add Ravi to your workers?")
SETUP = Offer(SETUP_OFFER, spec=ReplySpec(text="Add a site?", buttons=(ListRow("a", "Add a Site"),)))
DAILY = Offer(SETUP_QUESTION, spec=ReplySpec(text="Report by 9 pm?", buttons=(ListRow("t", "8 pm"),)))


def test_a_saved_note_with_the_photo_offer_is_one_message_with_photo_and_undo():
    spec = compose(SAVED, [PHOTO], saved=True)
    assert [b.id for b in spec.buttons] == [PHOTO_ROW.id, UNDO_ROW.id]
    assert spec.text.startswith(SAVED)
    assert "Attendance recorded" not in spec.text


def test_when_the_photo_was_already_asked_today_only_undo_remains():
    spec = compose(SAVED, [], saved=True)
    assert [b.id for b in spec.buttons] == [UNDO_ROW.id]


def test_the_undo_button_replaces_the_typed_undo_hint():
    # B-6 (live test 19 Oct): "Wrong? Reply UNDO." sat right above the Undo button.
    main = "✅ Saved: 12 masons, 5 bags cement.\n\nWrong? Reply UNDO."
    spec = compose(main, [], saved=True)
    assert spec.text == "✅ Saved: 12 masons, 5 bags cement."
    assert [b.id for b in spec.buttons] == [UNDO_ROW.id]
    malayalam = "✅ സേവ് ചെയ്തു.\nതെറ്റാണോ? UNDO എന്ന് മറുപടി നൽകൂ."
    assert compose(malayalam, [PHOTO], saved=True).text.startswith("✅ സേവ് ചെയ്തു.\n\n📷")


def test_without_the_undo_button_the_hint_stays():
    main = "✅ Saved.\n\nWrong? Reply UNDO."
    question = Offer(QUESTION, text="Make them permanent?")
    assert "Reply UNDO" in compose(main, [question], saved=True).text
    assert compose("Logged UNDO count", [], saved=False).text == "Logged UNDO count"


def test_a_reply_that_saved_nothing_has_no_undo():
    assert compose("Hello!", [], saved=False) == ReplySpec(text="Hello!")


def test_the_promotion_question_beats_the_photo():
    spec = compose(SAVED, [PHOTO, PROMOTION], saved=True)
    assert spec.buttons is None
    assert "Add Ravi to your workers?" in spec.text
    assert "photo" not in spec.text.lower()


def test_the_photo_beats_the_setup_question_and_a_save_drops_the_setup_question():
    both = compose("Hi", [DAILY, PHOTO], saved=False)
    assert PHOTO_ROW.id in [b.id for b in both.buttons]
    after_save = compose(SAVED, [DAILY], saved=True)
    assert "9 pm" not in after_save.text
    assert [b.id for b in after_save.buttons] == [UNDO_ROW.id]


def test_a_setup_question_alone_keeps_its_buttons_after_a_light_message():
    spec = compose("Hello!", [DAILY], saved=False)
    assert [b.title for b in spec.buttons] == ["8 pm"]
    assert "Report by 9 pm?" in spec.text


def test_the_project_setup_offer_beats_the_photo():
    spec = compose("✅ Site created.", [PHOTO, SETUP], saved=False)
    assert [b.title for b in spec.buttons] == ["Add a Site"]


# -- typed answers mean the tap ---------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("undo", UNDO_ROW.id),
        ("Undo!", UNDO_ROW.id),
        ("photo", PHOTO_ROW.id),
        ("add team photo", PHOTO_ROW.id),
        ("📷 Add team photo", PHOTO_ROW.id),
        ("1", PHOTO_ROW.id),
        ("2", UNDO_ROW.id),
    ],
)
def test_typed_words_titles_and_numbers_resolve_like_taps(typed, expected):
    assert resolve_choice(typed, [PHOTO_ROW, UNDO_ROW]).id == expected


@pytest.mark.parametrize("typed", ["8 pm", "3", "hello", ""])
def test_anything_else_is_not_a_choice(typed):
    assert resolve_choice(typed, [PHOTO_ROW, UNDO_ROW]) is None


def test_a_typed_report_time_is_an_option_title():
    times = [ListRow("setup_q:time:19:00", "7 pm"), ListRow("setup_q:time:20:00", "8 pm")]
    assert resolve_choice("8 pm", times).id == "setup_q:time:20:00"


# -- interactive failure falls back to numbered text ---------------------------------


async def test_a_failed_button_send_falls_back_to_numbered_text():
    sent = []

    async def send_text(wa_id, body):
        sent.append(body)
        return "wamid"

    spec = compose(SAVED, [PHOTO], saved=True)
    await send_reply_spec(spec, "wa", send_text=send_text, send_button=AsyncMock(return_value=False))
    assert len(sent) == 1
    assert "1. 📷 Add team photo" in sent[0] and "2. ↩️ Undo" in sent[0]


async def test_a_failed_list_send_falls_back_to_numbered_text():
    sent = []

    async def send_text(wa_id, body):
        sent.append(body)

    await send_reply_spec(
        pick_form("Which site?", _rows(5)),
        "wa",
        send_text=send_text,
        send_list=AsyncMock(return_value=False),
    )
    assert "5. Option 5" in sent[0]


# -- the journey: one reaction, one message ------------------------------------------


class _Redis:
    def __init__(self):
        self.data = {}

    async def set_json(self, key, value, *, ttl_seconds=None):
        self.data[key] = value

    async def get_json(self, key):
        return self.data.get(key)


def _message(text=NOTE, modality=InputModality.TEXT, metadata=None):
    return NormalizedMessage(
        message_id="wamid.in.1",
        sender=SenderInfo(wa_id="919876543210", profile_name="Ravi"),
        timestamp=dt.datetime(2026, 10, 19, 6, tzinfo=dt.UTC),
        modality=modality,
        text=text,
        metadata=metadata or {},
    )


def _tap(row_id, title):
    return _message(
        title,
        InputModality.INTERACTIVE,
        {"interactive_reply_id": row_id, "interactive_reply_type": "button_reply"},
    )


def _saved_attendance(*, saved_draft=True):
    draft = DraftActionV2(
        draft_id="d1",
        correlation_id="c1",
        workflow_instance_id="wf1",
        action_type=DraftActionType.RECORD_LABOUR_ATTENDANCE,
        organization_id=str(ORG),
        user_id=USR,
        fields={"lines": []},
    )
    return InteractionHandled(
        result=WorkflowResumeResult(
            status=WorkflowResumeStatus.CONFIRMED,
            workflow_instance_id="wf1",
            correlation_id="c1",
            confirmed_action=ConfirmedActionV2(
                confirmed_action_id="ca1",
                workflow_instance_id="wf1",
                correlation_id="c1",
                draft_action=draft,
                confirmed_by_user_id=USR,
            ),
        ),
        reply_text=SAVED,
        execution_result=ExecutionResult(
            status=ExecutionStatus.SUCCEEDED, idempotency_key="k", material_row_id=REPORT
        ),
        saved_draft=saved_draft,
    )


def _build(monkeypatch, *, redis=None, role="SUPERVISOR", **more):
    async def fake_resolve(_reader, wa_id):
        return SimpleNamespace(
            organization_id=ORG,
            org_active=True,
            user_id=USR,
            full_name="Ravi",
            role=role,
            org_name="Acme",
            projects=[],
            sites=[],
        )

    monkeypatch.setattr(mj, "resolve_sender", fake_resolve)
    params = inspect.signature(mj.build_message_handlers).parameters
    deps = {n: AsyncMock() for n, p in params.items() if p.default is inspect.Parameter.empty}
    handler = deps["interaction_handler"]
    handler.handle_fast_path.return_value = None
    handler.handle_slot_answer.return_value = None
    for sync_name in (
        "handle_category_tap",
        "handle_material_direction_tap",
        "handle_image_purpose_tap",
        "handle_greeting_trigger",
        "handle_whoami_trigger",
    ):
        setattr(handler, sync_name, MagicMock(return_value=None))
    handler.undo_latest_draft.return_value = "Done. I've removed the work update."
    deps["org_settings_query"].enabled_modules.return_value = ["dpr", "labour"]
    deps["org_settings_query"].get.return_value = "off"
    deps["category_hint_store"].pop_hint.return_value = None
    deps["plan_store"].get_plan.return_value = None
    deps["team_photo_hint_store"].claim_daily_offer.return_value = True
    deps["team_photo_hint_store"].pop_held.return_value = None
    deps["user_language_store"] = None
    deps["memory_loader"].load.return_value = SimpleNamespace(
        recent_turns=(), has_pending_confirmation=False
    )
    monkeypatch.setattr(mj, "try_hold_new_image_for_purpose_picker", AsyncMock(return_value=None))
    monkeypatch.setattr(mj.workflow_registry, "set_enabled_modules", MagicMock())
    redis = redis or _Redis()
    choices = OfferedChoicesStore(redis)
    setup = SimpleNamespace(after_reply=AsyncMock())
    extra = {
        "offered_choices_store": choices,
        "setup_questions": setup,
        "user_language_store": None,
        **more,
    }
    deps.pop("user_language_store")
    on_normalized, _ = mj.build_message_handlers(**deps, **extra)
    return on_normalized, deps, choices, setup


def _sends(deps):
    sender = deps["sender"]
    return (
        sender.send_text.await_args_list
        + sender.send_button.await_args_list
        + sender.send_list.await_args_list
    )


async def test_a_three_part_note_gets_one_reaction_and_one_message_with_save_and_photo(monkeypatch):
    on_normalized, deps, choices, setup = _build(monkeypatch)
    deps["interaction_handler"].handle_fast_path.return_value = _saved_attendance()

    await on_normalized(_message(), {})

    sender = deps["sender"]
    sender.send_reaction.assert_awaited_once_with("919876543210", "wamid.in.1", "✅")
    assert len(_sends(deps)) == 1
    sender.send_text.assert_not_awaited()
    sent = sender.send_button.await_args.kwargs
    # ARCH-04: a saved-first draft waits on Save / Cancel (WA-35), never Undo.
    assert sent["body"].startswith(sb.TO_SAVE_HEADER)
    assert [b.id for b in sent["buttons"]] == [*_SAVE_IDS, PHOTO_ROW.id]
    # no "Attendance recorded" message, and no setup question on top of a save
    setup.after_reply.assert_not_awaited()
    # the photo hint stays parked so the next photo attaches to today's attendance
    deps["team_photo_hint_store"].set_hint.assert_awaited()
    deps["team_photo_hint_store"].clear.assert_not_awaited()


async def test_the_photo_is_offered_once_a_day_after_that_only_save(monkeypatch):
    on_normalized, deps, _, _ = _build(monkeypatch)
    deps["team_photo_hint_store"].claim_daily_offer.return_value = False
    deps["interaction_handler"].handle_fast_path.return_value = _saved_attendance()

    await on_normalized(_message(), {})

    assert [b.id for b in deps["sender"].send_button.await_args.kwargs["buttons"]] == _SAVE_IDS


async def test_the_promotion_question_comes_in_the_same_message_and_beats_the_photo(monkeypatch):
    on_normalized, deps, _, _ = _build(monkeypatch)
    deps["interaction_handler"].handle_fast_path.return_value = _saved_attendance()

    async def promote(handled, runtime, query, actor, wa_id, send_text, send_spec_fn=None):
        await send_text(wa_id, "Add Suresh and Mahesh to your workers?")
        return True

    monkeypatch.setattr("runtime.inbound_journey._maybe_trigger_worker_promotion", promote)

    await on_normalized(_message(), {})

    sender = deps["sender"]
    assert len(_sends(deps)) == 1
    sent = sender.send_button.await_args.kwargs
    assert "Add Suresh and Mahesh to your workers?" in sent["body"]
    assert [b.id for b in sent["buttons"]] == _SAVE_IDS


async def test_undo_tap_runs_the_same_handler_as_typed_undo(monkeypatch):
    on_normalized, deps, choices, _ = _build(monkeypatch)
    for incoming, offered in ((_tap(UNDO_ROW.id, UNDO_ROW.title), True), (_message("undo"), False)):
        await choices.remember(user_id=USR, rows=[PHOTO_ROW, UNDO_ROW]) if offered else None
        deps["interaction_handler"].undo_latest_draft.reset_mock()
        deps["sender"].send_text.reset_mock()
        await on_normalized(incoming, {})
        deps["interaction_handler"].undo_latest_draft.assert_awaited_once()
        deps["sender"].send_text.assert_awaited_once()
        assert "removed" in deps["sender"].send_text.await_args.args[1]


async def test_typed_undo_and_typed_photo_work_when_the_buttons_were_offered(monkeypatch):
    on_normalized, deps, choices, _ = _build(monkeypatch)
    await choices.remember(user_id=USR, rows=[PHOTO_ROW, UNDO_ROW])
    await on_normalized(_message("undo"), {})
    deps["interaction_handler"].undo_latest_draft.assert_awaited_once()

    await choices.remember(user_id=USR, rows=[PHOTO_ROW, UNDO_ROW])
    await on_normalized(_message("photo"), {})
    assert deps["sender"].send_text.await_args.args[1] == "Send the photo now 📷"

    await choices.remember(user_id=USR, rows=[PHOTO_ROW, UNDO_ROW])
    await on_normalized(_message("1"), {})
    assert deps["sender"].send_text.await_args.args[1] == "Send the photo now 📷"


async def test_add_photo_tap_asks_for_the_photo_and_keeps_the_hint(monkeypatch):
    on_normalized, deps, _, _ = _build(monkeypatch)

    await on_normalized(_tap(PHOTO_ROW.id, PHOTO_ROW.title), {})

    assert deps["sender"].send_text.await_args.args[1] == "Send the photo now 📷"
    deps["team_photo_hint_store"].clear.assert_not_awaited()


async def test_a_typed_report_time_is_not_taken_for_a_choice(monkeypatch):
    on_normalized, deps, choices, _ = _build(monkeypatch)
    await choices.remember(user_id=USR, rows=[PHOTO_ROW, UNDO_ROW])
    await on_normalized(_message("8 pm"), {})
    deps["interaction_handler"].undo_latest_draft.assert_not_awaited()
    assert await choices.take(user_id=USR) == []  # cleared: a stale "2" can't match later


async def test_the_setup_question_waits_for_a_light_message(monkeypatch):
    on_normalized, deps, _, setup = _build(monkeypatch, role="ADMIN")
    deps["interaction_handler"].handle_fast_path.return_value = _saved_attendance()
    await on_normalized(_message(), {})
    setup.after_reply.assert_not_awaited()

    deps["interaction_handler"].handle_fast_path.return_value = None
    await on_normalized(_message("hi"), {})
    setup.after_reply.assert_awaited_once()


async def test_the_reaction_is_best_effort(monkeypatch):
    on_normalized, deps, _, _ = _build(monkeypatch)
    deps["sender"].send_reaction.side_effect = RuntimeError("meta down")
    deps["interaction_handler"].handle_fast_path.return_value = _saved_attendance()

    await on_normalized(_message(), {})

    assert len(_sends(deps)) == 1


async def test_the_agents_one_reply_carries_the_offers_for_what_it_saved(monkeypatch):
    from runtime.agent.runner import AgentResult
    from runtime.agent.turn import AgentTurnDeps, run_agent_turn

    sent = []

    async def send_agent_reply(reply, wa_id, gateway):
        sent.append((reply, wa_id, gateway))

    runner = SimpleNamespace(
        run=AsyncMock(
            return_value=AgentResult(
                outcome="ok",
                reply=ReplySpec(text=SAVED),
                toolbox=SimpleNamespace(parked=None),
            )
        )
    )
    gateway = SimpleNamespace(handled=[_saved_attendance()], finish=AsyncMock())
    deps = AgentTurnDeps(
        runner=runner,
        make_gateway=lambda msg, language: gateway,
        send_spec=AsyncMock(),
        transcribe=None,
        message_logger=AsyncMock(),
        send_agent_reply=send_agent_reply,
    )
    actor = SimpleNamespace(
        user_id=USR, full_name="Ravi", role="SUPERVISOR", org_name="Acme", projects=[], sites=[],
        organization_id=str(ORG),
    )

    await run_agent_turn(_message(), actor, deps)

    assert len(sent) == 1 and sent[0][0].text == SAVED
    deps.send_spec.assert_not_awaited()
    gateway.finish.assert_awaited_once()


async def test_the_reaction_is_a_cloud_api_reaction_message():
    import json

    import httpx

    from channel.whatsapp.outbound import WhatsAppSender

    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.out"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sender = WhatsAppSender(client=client, access_token="t", phone_number_id="1")
        assert await sender.send_reaction("919876543210", "wamid.in.1", "✅") is True
        assert await sender.send_reaction("919876543210", "") is False
    assert seen[0]["type"] == "reaction"
    assert seen[0]["reaction"] == {"message_id": "wamid.in.1", "emoji": "✅"}


# -- request [47]: the receipt card travels inside the one reply -----------------

PNG = b"\x89PNG-receipt"


def _with_receipt(handled, coro_fn):
    handled.receipt_coro = coro_fn()
    return handled


async def _png():
    return PNG


async def _boom():
    raise RuntimeError("playwright pool died")


async def _slow():
    import asyncio

    await asyncio.sleep(30)
    return PNG


async def test_a_save_first_reply_carries_the_receipt_as_the_image_header(monkeypatch):
    on_normalized, deps, _, _ = _build(monkeypatch)
    deps["interaction_handler"].handle_fast_path.return_value = _with_receipt(_saved_attendance(), _png)

    await on_normalized(_message(), {})

    sender = deps["sender"]
    assert len(_sends(deps)) == 1
    sent = sender.send_button.await_args.kwargs
    assert sent["header_image"] == PNG
    assert [b.id for b in sent["buttons"]] == [*_SAVE_IDS, PHOTO_ROW.id]
    sender.send_image.assert_not_awaited()  # not a second message


async def test_a_reply_without_buttons_sends_the_receipt_right_after_the_text(monkeypatch):
    on_normalized, deps, _, _ = _build(monkeypatch)
    deps["team_photo_hint_store"].claim_daily_offer.return_value = False
    handled = _with_receipt(_saved_attendance(saved_draft=False), _png)
    deps["interaction_handler"].handle_fast_path.return_value = handled

    await on_normalized(_message("yes"), {})

    sender = deps["sender"]
    sender.send_button.assert_not_awaited()
    sender.send_text.assert_awaited_once()
    sender.send_image.assert_awaited_once_with("919876543210", PNG, caption=None, shows=ANY)


async def test_a_failed_render_still_sends_the_reply_once_and_logs_an_error(monkeypatch, caplog):
    on_normalized, deps, _, _ = _build(monkeypatch)
    deps["interaction_handler"].handle_fast_path.return_value = _with_receipt(_saved_attendance(), _boom)

    with caplog.at_level("ERROR"):
        await on_normalized(_message(), {})

    assert len(_sends(deps)) == 1
    assert "header_image" not in deps["sender"].send_button.await_args.kwargs
    deps["sender"].send_image.assert_not_awaited()
    assert any("receipt.render_failed" in r.getMessage() and r.levelname == "ERROR" for r in caplog.records)


async def test_a_slow_render_never_blocks_the_reply(monkeypatch, caplog):
    monkeypatch.setattr(mj, "RECEIPT_TIMEOUT_S", 0.05)
    on_normalized, deps, _, _ = _build(monkeypatch)
    deps["interaction_handler"].handle_fast_path.return_value = _with_receipt(_saved_attendance(), _slow)

    with caplog.at_level("ERROR"):
        await on_normalized(_message(), {})

    assert len(_sends(deps)) == 1
    assert "header_image" not in deps["sender"].send_button.await_args.kwargs
    deps["sender"].send_image.assert_not_awaited()
    assert any("receipt.render_failed" in r.getMessage() for r in caplog.records)


async def test_a_multi_part_note_gets_one_combined_receipt(monkeypatch):
    from runtime.agent.runner import AgentResult

    parts = [_with_receipt(_saved_attendance(), _png), _with_receipt(_saved_attendance(), _png)]

    class _Runner:
        def __init__(self, provider):
            pass

        async def run(self, *, ctx, user_text, gateway, scope, correlation_id, lap=None, after_tool=None):
            gateway.handled.extend(parts)
            return AgentResult(
                outcome="ok", reply=ReplySpec(text=SAVED), toolbox=SimpleNamespace(parked=None)
            )

    monkeypatch.setattr("runtime.agent.runner.AgentRunner", _Runner)
    on_normalized, deps, _, _ = _build(monkeypatch, agent_provider=object())
    deps["org_settings_query"].get.return_value = "agent"
    deps["interaction_handler"].build_combined_receipt = AsyncMock(return_value=PNG)

    await on_normalized(_message(), {})

    sender = deps["sender"]
    assert len(_sends(deps)) == 1
    deps["interaction_handler"].build_combined_receipt.assert_awaited_once()
    assert deps["interaction_handler"].build_combined_receipt.await_args.args[0] == parts
    assert sender.send_button.await_args.kwargs["header_image"] == PNG
    sender.send_image.assert_not_awaited()
    assert all(p.receipt_coro is None for p in parts)  # the per-part renders were dropped


async def test_a_single_saved_part_keeps_its_own_receipt(monkeypatch):
    from runtime.agent.runner import AgentResult

    class _Runner:
        def __init__(self, provider):
            pass

        async def run(self, *, ctx, user_text, gateway, scope, correlation_id, lap=None, after_tool=None):
            gateway.handled.append(_with_receipt(_saved_attendance(), _png))
            return AgentResult(
                outcome="ok", reply=ReplySpec(text=SAVED), toolbox=SimpleNamespace(parked=None)
            )

    monkeypatch.setattr("runtime.agent.runner.AgentRunner", _Runner)
    on_normalized, deps, _, _ = _build(monkeypatch, agent_provider=object())
    deps["org_settings_query"].get.return_value = "agent"
    deps["interaction_handler"].build_combined_receipt = AsyncMock(return_value=b"combined")

    await on_normalized(_message(), {})

    assert deps["sender"].send_button.await_args.kwargs["header_image"] == PNG
    deps["interaction_handler"].build_combined_receipt.assert_not_awaited()


async def test_the_card_is_made_and_uploaded_while_the_model_writes_the_reply(monkeypatch):
    """B-7: started after the last tool call, not after the final model round."""
    import asyncio

    from runtime.agent.runner import AgentResult

    order: list[str] = []

    async def _card():
        order.append("card")
        return PNG

    class _Runner:
        def __init__(self, provider):
            pass

        async def run(self, *, ctx, user_text, gateway, scope, correlation_id, lap=None, after_tool=None):
            gateway.handled.append(_with_receipt(_saved_attendance(), _card))
            after_tool()
            await asyncio.sleep(0.2)  # the final model round
            order.append("model")
            return AgentResult(
                outcome="ok", reply=ReplySpec(text=SAVED), toolbox=SimpleNamespace(parked=None)
            )

    monkeypatch.setattr("runtime.agent.runner.AgentRunner", _Runner)
    on_normalized, deps, _, _ = _build(monkeypatch, agent_provider=object())
    deps["org_settings_query"].get.return_value = "agent"

    await on_normalized(_message(), {})

    assert order == ["card", "model"]
    deps["sender"].prepare_image.assert_awaited_once_with(PNG)
    assert deps["sender"].send_button.await_args.kwargs["header_image"] == PNG


async def test_a_save_after_the_card_started_gets_the_combined_card(monkeypatch):
    import asyncio

    from runtime.agent.runner import AgentResult

    first = _with_receipt(_saved_attendance(), _png)
    second = _with_receipt(_saved_attendance(), _png)

    class _Runner:
        def __init__(self, provider):
            pass

        async def run(self, *, ctx, user_text, gateway, scope, correlation_id, lap=None, after_tool=None):
            gateway.handled.append(first)
            after_tool()
            await asyncio.sleep(0.1)  # the single card starts
            gateway.handled.append(second)  # a second tool round saved more
            after_tool()
            await asyncio.sleep(0.1)
            return AgentResult(
                outcome="ok", reply=ReplySpec(text=SAVED), toolbox=SimpleNamespace(parked=None)
            )

    monkeypatch.setattr("runtime.agent.runner.AgentRunner", _Runner)
    on_normalized, deps, _, _ = _build(monkeypatch, agent_provider=object())
    deps["org_settings_query"].get.return_value = "agent"
    deps["interaction_handler"].build_combined_receipt = AsyncMock(return_value=b"combined")

    await on_normalized(_message(), {})

    assert deps["interaction_handler"].build_combined_receipt.await_args.args[0] == [first, second]
    assert deps["sender"].send_button.await_args.kwargs["header_image"] == b"combined"


# -- dispatch and sender -----------------------------------------------------------


async def test_a_failed_header_send_falls_back_to_text_buttons_then_the_image():
    send_text = AsyncMock()
    send_button = AsyncMock(side_effect=[False, True])
    send_image = AsyncMock(return_value=True)
    spec = ReplySpec(text=SAVED, buttons=(UNDO_ROW,), header_image=PNG)

    await send_reply_spec(
        spec, "wa", send_text=send_text, send_button=send_button, send_image=send_image
    )

    assert send_button.await_args_list[0].kwargs["header_image"] == PNG
    assert "header_image" not in send_button.await_args_list[1].kwargs
    send_image.assert_awaited_once_with("wa", PNG, caption=None, shows=ANY)
    send_text.assert_not_awaited()


async def test_the_sender_puts_the_uploaded_receipt_in_the_button_header():
    import json

    import httpx

    from channel.whatsapp.outbound import WhatsAppSender

    seen = []

    def handler(request):
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "media-9"})
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.out"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sender = WhatsAppSender(client=client, access_token="t", phone_number_id="1")
        assert await sender.send_button("919", body="Saved", buttons=[UNDO_ROW], header_image=PNG) is True
    interactive = seen[0]["interactive"]
    assert interactive["header"] == {"type": "image", "image": {"id": "media-9"}}
    assert interactive["body"] == {"text": "Saved"}


async def test_a_failed_header_upload_sends_nothing_and_returns_false():
    import httpx

    from channel.whatsapp.outbound import WhatsAppSender

    posts = []

    def handler(request):
        posts.append(request.url.path)
        return httpx.Response(500, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sender = WhatsAppSender(client=client, access_token="t", phone_number_id="1")
        assert await sender.send_button("919", body="Saved", buttons=[UNDO_ROW], header_image=PNG) is False
    assert all(p.endswith("/media") for p in posts)


def test_a_let_go_question_is_folded_into_the_new_reply_not_sent_apart():
    from runtime.reply_composer import fold_note, let_go_note

    note = let_go_note(
        {"promotable_workers": [{"name": "Vinod"}, {"name": "Manoj"}, {"name": "Biju"}]},
        NONE_ADDED,
    )
    assert note == "(Vinod, Manoj and Biju stay as temporary for now.)"
    spec = ReplySpec(
        text="What trade were these 5 workers?",
        list_button_label="Choose",
        list_rows=(ListRow("steel_bender", "Steel bender"),),
    )
    folded = fold_note(spec, note)
    assert folded.text == f"What trade were these 5 workers?\n\n{note}"
    assert folded.list_rows == spec.list_rows  # the choices are untouched
    assert let_go_note({}, "Made permanent: X") == "Made permanent: X"
    assert fold_note(spec, "  ") is spec


async def _let_go(monkeypatch, *, provider):
    """A message that lets an open promotion question go, then is answered by
    the agent (``provider``; None: nothing can read it) -- returns the sends."""
    from mesiri_contracts.assistant.planner_decision import WorkflowKey
    from workflows.runtime import WorkflowRunResult

    on_normalized, deps, _, _ = _build(monkeypatch, agent_provider=provider)
    closing = WorkflowRunResult.completed(
        workflow_key=WorkflowKey.WORKER_PROMOTION,
        correlation_id="c",
        pending_prompt=NONE_ADDED,
        collected_fields={"promotable_workers": [{"name": "Vinod"}, {"name": "Manoj"}]},
    )
    deps["interaction_handler"].handle_slot_answer.return_value = InteractionHandled(
        result=closing, reply_text=NONE_ADDED, closed_question=True
    )
    await on_normalized(_message("Today 5 workers came"), {})
    return deps


async def test_letting_a_question_go_adds_no_message_to_the_new_reply(monkeypatch):
    from mesiri_ai.fakes import FakeToolCallingProvider

    ask_trade = FakeToolCallingProvider(
        [
            [("ask_user", {"question": "What trade were these 5 workers?", "options": ["Mason", "Helper"]})],
            "What trade were these 5 workers?",
        ]
    )
    deps = await _let_go(monkeypatch, provider=ask_trade)

    sends = _sends(deps)
    assert len(sends) == 1
    body = sends[0].kwargs.get("body") or sends[0].args[1]
    assert body.startswith("What trade were these 5 workers?")
    assert "Vinod and Manoj stay as temporary for now." in body


async def test_a_let_go_line_is_never_lost_when_the_new_message_gets_no_reply(monkeypatch):
    deps = await _let_go(monkeypatch, provider=None)

    sends = _sends(deps)
    assert len(sends) == 1
    assert "Vinod and Manoj stay as temporary for now." in sends[0].args[1]


def test_a_tap_or_typed_trade_label_maps_back_to_its_code():
    from trade_label import trade_label

    rows = [ListRow(code, trade_label(code)) for code in ("steel_bender", "mason", "helper")]
    assert [r.title for r in rows] == ["Steel bender", "Mason", "Helper"]
    assert resolve_choice("Steel bender", rows).id == "steel_bender"
    assert resolve_choice("steel bender", rows).id == "steel_bender"
    assert resolve_choice("1", rows).id == "steel_bender"


def test_trade_labels_are_shared_by_the_labour_screens():
    from workflows.labour_query.nodes import _pretty_trade as query_label
    from workflows.labour_update.nodes import _line_summary
    from workflows.readable import value_text

    assert query_label("steel_bender") == "Steel bender"
    assert value_text("trade", "steel_bender") == "Steel bender"
    assert "5 × Steel bender" in _line_summary({"trade": "steel_bender", "headcount": 5})


async def test_a_voice_note_gets_the_check_mark_reaction_not_a_listening_message(monkeypatch):
    """29 Oct: "🎤 Got your voice note — listening now..." was a second message on
    every voice note; the ✅ reaction on their own message replaces it."""
    import asyncio

    on_normalized, deps, _, _ = _build(monkeypatch)
    deps["interaction_handler"].handle_fast_path.return_value = _saved_attendance()

    await on_normalized(_message(modality=InputModality.VOICE), {})
    await asyncio.sleep(0)

    deps["sender"].send_reaction.assert_awaited_once_with("919876543210", "wamid.in.1", "✅")
    texts = [str(c.args[1]) for c in deps["sender"].send_text.await_args_list]
    assert not any("listening" in t or "Got your" in t for t in texts)
