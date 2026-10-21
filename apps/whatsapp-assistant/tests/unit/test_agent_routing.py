"""Request [40]: which messages the agent takes, and that "off" changes nothing."""

from __future__ import annotations

import datetime as dt
import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import runtime.message_journey as mj
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo

ORG = uuid.uuid4()


def _message(text="10 masons today", modality=InputModality.TEXT):
    return NormalizedMessage(
        message_id="wamid.in.1",
        sender=SenderInfo(wa_id="919876543210", profile_name="Ravi"),
        timestamp=dt.datetime(2026, 10, 19, 6, tzinfo=dt.UTC),
        modality=modality,
        text=text,
    )


class _Reached(Exception):
    pass


def _build(monkeypatch, *, mode, provider):
    async def fake_resolve(_reader, wa_id):
        return SimpleNamespace(
            organization_id=ORG,
            org_active=True,
            user_id=str(uuid.uuid4()),
            full_name="Ravi",
            role="SUPERVISOR",
            org_name="Acme",
            projects=[],
            sites=[],
        )

    monkeypatch.setattr(mj, "resolve_sender", fake_resolve)
    classic = AsyncMock(side_effect=_Reached("classic pipeline"))
    monkeypatch.setattr(mj, "process_inbound_message", classic)

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
    handler.undo_latest_draft.return_value = None
    org_settings = deps["org_settings_query"]
    org_settings.enabled_modules.return_value = ["dpr", "labour"]
    org_settings.get.return_value = mode
    deps["category_hint_store"].pop_hint.return_value = None
    deps["memory_loader"].load.return_value = SimpleNamespace(
        recent_turns=(), has_pending_confirmation=False
    )
    monkeypatch.setattr(mj, "try_hold_new_image_for_purpose_picker", AsyncMock(return_value=None))
    monkeypatch.setattr(mj.workflow_registry, "set_enabled_modules", MagicMock())
    on_normalized, _ = mj.build_message_handlers(**deps, agent_provider=provider)
    return on_normalized, deps, classic


ASK = FakeToolCallingProvider(
    [
        [("ask_user", {"question": "Received or used?", "options": ["Received", "Used"]})],
        "Received or used?",
    ]
)


async def test_a_company_switched_to_the_agent_gets_its_reply_not_the_classic_pipeline(monkeypatch):
    on_normalized, deps, classic = _build(monkeypatch, mode="agent", provider=ASK)
    await on_normalized(_message("50 bags cement"), {})
    classic.assert_not_called()
    sent = deps["sender"].send_button.await_args
    assert sent.kwargs["body"] == "Received or used?"
    assert [b.title for b in sent.kwargs["buttons"]] == ["Received", "Used"]
    deps["org_settings_query"].get.assert_awaited()
    assert deps["org_settings_query"].get.await_args.kwargs["key"] == "assistant_mode"


async def test_one_turn_is_recorded_for_the_next_message(monkeypatch):
    on_normalized, deps, _ = _build(monkeypatch, mode="agent", provider=ASK)
    await on_normalized(_message("50 bags cement"), {})
    recorded = deps["memory_coordinator"].record_turn.await_args.kwargs
    assert recorded["user_text"] == "50 bags cement"
    assert "Received or used?" in recorded["assistant_reply"]
    assert "Received / Used" in recorded["assistant_reply"]


@pytest.mark.parametrize("mode", ["off", None, "", "AGENT?"])
async def test_anything_but_agent_stays_on_the_classic_pipeline(monkeypatch, mode):
    on_normalized, _, classic = _build(monkeypatch, mode=mode, provider=ASK)
    with pytest.raises(_Reached):
        await on_normalized(_message(), {})
    classic.assert_awaited_once()


async def test_without_a_provider_the_switch_is_ignored(monkeypatch):
    on_normalized, _, classic = _build(monkeypatch, mode="agent", provider=None)
    with pytest.raises(_Reached):
        await on_normalized(_message(), {})
    classic.assert_awaited_once()


async def test_a_failing_mode_lookup_means_classic(monkeypatch):
    on_normalized, deps, classic = _build(monkeypatch, mode="agent", provider=ASK)
    deps["org_settings_query"].get.side_effect = RuntimeError("db down")
    with pytest.raises(_Reached):
        await on_normalized(_message(), {})
    classic.assert_awaited_once()


async def test_photos_never_go_to_the_agent(monkeypatch):
    on_normalized, deps, classic = _build(monkeypatch, mode="agent", provider=ASK)
    image = _message(text=None, modality=InputModality.IMAGE)
    with pytest.raises(_Reached):
        await on_normalized(image, {})
    classic.assert_awaited_once()
    deps["org_settings_query"].get.assert_not_awaited()


async def test_an_empty_tap_text_never_goes_to_the_agent(monkeypatch):
    on_normalized, _, classic = _build(monkeypatch, mode="agent", provider=ASK)
    with pytest.raises(_Reached):
        await on_normalized(_message(text="  ", modality=InputModality.INTERACTIVE), {})
    classic.assert_awaited_once()


async def test_an_ai_outage_before_any_save_is_queued_and_retried(monkeypatch):
    from mesiri_contracts.common.errors import MesiriError
    from runtime.ai_outage import QUEUED_REPLY, AIUnavailableError, retry_attempt

    down = FakeToolCallingProvider([], error=MesiriError.configuration("x", code="PROVIDER_ERROR"))
    on_normalized, deps, _ = _build(monkeypatch, mode="agent", provider=down)
    token = retry_attempt.set(1)
    try:
        with pytest.raises(AIUnavailableError):
            await on_normalized(_message("10 masons"), {})
    finally:
        retry_attempt.reset(token)
    assert [c.args[1] for c in deps["sender"].send_text.await_args_list] == [QUEUED_REPLY]


async def test_a_provider_blip_is_retried_at_once_and_the_sender_hears_nothing_about_it(monkeypatch):
    """Request 57, A5: "I'll process this in a few minutes" is only said when
    a second immediate try also fails."""
    from mesiri_contracts.common.errors import MesiriError
    from runtime import ai_outage
    from runtime.ai_outage import QUEUED_REPLY, retry_attempt

    monkeypatch.setattr(ai_outage, "QUICK_RETRY_PAUSE_SECONDS", 0)
    import runtime.agent.turn as turn_module

    monkeypatch.setattr(turn_module, "QUICK_RETRY_PAUSE_SECONDS", 0)

    class _FlakyOnce(FakeToolCallingProvider):
        async def run_tools(self, *args, **kwargs):  # noqa: ANN002, ANN003
            if self.calls == 0:
                self.calls += 1
                raise MesiriError.configuration("x", code="PROVIDER_ERROR")
            return await super().run_tools(*args, **kwargs)

    flaky = _FlakyOnce(["Hello!"])
    on_normalized, deps, _ = _build(monkeypatch, mode="agent", provider=flaky)
    token = retry_attempt.set(1)
    try:
        await on_normalized(_message("hi"), {})
    finally:
        retry_attempt.reset(token)
    sent = [c.args[1] for c in deps["sender"].send_text.await_args_list]
    assert QUEUED_REPLY not in sent
    assert flaky.calls == 2


# Request [68]: a reply that saved nothing (a question or small talk) is one message;
# the daily setup question waits for a save, so neither case asks here.
@pytest.mark.parametrize(("provider", "asked"), [(ASK, False), (FakeToolCallingProvider(["Hello!"]), False)])
async def test_the_daily_setup_question_never_piles_on_an_open_question(monkeypatch, provider, asked):
    setup = MagicMock()
    setup.after_reply = AsyncMock()
    setup.handle_tap = AsyncMock(return_value=None)
    setup.handle_media = AsyncMock(return_value=None)
    _, deps, _ = _build(monkeypatch, mode="agent", provider=provider)
    on_normalized, _ = mj.build_message_handlers(
        **{n: deps[n] for n in inspect.signature(mj.build_message_handlers).parameters if n in deps},
        agent_provider=provider,
        setup_questions=setup,
    )
    await on_normalized(_message("50 bags cement"), {})
    assert setup.after_reply.await_count == (1 if asked else 0)


# WA-35: the agent's records wait on the sender's Save tap.


def _saving(monkeypatch, deps):
    """The pipeline saves one labour draft, as save-first does."""
    from mesiri_contracts.assistant.draft_action import DraftActionType
    from workflows import WorkflowRunStatus

    row = uuid.uuid4()
    run = SimpleNamespace(status=WorkflowRunStatus.STARTED, workflow_key=SimpleNamespace(value="labour_attendance"))
    monkeypatch.setattr(
        mj, "process_inbound_message", AsyncMock(return_value=SimpleNamespace(workflow_run=run, planner_decision=None))
    )
    handled = SimpleNamespace(
        saved_draft=True,
        reply_text="✅ Recorded. Thank you.",
        receipt_coro=None,
        execution_result=SimpleNamespace(material_row_id=str(row)),
        result=SimpleNamespace(
            workflow_instance_id=None,
            confirmed_action=SimpleNamespace(
                draft_action=SimpleNamespace(
                    action_type=DraftActionType.RECORD_LABOUR_ATTENDANCE,
                    fields={"lines": [{"trade": "mason", "headcount": 6}]},
                )
            ),
        ),
        project_id=None,
        site_id=None,
    )
    deps["interaction_handler"].save_now.return_value = handled
    return row


async def test_what_the_agent_saves_goes_out_with_save_and_cancel(monkeypatch):
    from runtime.agent import save_button

    provider = FakeToolCallingProvider(
        [[("save_labour", {"workers": [{"trade": "mason", "headcount": 6}]})], ""]
    )
    on_normalized, deps, _ = _build(monkeypatch, mode="agent", provider=provider)
    row = _saving(monkeypatch, deps)

    await on_normalized(_message("6 mason today"), {})

    # The first message is the agent's reply (any later one is a follow-up).
    sent = deps["sender"].send_button.await_args_list[0].kwargs
    assert sent["body"].startswith(save_button.TO_SAVE_HEADER)
    titles = [b.title for b in sent["buttons"]]
    assert titles[:2] == [save_button.SAVE_TITLE, save_button.CANCEL_TITLE]
    assert "↩️ Undo" not in titles
    assert sent["buttons"][0].id == save_button.tap_id(save_button.SAVE, [("labour_report", row)])


async def test_a_save_tap_confirms_without_reaching_the_agent_or_the_pipeline(monkeypatch):
    from runtime.agent import save_button
    from runtime.save_first import DraftsSettled

    provider = FakeToolCallingProvider([])
    on_normalized, deps, classic = _build(monkeypatch, mode="agent", provider=provider)
    deps["interaction_handler"].settle_drafts.return_value = DraftsSettled(done=1)
    row = uuid.uuid4()
    tap = _message(save_button.SAVE_TITLE, modality=InputModality.INTERACTIVE).model_copy(
        update={
            "metadata": {
                "interactive_reply_id": save_button.tap_id(save_button.SAVE, [("labour_report", row)]),
                "interactive_reply_type": "button_reply",
            }
        }
    )

    await on_normalized(tap, {})

    classic.assert_not_called()
    assert provider.calls == 0
    kwargs = deps["interaction_handler"].settle_drafts.await_args.kwargs
    assert kwargs["facts"] == [("labour_report", row)] and kwargs["keep"] is True
    sent = [c.args[1] for c in deps["sender"].send_text.await_args_list]
    assert save_button.SAVED_DONE in sent
