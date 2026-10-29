"""Redis-backed pending media BATCH (#2 Batch Media; short-lived, pop-once).

Engineers often send several photos in one burst (15 progress photos, a
stack of receipts). Every genuinely new image (not a tap answering the
purpose picker) is held here while the user picks what the WHOLE batch is
for -- then all of them are re-processed together once they tap. This used
to hold exactly ONE pending image per user: photo 15 silently overwrote
photos 1-14, and each arrival re-sent its own "what is this for?" picker.
Now a burst accumulates into one batch and the picker is asked exactly once
for it.

Key layout (the client prepends the ``mesiri`` namespace):

    mesiri:user:{user_id}:pending_media
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

from mesiri_contracts.assistant.normalized_message import NormalizedMessage

#: PHO-06: photos nobody has said the purpose of are held for hours, not
#: minutes, so they can be reminded about once and then said to be dropped --
#: they used to vanish after 10 minutes without a word.
_DEFAULT_TTL_SECONDS = 3 * 60 * 60

#: PHO-07: how long a purpose read from a caption covers the photos that follow it.
PURPOSE_BURST_SECONDS = 25

#: Hard cap on one batch. Bounds the Redis payload size and, more
#: importantly, the vision-analysis fan-out a single picker tap can trigger
#: -- a burst of 40 photos is far more likely to be an accidental multi-send
#: than a genuine 40-photo report.
MAX_BATCH_SIZE = 20


class _RedisLike(Protocol):
    def namespaced(self, *parts: str) -> str: ...
    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None: ...
    async def get_json(self, key: str) -> Any | None: ...


@dataclass(frozen=True, slots=True)
class BatchAddResult:
    """What happened when one image was added to the batch.

    ``is_new_batch`` is the caller's signal for whether to send the purpose
    picker (True -- this is the first image of a fresh batch) or stay
    silent (False -- a picker is already pending for this batch; the photo
    was just appended to it). ``capped`` is True exactly once per batch: for
    the first photo that did NOT fit (PHO-09: the "20 photos held" note used
    to be sent for every one of them) -- the caller sends one honest "that's
    as many as I can hold at once" note, not one per rejected photo.
    """

    is_new_batch: bool
    batch_size: int
    capped: bool


class PendingMediaStore:
    """Stores a batch of pending NormalizedMessages (images) per user,
    consumed at most once as a whole."""

    def __init__(self, redis: _RedisLike) -> None:
        self._redis = redis

    @staticmethod
    def _key(user_id: str) -> str:
        return f"user:{user_id}:pending_media"

    @staticmethod
    def _meta_key(user_id: str) -> str:
        return f"user:{user_id}:pending_media_meta"

    async def add_pending(
        self,
        *,
        user_id: str,
        message: NormalizedMessage,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        now: float | None = None,
    ) -> BatchAddResult:
        """Append one image to the user's batch, starting a fresh one if
        none is pending. TTL is refreshed on every add -- a burst spread
        over several minutes must not have its earliest photos expire out
        from under it while later ones are still arriving."""
        key = self._key(user_id)
        raw = await self._redis.get_json(key)
        batch: list[dict[str, Any]] = list(raw) if isinstance(raw, list) else []
        is_new_batch = not batch
        meta = await self._meta(user_id) if not is_new_batch else {}
        stamp = time.time() if now is None else now

        if len(batch) >= MAX_BATCH_SIZE:
            # Already full -- this image is not kept, and the caller is told so
            # exactly once (the first one over), not once per photo.
            overflow = int(meta.get("overflow") or 0) + 1
            await self._redis.set_json(
                self._meta_key(user_id), {**meta, "overflow": overflow}, ttl_seconds=ttl_seconds
            )
            return BatchAddResult(is_new_batch=False, batch_size=len(batch), capped=overflow == 1)

        batch.append(message.model_dump(mode="json"))
        await self._redis.set_json(key, batch, ttl_seconds=ttl_seconds)
        if is_new_batch:
            meta = {"held_at": stamp, "reminded_at": None, "overflow": 0}
        await self._redis.set_json(self._meta_key(user_id), meta, ttl_seconds=ttl_seconds)
        return BatchAddResult(is_new_batch=is_new_batch, batch_size=len(batch), capped=False)

    async def _meta(self, user_id: str) -> dict[str, Any]:
        raw = await self._redis.get_json(self._meta_key(user_id))
        return dict(raw) if isinstance(raw, dict) else {}

    async def waiting(self, *, user_id: str) -> tuple[int, dict[str, Any]]:
        """(how many photos are held, when they were: ``held_at`` / ``reminded_at``
        / ``overflow``). (0, {}) when nothing is held."""
        raw = await self._redis.get_json(self._key(user_id))
        count = len(raw) if isinstance(raw, list) else 0
        return (count, await self._meta(user_id)) if count else (0, {})

    @staticmethod
    def _purpose_key(user_id: str) -> str:
        return f"user:{user_id}:photo_purpose"

    async def remember_purpose(self, *, user_id: str, row_id: str, now: float | None = None) -> None:
        """PHO-07: a caption said what this photo is; the rest of its burst
        (an album sends the caption on one photo) is the same, for a few seconds."""
        stamp = time.time() if now is None else now
        await self._redis.set_json(
            self._purpose_key(user_id), {"row_id": row_id, "at": stamp}, ttl_seconds=PURPOSE_BURST_SECONDS
        )

    async def recent_purpose(self, *, user_id: str, now: float | None = None) -> str | None:
        raw = await self._redis.get_json(self._purpose_key(user_id))
        if not isinstance(raw, dict) or not raw.get("row_id"):
            return None
        stamp = time.time() if now is None else now
        return str(raw["row_id"]) if stamp - float(raw.get("at") or 0) <= PURPOSE_BURST_SECONDS else None

    async def mark_reminded(self, *, user_id: str, now: float | None = None) -> None:
        meta = await self._meta(user_id)
        if meta:
            meta["reminded_at"] = time.time() if now is None else now
            await self._redis.set_json(self._meta_key(user_id), meta, ttl_seconds=_DEFAULT_TTL_SECONDS)

    async def pop_batch(self, *, user_id: str) -> list[NormalizedMessage]:
        """Read the whole pending batch and clear it in the same call -- a
        stale or expired batch must never resurrect later. Empty list (not
        None) when nothing is pending, since "no photos" and "batch
        expired" both mean the same thing to every caller: nothing to
        process."""
        key = self._key(user_id)
        raw = await self._redis.get_json(key)
        if not raw:
            return []
        await self._redis.set_json(key, [], ttl_seconds=1)
        await self._redis.set_json(self._meta_key(user_id), {}, ttl_seconds=1)
        return [NormalizedMessage.model_validate(item) for item in raw]

    async def peek(self, *, user_id: str) -> list[NormalizedMessage]:
        """The held photos, left held (``pop_batch`` clears them). Empty when none."""
        raw = await self._redis.get_json(self._key(user_id))
        if not isinstance(raw, list):
            return []
        return [NormalizedMessage.model_validate(item) for item in raw]

    async def has_pending(self, *, user_id: str) -> bool:
        """Non-destructive presence check -- for callers (memory/context_loader.py)
        that need to know *whether* a batch is held without consuming it."""
        raw = await self._redis.get_json(self._key(user_id))
        return bool(raw)
