"""Request 124: the journey routes the taps of a draft card (`agd:...`) to the
draft, not to the old Save button, and reads the company's `draft_v2` setting."""

from __future__ import annotations

import datetime as dt
import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import runtime.agent.journey_gateway as jg
import runtime.message_journey as mj
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from runtime.agent import draft as dr
from runtime.agent.draft_store import MemoryDraftStore

ORG = uuid.uuid4()
USER = str(uuid.uuid4())


def _tap(row_id: str, title: str) -> NormalizedMessage:
    return NormalizedMessage(
        message_id="wamid.in.tap",
        sender=SenderInfo(wa_id="919876543210", profile_name="Ravi"),
        timestamp=dt.datetime(2026, 10, 27, 6, tzinfo=dt.UTC),
        modality=InputModality.INTERACTIVE,
        text=title,
        metadata={"interactive_reply_id": row_id, "interactive_reply_type": "button_reply"},
    )


def _build(monkeypatch, *, drafts, setting=True):
    async def fake_resolve(_reader, wa_id):
        return SimpleNamespace(
            organization_id=ORG, org_active=True, user_id=USER, full_name="Ravi", role="SUPERVISOR",
            org_name="Acme", projects=[], sites=[],
        )

    monkeypatch.setattr(mj, "resolve_sender", fake_resolve)
    params = inspect.signature(mj.build_message_handlers).parameters
    deps = {n: AsyncMock() for n, p in params.items() if p.default is inspect.Parameter.empty}
    handler = deps["interaction_handler"]
    handler.handle_fast_path.return_value = None
    handler.handle_slot_answer.return_value = None
    for name in (
        "handle_category_tap", "handle_material_direction_tap", "handle_image_purpose_tap",
        "handle_greeting_trigger", "handle_whoami_trigger",
    ):
        setattr(handler, name, MagicMock(return_value=None))
    handler.undo_latest_draft.return_value = None
    deps["org_settings_query"].enabled_modules.return_value = ["dpr", "labour"]
    deps["org_settings_query"].get.return_value = setting
    deps["category_hint_store"].pop_hint.return_value = None
    deps["memory_loader"].load.return_value = SimpleNamespace(recent_turns=(), has_pending_confirmation=False)
    monkeypatch.setattr(mj, "try_hold_new_image_for_purpose_picker", AsyncMock(return_value=None))
    monkeypatch.setattr(mj.workflow_registry, "set_enabled_modules", MagicMock())
    on_normalized, _ = mj.build_message_handlers(
        **deps, agent_provider=FakeToolCallingProvider(["unused"]), drafts=drafts
    )
    return on_normalized, deps


def _draft() -> dr.MessageDraft:
    draft = dr.MessageDraft.new(organization_id=str(ORG), user_id=USER)
    draft.items.append(
        dr.DraftItem(kind=dr.KIND_MATERIAL_IN, tool="save_material_receipt", args={}, summary="Cement in: 50 bags")
    )
    return draft


def _said(deps) -> list[str]:
    calls = [*deps["sender"].send_text.await_args_list]
    return [c.args[1] if len(c.args) > 1 else c.kwargs.get("text", "") for c in calls]


async def test_cancel_tap_discards_the_draft_and_says_nothing_was_saved(monkeypatch):
    store = MemoryDraftStore()
    draft = _draft()
    await store.put(draft)
    on_normalized, deps = _build(monkeypatch, drafts=store)

    await on_normalized(_tap(dr.tap_id(dr.CANCEL, draft.id), "❌ Cancel"), {})

    assert dr.CANCELLED in _said(deps)
    assert store.rows[draft.id].status == dr.DISCARDED
    deps["interaction_handler"].save_now.assert_not_awaited()
    deps["workflow_runtime"].start.assert_not_awaited()  # nothing was started, nothing written


async def test_a_tap_on_a_card_that_is_already_done_writes_nothing(monkeypatch):
    store = MemoryDraftStore()
    draft = _draft()
    await store.put(draft)
    await store.discard(draft.id)
    on_normalized, deps = _build(monkeypatch, drafts=store)

    await on_normalized(_tap(dr.tap_id(dr.SAVE, draft.id), "✅ Save"), {})

    # Request 162: a cancelled card's button says so (in code, never saves); a saved one stays ALREADY_DONE.
    assert "cancelled" in " ".join(_said(deps))
    deps["workflow_runtime"].start.assert_not_awaited()


async def test_a_tap_on_someone_elses_or_an_unknown_card_is_expired(monkeypatch):
    store = MemoryDraftStore()
    other = dr.MessageDraft.new(organization_id=str(ORG), user_id=str(uuid.uuid4()))
    other.items.append(dr.DraftItem(kind=dr.KIND_LABOUR, tool="save_labour", args={}, summary="3 workers"))
    await store.put(other)
    on_normalized, deps = _build(monkeypatch, drafts=store)

    await on_normalized(_tap(dr.tap_id(dr.SAVE, other.id), "✅ Save"), {})

    assert dr.EXPIRED in _said(deps)
    assert store.rows[other.id].status == dr.OPEN  # not theirs: untouched


async def test_an_expired_card_is_discarded_not_saved(monkeypatch):
    store = MemoryDraftStore()
    draft = _draft()
    await store.put(draft)
    store.rows[draft.id].updated -= dr.DRAFT_TTL_SECONDS + 60
    on_normalized, deps = _build(monkeypatch, drafts=store)

    await on_normalized(_tap(dr.tap_id(dr.SAVE, draft.id), "✅ Save"), {})

    assert dr.EXPIRED in _said(deps)
    assert store.rows[draft.id].status == dr.DISCARDED
    deps["workflow_runtime"].start.assert_not_awaited()


async def test_the_company_setting_decides_whether_messages_are_held_as_drafts(monkeypatch):
    # Request 136: on for every company; an explicit false is the per-company off switch.
    for stored, expected in ((True, True), (False, False), (None, True), ("true", True)):
        on_normalized, deps = _build(monkeypatch, drafts=MemoryDraftStore(), setting=stored)
        seen = {}
        original = jg.JourneyGateway

        def spy(*args, _seen=seen, _original=original, **kwargs):
            gateway = _original(*args, **kwargs)
            _seen["gateway"] = gateway
            return gateway

        monkeypatch.setattr(jg, "JourneyGateway", spy)
        message = _tap("not-a-draft", "hello").model_copy(update={"modality": InputModality.TEXT, "metadata": {}})
        await on_normalized(message, {})
        assert seen["gateway"].draft_mode is expected, stored


def _text(text: str) -> NormalizedMessage:
    return NormalizedMessage(
        message_id="wamid.in.help",
        sender=SenderInfo(wa_id="919876543210", profile_name="Ravi"),
        timestamp=dt.datetime(2026, 10, 27, 6, tzinfo=dt.UTC),
        modality=InputModality.TEXT,
        text=text,
    )


async def test_help_with_draft_cards_is_the_one_help_not_the_category_menu(monkeypatch):
    """WA-83 (live 27 Oct, screenshot 19): "help" got the old menu with switched-off
    Money and Reminders. With draft cards it is the one help: the company's modules
    and examples to copy."""
    from channel.replies import render_greeting_menu

    on_normalized, deps = _build(monkeypatch, drafts=MemoryDraftStore())
    deps["interaction_handler"].handle_greeting_trigger.return_value = render_greeting_menu()

    await on_normalized(_text("help"), {})

    deps["sender"].send_list.assert_not_awaited()
    said = " ".join(_said(deps))
    assert "6 mason" in said or "example" in said.casefold()
    assert "Money" not in said


async def test_hi_still_opens_the_menu(monkeypatch):
    from channel.replies import render_greeting_menu

    on_normalized, deps = _build(monkeypatch, drafts=MemoryDraftStore())
    deps["interaction_handler"].handle_greeting_trigger.return_value = render_greeting_menu()

    await on_normalized(_text("hi"), {})

    deps["sender"].send_list.assert_awaited()


async def test_the_save_tap_sends_the_saved_records_card(monkeypatch):
    """Live 29 Oct: Save on a draft card sent "Saved" with no receipt card (a P1 limit,
    on for every company since 28 Oct). The saved record's card follows the "Saved"
    line -- the line never waits for the picture -- built after the tap so it says
    SAVED, never TO SAVE (the card made at the write did not know the tap)."""
    from runtime.agent.toolbox import ReplySpec

    store = MemoryDraftStore()
    draft = _draft()
    await store.put(draft)
    on_normalized, deps = _build(monkeypatch, drafts=store)

    async def card() -> bytes:
        return b"PNG-receipt"

    async def save_draft(self, _draft):  # noqa: ANN001, ANN202
        self.handled = [SimpleNamespace(receipt_coro=card(), workflow_key=None, execution_result=None)]
        self.draft = None
        return ReplySpec(text="✅ Saved: Cement in: 50 bags")

    monkeypatch.setattr(jg.JourneyGateway, "save_draft", save_draft)
    deps["interaction_handler"].build_combined_receipt.return_value = b"PNG-saved"
    await on_normalized(_tap(dr.tap_id(dr.SAVE, draft.id), "✅ Save"), {})

    images = [c.args[1] if len(c.args) > 1 else c.kwargs.get("image") for c in deps["sender"].send_image.await_args_list]
    assert b"PNG-saved" in images, deps["sender"].method_calls
    assert deps["interaction_handler"].build_combined_receipt.await_args.kwargs == {"kept": True}
    # The words went first: the picture is the last thing sent.
    sent = [c[0] for c in deps["sender"].method_calls if c[0] in ("send_text", "send_image", "send_button")]
    assert sent[-1] == "send_image" and sent.index("send_image") > 0, sent
