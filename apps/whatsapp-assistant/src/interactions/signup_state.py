"""Redis-backed progress of a WhatsApp signup (SS-04).

An unknown number that taps "Start free trial" answers a few questions
before a company exists, so there is no user id yet: the state is keyed by
the WhatsApp number. Same "Redis is a hint, never authoritative" stance as
interactions/project_setup_offer.py: lost or expired state just means the
signup starts again from the welcome message. Nothing is created until the
last answer, so an abandoned signup leaves nothing behind.

Key layout (the client prepends the ``mesiri`` namespace):
    mesiri:signup:{wa_id}
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

#: A day: an owner may start on a site and finish in the evening.
_DEFAULT_TTL_SECONDS = 24 * 60 * 60

SignupStage = Literal["welcome", "company", "site", "owner_name"]
_STAGES: frozenset[str] = frozenset({"welcome", "company", "site", "owner_name"})


@dataclass(frozen=True, slots=True)
class SignupState:
    stage: SignupStage
    company_name: str | None = None
    site_name: str | None = None


class _RedisLike(Protocol):
    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None: ...
    async def get_json(self, key: str) -> Any | None: ...


class SignupStateStore:
    def __init__(self, redis: _RedisLike) -> None:
        self._redis = redis

    @staticmethod
    def _key(wa_id: str) -> str:
        return f"signup:{wa_id}"

    async def get(self, wa_id: str) -> SignupState | None:
        raw = await self._redis.get_json(self._key(wa_id))
        if not isinstance(raw, dict) or raw.get("stage") not in _STAGES:
            return None
        return SignupState(
            stage=raw["stage"],
            company_name=raw.get("company_name"),
            site_name=raw.get("site_name"),
        )

    async def set(
        self, wa_id: str, state: SignupState, *, ttl_seconds: int = _DEFAULT_TTL_SECONDS
    ) -> None:
        await self._redis.set_json(self._key(wa_id), asdict(state), ttl_seconds=ttl_seconds)

    async def clear(self, wa_id: str) -> None:
        # Overwritten rather than deleted: FakeRedis.delete doesn't apply the
        # namespace, and a short-lived null reads as "no signup" either way.
        await self._redis.set_json(self._key(wa_id), None, ttl_seconds=60)
