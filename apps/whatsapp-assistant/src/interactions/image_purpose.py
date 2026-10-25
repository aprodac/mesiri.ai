"""Hold a genuinely new image while asking "what is this photo for?" (#2 Batch Media).

Every image (not a tap answering this very picker) is held via
PendingMediaStore and the picker (channel/replies.IMAGE_PURPOSE_ROWS) is
sent instead of running understanding straight away -- a bare photo often
arrives with no caption saying what it's for, so this replaces relying on
vision analysis to guess (see docs/execution/FINANCE_MODULE_PLAN.md's note
on why that guess isn't reliable enough to be the only signal).

A burst of photos (the common case -- an engineer photographing 10 finished
bays in a row) accumulates into ONE batch: the picker is sent only for the
first photo of a fresh batch (PendingMediaStore.add_pending's
is_new_batch=True); every subsequent photo in the same burst is appended
silently (returns None here, same as any other fall-through), so the user
never sees the same picker 10 times in a row.

Kept as a standalone function (not an InteractionHandler method) because it
needs PendingMediaStore, mirroring how the project/site pending-report gates
(runtime/inbound_journey.py's _run_project_gate/_run_site_gate) are plain
functions taking their store as a parameter rather than methods on
InteractionHandler -- InteractionHandler's own fast-path methods are either
I/O-free or only ever touch WorkflowRuntime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from channel.replies import ReplySpec, render_image_purpose_picker
from mesiri_contracts.assistant.enums import InputModality

if TYPE_CHECKING:
    from mesiri_contracts.assistant.normalized_message import NormalizedMessage

    from .pending_media import PendingMediaStore


#: PHO-07: caption words that name what a photo is. A caption that names more
#: than one purpose ("cement bill for plastering") is not guessed: it is asked.
_PURPOSE_WORDS: dict[str, tuple[str, ...]] = {
    "img_material_invoice": (
        "bill", "bills", "challan", "chalan", "invoice", "delivery note", "delivery challan",
    ),
    "img_attendance": ("attendance", "register", "hajari", "muster", "roll call"),
    "img_expense": ("expense", "expenses"),
    "img_site_update": (
        "site update", "progress", "work done", "plastering", "brickwork", "bricks", "concreting",
        "concrete", "slab", "shuttering", "centering", "painting", "tiling", "flooring", "wiring",
        "plumbing", "excavation", "foundation", "waterproofing", "putty", "floor",
    ),
}


def purpose_from_caption(caption: str | None) -> str | None:
    """The picker row a photo's caption names ("cement bill 50 bags" ->
    img_material_invoice, "2nd floor plastering" -> img_site_update), or None
    when it names none or several, or the purpose's module is off."""
    import re

    from channel.replies import IMAGE_PURPOSE_MODULE
    from workflows.registry import module_is_enabled

    text = " ".join(re.sub(r"[^\w\s]", " ", (caption or "").casefold()).split())
    if not text:
        return None
    named = [
        row_id
        for row_id, words in _PURPOSE_WORDS.items()
        if any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text) for word in words)
    ]
    if len(named) != 1:
        return None
    row_id = named[0]
    return row_id if module_is_enabled(IMAGE_PURPOSE_MODULE.get(row_id)) else None


async def try_hold_new_image_for_purpose_picker(
    message: NormalizedMessage, *, user_id: str, pending_media_store: PendingMediaStore
) -> ReplySpec | None:
    """Returns None for anything that isn't image modality (so the caller
    falls through to the normal journey unchanged for every other modality,
    including a tap answering this exact picker, which is
    InputModality.INTERACTIVE, not IMAGE) OR for an image silently appended
    to an already-open batch."""
    if message.modality is not InputModality.IMAGE:
        return None
    result = await pending_media_store.add_pending(user_id=user_id, message=message)
    if result.capped:
        # Said once per batch (PHO-09), for the first photo that did not fit.
        return ReplySpec(
            text=(
                f"📷 I'm holding {result.batch_size} photos, which is as many as I can take at "
                "once, so the ones after them were not kept. Tell me what these are for, "
                "then send the rest."
            )
        )
    if not result.is_new_batch:
        return None
    return render_image_purpose_picker()


#: PHO-06: how long photos may wait for the question to be answered before the
#: next message reminds the sender (once), and how long after the reminder
#: before they are dropped and the sender is told.
REMIND_AFTER_SECONDS = 5 * 60
DROP_AFTER_SECONDS = 30 * 60


async def photo_wait_notice(
    *, user_id: str, pending_media_store: PendingMediaStore, now: float | None = None
) -> ReplySpec | None:
    """Photos nobody said the purpose of never vanish silently (PHO-06): the
    first message from the sender 5 minutes or more after they were held gets a
    reminder with the question again; once more than 30 minutes have passed
    since the reminder, the next message is told they were not kept. Event
    driven (it runs on the sender's next message), so a sender who never writes
    again is not told."""
    import time

    try:
        count, meta = await pending_media_store.waiting(user_id=user_id)
    except Exception:  # noqa: BLE001 -- a reminder is a nicety: never in the way of the message
        return None
    if not count or not isinstance(meta, dict):
        return None
    moment = time.time() if now is None else now
    noun = "photo" if count == 1 else "photos"
    reminded_at = meta.get("reminded_at")
    if reminded_at is None:
        if moment - float(meta.get("held_at") or moment) < REMIND_AFTER_SECONDS:
            return None
        await pending_media_store.mark_reminded(user_id=user_id, now=moment)
        picker = render_image_purpose_picker()
        return ReplySpec(
            text=f"📷 {count} {noun} you sent are still waiting. What {'is it' if count == 1 else 'are they'} for?",
            list_button_label=picker.list_button_label,
            list_rows=picker.list_rows,
        )
    if moment - float(reminded_at) >= DROP_AFTER_SECONDS:
        await pending_media_store.pop_batch(user_id=user_id)
        return ReplySpec(
            text=(
                f"📷 The {count} {noun} I was holding were not kept, because I never learned what "
                "they were for. Please send them again if you still need them."
            )
        )
    return None
