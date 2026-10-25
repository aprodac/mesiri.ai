"""Unit tests for PendingMediaStore — in-memory fake, no real Redis needed.

Mirrors test_pending_report.py's pattern exactly. #2 Batch Media: the store
now holds a BATCH per user (was: one message), so these cover accumulation,
the cap, and pop-once-for-the-whole-batch alongside the original scoping
guarantees.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from interactions.pending_media import MAX_BATCH_SIZE, PendingMediaStore
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import (
    MediaReference,
    NormalizedMessage,
    SenderInfo,
)

USR = "22222222-2222-4222-8222-222222222222"


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, datetime | None]] = {}

    def namespaced(self, *parts: str) -> str:
        return ":".join(parts)

    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        expires = (
            datetime.now(UTC) + timedelta(seconds=ttl_seconds) if ttl_seconds is not None else None
        )
        self._store[key] = (value, expires)

    async def get_json(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires = entry
        if expires is not None and expires <= datetime.now(UTC):
            return None
        return value


def _image_message(message_id: str = "wamid.1") -> NormalizedMessage:
    return NormalizedMessage(
        message_id=message_id,
        correlation_id="cor_1",
        sender=SenderInfo(wa_id="919000000000", profile_name="Ravi"),
        timestamp=datetime(2026, 7, 25, 10, 0, tzinfo=UTC),
        modality=InputModality.IMAGE,
        media=MediaReference(
            object_key=f"media/{message_id}/abc123", mime_type="image/jpeg", size_bytes=1024
        ),
    )


async def test_pop_batch_returns_empty_list_when_nothing_was_added():
    store = PendingMediaStore(_FakeRedis())
    assert await store.pop_batch(user_id=USR) == []


async def test_add_then_pop_returns_the_message_with_media_intact():
    store = PendingMediaStore(_FakeRedis())
    await store.add_pending(user_id=USR, message=_image_message())
    restored = await store.pop_batch(user_id=USR)
    assert len(restored) == 1
    assert restored[0].modality is InputModality.IMAGE
    assert restored[0].media is not None
    assert restored[0].media.object_key == "media/wamid.1/abc123"


async def test_pop_is_consume_once():
    store = PendingMediaStore(_FakeRedis())
    await store.add_pending(user_id=USR, message=_image_message())
    await store.pop_batch(user_id=USR)
    assert await store.pop_batch(user_id=USR) == []


async def test_pending_media_is_scoped_per_user():
    store = PendingMediaStore(_FakeRedis())
    await store.add_pending(user_id=USR, message=_image_message())
    assert await store.pop_batch(user_id="usr_other") == []
    assert await store.pop_batch(user_id=USR) != []


async def test_first_add_is_a_new_batch_subsequent_adds_are_not():
    store = PendingMediaStore(_FakeRedis())
    first = await store.add_pending(user_id=USR, message=_image_message("wamid.1"))
    second = await store.add_pending(user_id=USR, message=_image_message("wamid.2"))

    assert first.is_new_batch is True
    assert first.batch_size == 1
    assert second.is_new_batch is False
    assert second.batch_size == 2


async def test_batch_accumulates_all_photos_until_popped():
    store = PendingMediaStore(_FakeRedis())
    for i in range(5):
        await store.add_pending(user_id=USR, message=_image_message(f"wamid.{i}"))

    batch = await store.pop_batch(user_id=USR)
    assert len(batch) == 5
    assert {m.media.object_key for m in batch} == {f"media/wamid.{i}/abc123" for i in range(5)}


async def test_batch_is_capped_and_says_so_once_for_the_first_photo_over():
    """PHO-09: the cap note was sent for every photo past the cap (6 times for
    25 photos). It is said once, for the first one that did not fit."""
    store = PendingMediaStore(_FakeRedis())
    for i in range(MAX_BATCH_SIZE):
        result = await store.add_pending(user_id=USR, message=_image_message(f"wamid.{i}"))
        assert result.capped is False  # the 20th fits: nothing to say yet
    assert result.batch_size == MAX_BATCH_SIZE

    first_over = await store.add_pending(user_id=USR, message=_image_message("wamid.over1"))
    assert (first_over.capped, first_over.batch_size) == (True, MAX_BATCH_SIZE)
    for i in range(2, 6):
        again = await store.add_pending(user_id=USR, message=_image_message(f"wamid.over{i}"))
        assert again.capped is False and again.batch_size == MAX_BATCH_SIZE

    batch = await store.pop_batch(user_id=USR)
    assert len(batch) == MAX_BATCH_SIZE  # the extras were not squeezed in
    # a new batch starts clean: its first overflow is announced again
    for i in range(MAX_BATCH_SIZE + 1):
        result = await store.add_pending(user_id=USR, message=_image_message(f"wamid.n{i}"))
    assert result.capped is True


async def test_has_pending_reflects_batch_presence():
    store = PendingMediaStore(_FakeRedis())
    assert await store.has_pending(user_id=USR) is False
    await store.add_pending(user_id=USR, message=_image_message())
    assert await store.has_pending(user_id=USR) is True
    await store.pop_batch(user_id=USR)
    assert await store.has_pending(user_id=USR) is False
