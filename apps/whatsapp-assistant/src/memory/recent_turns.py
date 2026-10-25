"""Redis-backed short conversation history (last-N-turns, hard-capped).

Mirrors interactions/pending_report.py's store shape but is append-only up to
a cap rather than single-slot pop-once: "continue", "same place", and "that
one" need to see a short window of what was just said, not only the single
most recent pending item another store already tracks.

Key layout (the client prepends the ``mesiri`` namespace):

    mesiri:user:{user_id}:recent_turns
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

from .requirements import RECENT_TURNS, RECENT_TURNS_MAX_ENTRIES


class _RedisLike(Protocol):
    def namespaced(self, *parts: str) -> str: ...
    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None: ...
    async def get_json(self, key: str) -> Any | None: ...


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """One (what the user said, what Mesiri replied) pair.

    ``user_text`` is the understood text (translated/transcribed), not the
    raw WhatsApp payload -- this feeds later NLU, which never sees raw media.
    """

    user_text: str
    assistant_reply: str
    correlation_id: str
    #: When it was said (epoch seconds); 0 for a turn stored before this existed.
    at: float = 0.0


class RecentTurnsStore:
    """Stores up to RECENT_TURNS_MAX_ENTRIES turns per user, newest last.

    Read-modify-write on a single JSON list under the M1 client's get_json/
    set_json interface (no native list primitive is exposed) -- acceptable
    here because the list is capped tiny (see requirements.py) and a lost
    update under a race just drops one turn from a soft hint, never a
    correctness issue the way losing a workflow_instances row would be.
    """

    def __init__(self, redis: _RedisLike) -> None:
        self._redis = redis

    @staticmethod
    def _key(user_id: str) -> str:
        return f"user:{user_id}:recent_turns"

    async def append(
        self,
        *,
        user_id: str,
        turn: ConversationTurn,
        ttl_seconds: int = RECENT_TURNS.ttl_seconds,
    ) -> None:
        key = self._key(user_id)
        raw = await self._redis.get_json(key)
        turns: list[dict[str, Any]] = list(raw) if isinstance(raw, list) else []
        turns.append(
            {
                "user_text": turn.user_text,
                "assistant_reply": turn.assistant_reply,
                "correlation_id": turn.correlation_id,
                "at": turn.at or time.time(),
            }
        )
        # Keep only the most recent entries -- oldest-first list, so trim
        # from the front once the cap is exceeded.
        turns = turns[-RECENT_TURNS_MAX_ENTRIES:]
        await self._redis.set_json(key, turns, ttl_seconds=ttl_seconds)

    async def recent(self, *, user_id: str) -> tuple[ConversationTurn, ...]:
        raw = await self._redis.get_json(self._key(user_id))
        if not isinstance(raw, list):
            return ()
        return tuple(
            ConversationTurn(
                user_text=str(entry.get("user_text") or ""),
                assistant_reply=str(entry.get("assistant_reply") or ""),
                correlation_id=str(entry.get("correlation_id") or ""),
                at=float(entry.get("at") or 0.0),
            )
            for entry in raw
            if isinstance(entry, dict)
        )
