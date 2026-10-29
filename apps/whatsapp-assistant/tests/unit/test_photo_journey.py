"""Photos (audit 07) through the real message journey, every service a mock:
PHO-01 the Site Update tap, PHO-06 the reminder, PHO-07 the caption."""

from __future__ import annotations

import datetime as dt
import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import runtime.message_journey as mj
from interactions.pending_media import PendingMediaStore
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import (
    MediaReference,
    NormalizedMessage,
    SenderInfo,
)

ORG = str(uuid.uuid4())
USER = str(uuid.uuid4())
SITE = str(uuid.uuid4())


def _photo(message_id: str, caption: str | None = None) -> NormalizedMessage:
    return NormalizedMessage(
        message_id=message_id,
        correlation_id=f"cor_{message_id}",
        sender=SenderInfo(wa_id="919876543210", profile_name="Ravi"),
        timestamp=dt.datetime(2026, 10, 25, 6, tzinfo=dt.UTC),
        modality=InputModality.IMAGE,
        text=caption,
        media=MediaReference(object_key=f"media/{message_id}/x", mime_type="image/jpeg", size_bytes=10),
    )


def _text(body: str) -> NormalizedMessage:
    return NormalizedMessage(
        message_id="wamid.t", correlation_id="cor_t",
        sender=SenderInfo(wa_id="919876543210", profile_name="Ravi"),
        timestamp=dt.datetime(2026, 10, 25, 6, tzinfo=dt.UTC), modality=InputModality.TEXT, text=body,
    )


def _build(monkeypatch, *, tap=None, provider=None):
    async def fake_resolve(_reader, wa_id):
        return SimpleNamespace(
            organization_id=ORG, org_active=True, user_id=USER, full_name="Ravi", role="SITE_ENGINEER",
            org_name="Acme", projects=[], sites=[SimpleNamespace(id=SITE, name="Green Villa", project_id=None)],
        )

    monkeypatch.setattr(mj, "resolve_sender", fake_resolve)
    params = inspect.signature(mj.build_message_handlers).parameters
    deps = {n: AsyncMock() for n, p in params.items() if p.default is inspect.Parameter.empty}
    handler = deps["interaction_handler"]
    handler.handle_fast_path.return_value = None
    handler.handle_slot_answer.return_value = None
    for sync_name in ("handle_category_tap", "handle_material_direction_tap", "handle_greeting_trigger",
                      "handle_whoami_trigger"):
        setattr(handler, sync_name, MagicMock(return_value=None))
    handler.handle_image_purpose_tap = MagicMock(return_value=tap)
    handler.undo_latest_draft.return_value = None
    deps["org_settings_query"].enabled_modules.return_value = ["dpr", "labour", "materials"]
    deps["org_settings_query"].get.return_value = "agent"
    deps["category_hint_store"].pop_hint.return_value = None
    deps["completion_photo_hint_store"].pop_hint.return_value = None
    for store in ("team_photo_hint_store",):
        for name in ("pop", "pop_hint", "pop_pending", "pop_report"):
            getattr(deps[store], name).return_value = None
    deps["memory_loader"].load.return_value = SimpleNamespace(recent_turns=(), has_pending_confirmation=False)
    deps["pending_media_store"] = PendingMediaStore(FakeRedis())
    deps["activity_query"].find_activity_for_photos.return_value = {
        "activity_id": "act-1", "site_id": SITE, "work_type": "plastering", "narrative": "plastering 2nd floor",
    }
    deps["evidence_query"].attach_photos.return_value = ["a"]
    monkeypatch.setattr(mj.workflow_registry, "set_enabled_modules", MagicMock())
    on_normalized, _ = mj.build_message_handlers(
        **deps, agent_provider=provider or FakeToolCallingProvider(["Read the bill."])
    )
    return on_normalized, deps


def _sent_texts(deps) -> list[str]:
    texts = [c.args[1] for c in deps["sender"].send_text.await_args_list]
    texts += [c.kwargs.get("body", "") for c in deps["sender"].send_list.await_args_list]
    texts += [c.kwargs.get("body", "") for c in deps["sender"].send_button.await_args_list]
    return texts


async def test_pho01_the_site_update_tap_attaches_the_batch_with_its_captions(monkeypatch):
    on_normalized, deps = _build(monkeypatch, tap="img_site_update")
    store = deps["pending_media_store"]
    await store.add_pending(user_id=USER, message=_photo("wamid.1", "2nd floor plastering"))
    await store.add_pending(user_id=USER, message=_photo("wamid.2"))
    deps["activity_query"].find_activity_for_photos.return_value = {
        "activity_id": "act-1", "site_id": SITE, "work_type": "plastering", "narrative": "plastering 2nd floor",
    }
    deps["evidence_query"].attach_photos.return_value = ["a", "b"]

    await on_normalized(_text("tap"), {})

    looked = deps["activity_query"].find_activity_for_photos.await_args.kwargs
    assert looked["site_ids"] == [SITE] and looked["reported_by_user_id"] == USER
    attached = deps["evidence_query"].attach_photos.await_args.kwargs
    assert attached["media_object_keys"] == ["media/wamid.1/x", "media/wamid.2/x"]
    assert attached["captions"] == ["2nd floor plastering", None]
    assert any("2 photos attached to plastering" in t for t in _sent_texts(deps))


async def test_pho07_a_caption_that_names_the_purpose_is_not_asked_about(monkeypatch):
    on_normalized, deps = _build(monkeypatch)
    await on_normalized(_photo("wamid.9", "2nd floor plastering"), {})
    sent = _sent_texts(deps)
    assert not any("What is this photo for" in t for t in sent)
    # a Site Update caption goes to the work, with the caption
    deps["activity_query"].find_activity_for_photos.assert_awaited_once()
    assert deps["evidence_query"].attach_photos.await_args.kwargs["captions"] == ["2nd floor plastering"]


async def test_pho07_the_rest_of_the_captioned_burst_is_not_asked_either(monkeypatch):
    on_normalized, deps = _build(monkeypatch)
    await on_normalized(_photo("wamid.1", "2nd floor plastering"), {})
    await on_normalized(_photo("wamid.2"), {})
    assert not any("What is this photo for" in t for t in _sent_texts(deps))
    assert deps["evidence_query"].attach_photos.await_count == 2


async def test_pho07_a_photo_with_no_caption_is_still_asked(monkeypatch):
    on_normalized, deps = _build(monkeypatch)
    await on_normalized(_photo("wamid.1"), {})
    assert any("What is this photo for" in t for t in _sent_texts(deps))
    deps["evidence_query"].attach_photos.assert_not_awaited()


async def test_pho06_a_photo_left_waiting_is_reminded_about_on_the_next_message(monkeypatch):
    on_normalized, deps = _build(monkeypatch)
    store = deps["pending_media_store"]
    await store.add_pending(user_id=USER, message=_photo("wamid.1"), now=1.0)  # held long ago

    await on_normalized(_text("5 masons today"), {})

    assert any("still waiting" in t for t in _sent_texts(deps))
    # once: the next message does not remind again
    deps["sender"].send_list.reset_mock()
    await on_normalized(_text("and 3 helpers"), {})
    assert not any("still waiting" in c.kwargs.get("body", "") for c in deps["sender"].send_list.await_args_list)

