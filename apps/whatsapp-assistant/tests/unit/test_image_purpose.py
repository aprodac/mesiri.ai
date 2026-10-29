"""interactions/image_purpose.py — unit tests (fake store, no real Redis).

#2 Batch Media: a burst of photos must get exactly ONE picker, not one per
photo -- covered here alongside the original single-photo/non-image cases.
"""

from __future__ import annotations

from datetime import UTC, datetime

from interactions.image_purpose import try_hold_new_image_for_purpose_picker
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
        self._store: dict[str, object] = {}

    def namespaced(self, *parts: str) -> str:
        return ":".join(parts)

    async def set_json(self, key: str, value, *, ttl_seconds=None) -> None:
        self._store[key] = value

    async def get_json(self, key: str):
        return self._store.get(key)


def _message(
    modality: InputModality, text: str | None = None, message_id: str = "wamid.1"
) -> NormalizedMessage:
    return NormalizedMessage(
        message_id=message_id,
        correlation_id="cor_1",
        sender=SenderInfo(wa_id="919000000000", profile_name="Ravi"),
        timestamp=datetime(2026, 7, 25, 10, 0, tzinfo=UTC),
        modality=modality,
        text=text,
        media=MediaReference(
            object_key=f"media/{message_id}/abc123", mime_type="image/jpeg", size_bytes=1024
        )
        if modality is InputModality.IMAGE
        else None,
    )


async def test_new_image_is_held_and_returns_the_picker():
    store = PendingMediaStore(_FakeRedis())

    reply = await try_hold_new_image_for_purpose_picker(
        _message(InputModality.IMAGE), user_id=USR, pending_media_store=store
    )

    assert reply is not None
    assert "photo" in reply.text.lower()
    assert reply.list_rows is not None
    row_ids = {row.id for row in reply.list_rows}
    assert row_ids == {
        "img_material_invoice",
        "img_expense",
        "img_attendance",
        "img_site_update",
    }

    held = await store.pop_batch(user_id=USR)
    assert len(held) == 1
    assert held[0].media.object_key == "media/wamid.1/abc123"


async def test_text_message_is_ignored():
    store = PendingMediaStore(_FakeRedis())
    reply = await try_hold_new_image_for_purpose_picker(
        _message(InputModality.TEXT, text="spent 250 on fuel"), user_id=USR, pending_media_store=store
    )
    assert reply is None
    assert await store.pop_batch(user_id=USR) == []


async def test_interactive_tap_is_ignored():
    """A tap answering the picker is InputModality.INTERACTIVE, not IMAGE --
    it must never re-trigger the hold gate."""
    store = PendingMediaStore(_FakeRedis())
    reply = await try_hold_new_image_for_purpose_picker(
        _message(InputModality.INTERACTIVE), user_id=USR, pending_media_store=store
    )
    assert reply is None


async def test_a_burst_of_photos_gets_exactly_one_picker():
    store = PendingMediaStore(_FakeRedis())

    first = await try_hold_new_image_for_purpose_picker(
        _message(InputModality.IMAGE, message_id="wamid.1"), user_id=USR, pending_media_store=store
    )
    second = await try_hold_new_image_for_purpose_picker(
        _message(InputModality.IMAGE, message_id="wamid.2"), user_id=USR, pending_media_store=store
    )
    third = await try_hold_new_image_for_purpose_picker(
        _message(InputModality.IMAGE, message_id="wamid.3"), user_id=USR, pending_media_store=store
    )

    assert first is not None  # the picker
    assert second is None  # silently appended
    assert third is None  # silently appended

    held = await store.pop_batch(user_id=USR)
    assert len(held) == 3
    assert {m.message_id for m in held} == {"wamid.1", "wamid.2", "wamid.3"}


async def test_exceeding_the_cap_replies_with_an_honest_note_once():
    store = PendingMediaStore(_FakeRedis())
    for i in range(MAX_BATCH_SIZE):
        await try_hold_new_image_for_purpose_picker(
            _message(InputModality.IMAGE, message_id=f"wamid.{i}"),
            user_id=USR,
            pending_media_store=store,
        )

    overflow_reply = await try_hold_new_image_for_purpose_picker(
        _message(InputModality.IMAGE, message_id="wamid.overflow"),
        user_id=USR,
        pending_media_store=store,
    )

    assert overflow_reply is not None
    assert str(MAX_BATCH_SIZE) in overflow_reply.text
    assert overflow_reply.list_rows is None  # a note, not another picker

    held = await store.pop_batch(user_id=USR)
    assert len(held) == MAX_BATCH_SIZE


async def test_pho09_twenty_five_photos_get_one_cap_note_not_six():
    store = PendingMediaStore(_FakeRedis())
    replies = []
    for i in range(25):
        replies.append(
            await try_hold_new_image_for_purpose_picker(
                _message(InputModality.IMAGE, message_id=f"wamid.{i}"), user_id=USR, pending_media_store=store
            )
        )
    notes = [r for r in replies if r is not None and not r.list_rows]
    pickers = [r for r in replies if r is not None and r.list_rows]
    assert len(pickers) == 1 and len(notes) == 1
    assert "not kept" in notes[0].text and str(MAX_BATCH_SIZE) in notes[0].text
    assert len(await store.pop_batch(user_id=USR)) == MAX_BATCH_SIZE


HOUR = 3600.0


async def test_pho06_untapped_photos_are_reminded_about_once_then_said_to_be_dropped():
    from interactions.image_purpose import (
        DROP_AFTER_SECONDS,
        REMIND_AFTER_SECONDS,
        photo_wait_notice,
    )

    store = PendingMediaStore(_FakeRedis())
    t0 = 1_000_000.0
    await store.add_pending(user_id=USR, message=_message(InputModality.IMAGE, message_id="wamid.1"), now=t0)
    await store.add_pending(user_id=USR, message=_message(InputModality.IMAGE, message_id="wamid.2"), now=t0 + 30)

    async def notice(at: float):
        return await photo_wait_notice(user_id=USR, pending_media_store=store, now=at)

    assert await notice(t0 + 60) is None  # too soon: nothing to say
    reminder = await notice(t0 + REMIND_AFTER_SECONDS + 1)
    assert reminder is not None and "2 photos" in reminder.text and reminder.list_rows  # asked again, once
    assert await notice(t0 + REMIND_AFTER_SECONDS + 60) is None  # not nagged again
    dropped = await notice(t0 + REMIND_AFTER_SECONDS + 1 + DROP_AFTER_SECONDS)
    assert dropped is not None and "were not kept" in dropped.text and "2 photos" in dropped.text
    assert await store.pop_batch(user_id=USR) == []  # and they are gone
    assert await notice(t0 + 10 * HOUR) is None  # nothing held, nothing said


async def test_pho06_a_tap_in_time_still_gets_the_photos_and_clears_the_notice():
    from interactions.image_purpose import photo_wait_notice

    store = PendingMediaStore(_FakeRedis())
    await store.add_pending(user_id=USR, message=_message(InputModality.IMAGE), now=0.0)
    assert len(await store.pop_batch(user_id=USR)) == 1
    assert await photo_wait_notice(user_id=USR, pending_media_store=store, now=99999.0) is None


def test_pho07_a_caption_that_names_the_purpose_skips_the_question():
    from interactions.image_purpose import purpose_from_caption

    assert purpose_from_caption("cement bill 50 bags") == "img_material_invoice"
    assert purpose_from_caption("Challan - Sharma Traders") == "img_material_invoice"
    assert purpose_from_caption("attendance register today") == "img_attendance"
    assert purpose_from_caption("2nd floor plastering") == "img_site_update"
    assert purpose_from_caption("Slab shuttering done!") == "img_site_update"
    # nothing named, or two things named: asked
    assert purpose_from_caption(None) is None
    assert purpose_from_caption("look at this") is None
    assert purpose_from_caption("cement bill for plastering") is None
    assert purpose_from_caption("the billing office") is None  # whole words only


async def test_pho07_the_rest_of_a_captioned_burst_is_not_asked_either():
    store = PendingMediaStore(_FakeRedis())
    assert await store.recent_purpose(user_id=USR, now=100.0) is None
    await store.remember_purpose(user_id=USR, row_id="img_site_update", now=100.0)
    assert await store.recent_purpose(user_id=USR, now=110.0) == "img_site_update"
    assert await store.recent_purpose(user_id=USR, now=200.0) is None  # a later photo is asked
