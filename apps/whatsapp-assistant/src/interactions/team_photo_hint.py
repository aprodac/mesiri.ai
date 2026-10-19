"""Redis-backed "waiting for a team photo" hint.

After attendance is recorded and the promotion offer is settled, Mesiri asks
whether the supervisor wants to attach a photo of the crew. This remembers
WHICH attendance report that offer was about, so the very next photo they
send attaches to it directly -- skipping the "what is this photo for?"
picker, which would be a strange thing to ask about a photo sent in answer to
a question Mesiri itself just posed.

Mirrors interactions/completion_photo_hint.py exactly, including its
"Redis is a hint, never authoritative" stance: a missing or expired hint
must never break the journey. The worst case is that the photo goes through
the normal picker instead, which still works.

Deliberately NOT stored on the attendance record. The record is append-only
(P5) and complete the moment it is confirmed -- whether a photo was later
offered is a fact about the conversation, not about who worked that day.

Key layout (the client prepends the ``mesiri`` namespace):

    mesiri:user:{user_id}:team_photo_hint
"""

from __future__ import annotations

from typing import Any, Protocol

#: Long enough to walk outside, gather the crew and take the picture. Matches
#: the completion-photo hint for the same reason: this is a physical errand,
#: not a reply someone types straight away.
_DEFAULT_TTL_SECONDS = 900  # 15 minutes


class _RedisLike(Protocol):
    def namespaced(self, *parts: str) -> str: ...
    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None: ...
    async def get_json(self, key: str) -> Any | None: ...


class TeamPhotoHintStore:
    """One pending "which attendance report is the next photo for" hint per
    user, consumed at most once."""

    def __init__(self, redis: _RedisLike) -> None:
        self._redis = redis

    @staticmethod
    def _key(user_id: str) -> str:
        return f"user:{user_id}:team_photo_hint"

    async def set_hint(
        self, *, user_id: str, report_id: str, ttl_seconds: int = _DEFAULT_TTL_SECONDS
    ) -> None:
        await self._redis.set_json(
            self._key(user_id), {"report_id": report_id}, ttl_seconds=ttl_seconds
        )

    async def pop_hint(self, *, user_id: str) -> str | None:
        """Read the pending report_id and clear it in the same call.

        Pop-once matters here: without it a photo sent an hour later, meant
        for something else entirely, would silently attach to a closed day's
        attendance.
        """
        key = self._key(user_id)
        raw = await self._redis.get_json(key)
        if not raw or not raw.get("report_id"):
            return None
        await self._redis.set_json(key, {}, ttl_seconds=1)
        return str(raw["report_id"])

    @staticmethod
    def _held_key(user_id: str) -> str:
        return f"user:{user_id}:team_photo_held"

    async def hold(
        self, *, user_id: str, report_id: str, ttl_seconds: int = _DEFAULT_TTL_SECONDS
    ) -> None:
        """Keep the offer back while a multi-part note is still running (it
        is asked once the note finishes -- see pop_held). Separate from the
        live hint so a photo sent meanwhile is not claimed by an offer that
        was never made; the hint written at confirmation is cleared here."""
        await self.clear(user_id=user_id)
        await self._redis.set_json(
            self._held_key(user_id), {"report_id": report_id}, ttl_seconds=ttl_seconds
        )

    async def pop_held(self, *, user_id: str) -> str | None:
        """The held report id, cleared in the same call; None if nothing is held."""
        key = self._held_key(user_id)
        raw = await self._redis.get_json(key)
        if not raw or not raw.get("report_id"):
            return None
        await self._redis.set_json(key, {}, ttl_seconds=1)
        return str(raw["report_id"])

    async def clear(self, *, user_id: str) -> None:
        """Drop the hint without acting on it -- used when the supervisor
        taps Skip, so a photo they send later for some other purpose is not
        quietly swallowed by an offer they already declined."""
        await self._redis.set_json(self._key(user_id), {}, ttl_seconds=1)
