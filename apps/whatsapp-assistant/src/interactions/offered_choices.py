"""The choices on the last reply, so a typed answer works like a tap.

A worker who types "undo", "photo", "skip", an option's title or its number
instead of tapping a button is not left stuck (request [45]). The composed
reply (runtime/reply_composer.py) records its options here; the journey checks
the next text message against them (runtime/reply_composer.resolve_choice) and
treats a match as the tap. Any other message clears them, so a stale "2" can
never be read as a choice later.

Redis is a hint, never authoritative: a miss just means the typed word is
handled the way it was before this existed.

Key: mesiri:user:{user_id}:offered_choices
"""

from __future__ import annotations

from typing import Any, Protocol

from channel.replies import ListRow

_TTL_SECONDS = 30 * 60


class _RedisLike(Protocol):
    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None: ...
    async def get_json(self, key: str) -> Any | None: ...


class OfferedChoicesStore:
    def __init__(self, redis: _RedisLike) -> None:
        self._redis = redis

    @staticmethod
    def _key(user_id: str) -> str:
        return f"user:{user_id}:offered_choices"

    async def remember(self, *, user_id: str, rows: list[ListRow]) -> None:
        await self._redis.set_json(
            self._key(user_id),
            {"rows": [{"id": r.id, "title": r.title} for r in rows]},
            ttl_seconds=_TTL_SECONDS,
        )

    async def take(self, *, user_id: str) -> list[ListRow]:
        """The remembered choices, cleared in the same call."""
        key = self._key(user_id)
        raw = await self._redis.get_json(key)
        if not raw or not raw.get("rows"):
            return []
        await self._redis.set_json(key, {}, ttl_seconds=1)
        return [ListRow(str(r["id"]), str(r["title"])) for r in raw["rows"]]
