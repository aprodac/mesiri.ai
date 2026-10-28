"""Unit tests for WhatsApp ingress receiver orchestration."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from tests.fixtures.meta_payloads import (
    image_webhook_payload,
    text_webhook_payload,
    voice_webhook_payload,
)

from ingress.deduplication import InMemoryDeduplicationStore
from ingress.media_ingestion import DownloadedMedia
from ingress.receiver import InMemoryNormalizedMessageStore, WhatsAppReceiver
from mesiri.infrastructure.objectstorage.fake import FakeObjectStorage
from mesiri_contracts.assistant.enums import InputModality


@pytest.mark.asyncio
async def test_receiver_normalizes_text_message() -> None:
    deduplication_store = InMemoryDeduplicationStore()
    message_store = InMemoryNormalizedMessageStore()
    media_downloader = AsyncMock()
    receiver = WhatsAppReceiver(
        deduplication_store=deduplication_store,
        media_downloader=media_downloader,
        message_store=message_store,
        object_storage=FakeObjectStorage(),
    )

    scheduled = await receiver.handle_payload(text_webhook_payload())
    await receiver.wait_until_idle()

    assert scheduled == 1
    media_downloader.download.assert_not_called()
    normalized = await message_store.get("wamid.text")
    assert normalized is not None
    assert normalized.modality is InputModality.TEXT


@pytest.mark.asyncio
async def test_receiver_enqueues_claimed_messages_instead_of_processing_inline() -> None:
    """When a durable queue is wired up (runtime/queue.py, real Redis only),
    a claimed message must be handed to it rather than to
    asyncio.create_task -- that in-process task is exactly what gets lost if
    the process crashes before it finishes."""
    deduplication_store = InMemoryDeduplicationStore()
    message_store = InMemoryNormalizedMessageStore()
    media_downloader = AsyncMock()
    enqueue = AsyncMock()
    receiver = WhatsAppReceiver(
        deduplication_store=deduplication_store,
        media_downloader=media_downloader,
        message_store=message_store,
        object_storage=FakeObjectStorage(),
        enqueue=enqueue,
    )

    scheduled = await receiver.handle_payload(text_webhook_payload())
    await receiver.wait_until_idle()

    assert scheduled == 1
    enqueue.assert_awaited_once()
    (context,) = enqueue.await_args.args
    assert context.message["id"] == "wamid.text"
    # Never processed in-process -- that's the worker's job now.
    assert await message_store.get("wamid.text") is None


@pytest.mark.asyncio
async def test_receiver_deduplicates_duplicate_webhooks() -> None:
    deduplication_store = InMemoryDeduplicationStore()
    message_store = InMemoryNormalizedMessageStore()
    media_downloader = AsyncMock()
    receiver = WhatsAppReceiver(
        deduplication_store=deduplication_store,
        media_downloader=media_downloader,
        message_store=message_store,
        object_storage=FakeObjectStorage(),
    )

    payload = text_webhook_payload()
    assert await receiver.handle_payload(payload) == 1
    assert await receiver.handle_payload(payload) == 0
    await receiver.wait_until_idle()

    normalized = await message_store.get("wamid.text")
    assert normalized is not None


@pytest.mark.asyncio
async def test_receiver_downloads_media_for_image_and_voice() -> None:
    deduplication_store = InMemoryDeduplicationStore()
    message_store = InMemoryNormalizedMessageStore()
    object_storage = FakeObjectStorage()
    media_downloader = AsyncMock()

    media_downloader.download.side_effect = [
        DownloadedMedia(
            media_id="media-image-1",
            mime_type="image/jpeg",
            content=b"jpeg-bytes",
            sha256="abc123",
            file_size=1024,
        ),
        DownloadedMedia(
            media_id="media-audio-1",
            mime_type="audio/ogg",
            content=b"voice-bytes",
            sha256="voice123",
            file_size=2048,
        ),
    ]
    receiver = WhatsAppReceiver(
        deduplication_store=deduplication_store,
        media_downloader=media_downloader,
        message_store=message_store,
        object_storage=object_storage,
    )

    image_payload = image_webhook_payload(message_id="wamid.image-1")
    voice_payload = voice_webhook_payload(message_id="wamid.voice-1")

    assert await receiver.handle_payload(image_payload) == 1
    assert await receiver.handle_payload(voice_payload) == 1
    await receiver.wait_until_idle()

    image_message = await message_store.get("wamid.image-1")
    voice_message = await message_store.get("wamid.voice-1")

    assert image_message is not None
    assert image_message.modality is InputModality.IMAGE
    assert image_message.media is not None
    assert image_message.media.object_key == "media/wamid.image-1/media-image-1"
    assert voice_message is not None
    assert voice_message.modality is InputModality.VOICE
    assert voice_message.media is not None
    assert voice_message.media.object_key == "media/wamid.voice-1/media-audio-1"
    assert media_downloader.download.await_count == 2


@pytest.mark.asyncio
async def test_message_claimed_ack_fires_before_slow_media_download_completes() -> None:
    """The blue tick / typing indicator (on_message_claimed) must not wait on
    the Meta media download -- it used to run at the top of the journey
    callback, which for voice/image meant the sender saw no acknowledgement
    until download+upload+normalization had all finished. Proven here by
    giving the download an artificial delay and asserting the ack still
    completes first."""
    events: list[str] = []

    async def _slow_download(media_id: str) -> DownloadedMedia:
        await asyncio.sleep(0.05)
        events.append("downloaded")
        return DownloadedMedia(
            media_id=media_id,
            mime_type="audio/ogg",
            content=b"voice-bytes",
            sha256="abc",
            file_size=11,
        )

    async def _on_claimed(message_id: str) -> None:
        events.append("claimed")

    media_downloader = AsyncMock()
    media_downloader.download.side_effect = _slow_download

    receiver = WhatsAppReceiver(
        deduplication_store=InMemoryDeduplicationStore(),
        media_downloader=media_downloader,
        message_store=InMemoryNormalizedMessageStore(),
        object_storage=FakeObjectStorage(),
        on_message_claimed=_on_claimed,
    )

    await receiver.handle_payload(voice_webhook_payload(message_id="wamid.voice-slow"))
    await receiver.wait_until_idle()

    assert events == ["claimed", "downloaded"]


@pytest.mark.asyncio
async def test_receiver_normalizes_interactive_reply_without_downloading_media() -> None:
    """The media-download step has the same 'only text/image/audio' history as
    modality resolution did -- an interactive reply has no media at all, and
    must not be routed into a download attempt."""
    from tests.fixtures.meta_payloads import list_reply_webhook_payload

    deduplication_store = InMemoryDeduplicationStore()
    message_store = InMemoryNormalizedMessageStore()
    media_downloader = AsyncMock()
    receiver = WhatsAppReceiver(
        deduplication_store=deduplication_store,
        media_downloader=media_downloader,
        message_store=message_store,
        object_storage=FakeObjectStorage(),
    )

    scheduled = await receiver.handle_payload(list_reply_webhook_payload())
    await receiver.wait_until_idle()

    assert scheduled == 1
    media_downloader.download.assert_not_called()
    normalized = await message_store.get("wamid.interactive")
    assert normalized is not None
    assert normalized.modality is InputModality.INTERACTIVE
    assert normalized.text == "Material"
    assert normalized.metadata["interactive_reply_id"] == "cat_material"


@pytest.mark.asyncio
async def test_group_message_is_not_handled_as_one_on_one() -> None:
    """WA-87: a message in a WhatsApp group carries `group_id` next to the
    participant's `from`. It must never be processed as that participant's
    1-on-1 message (saved under them, answered privately) -- nor get a read
    receipt -- while the 1-on-1 message in the same webhook still is."""
    message_store = InMemoryNormalizedMessageStore()
    on_message_claimed = AsyncMock()
    receiver = WhatsAppReceiver(
        deduplication_store=InMemoryDeduplicationStore(),
        media_downloader=AsyncMock(),
        message_store=message_store,
        object_storage=FakeObjectStorage(),
        on_message_claimed=on_message_claimed,
    )
    payload = text_webhook_payload()
    value = payload["entry"][0]["changes"][0]["value"]
    group_message = dict(value["messages"][0], id="wamid.group", group_id="120363000000000001")
    value["messages"] = [*value["messages"], group_message]

    scheduled = await receiver.handle_payload(payload)
    await receiver.wait_until_idle()

    assert scheduled == 1
    assert await message_store.get("wamid.group") is None
    assert await message_store.get("wamid.text") is not None
    claimed = [call.args[0] for call in on_message_claimed.await_args_list]
    assert "wamid.group" not in claimed
