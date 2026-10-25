"""Saves waiting for the site answer ([111], SIT-02).

A save the sender made without a site (and with no site for today) is not
saved: they are asked "Which site is this for?". If they send another update
before they answer, that one is asked too -- and the question is replaced, so
the first update was lost (live 25 Oct: "5 mason vannu", then "10 bags cement
used", then the tap on Site B saved only the cement).

Every save call that ends in the site question is kept here, per sender
(Redis, like the card and the still-to-do list), in the order it came. The
answer -- a tap, or the name typed -- releases them all, in order, at that
site, onto one card (toolbox.py ``_release_site_queue``).
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("mesiri.agent")

#: Most saves held for one answer; the rest are told to wait.
MAX_WAITING = 10


class SiteWaitStore:
    """Per sender, the save calls waiting on the site answer."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    @staticmethod
    def _key(actor: Any) -> str | None:
        org = getattr(actor, "organization_id", None)
        user = getattr(actor, "user_id", None)
        return f"{org}:user:{user}:agent_site_wait" if org and user else None

    async def get(self, actor: Any) -> list[dict[str, Any]]:
        key = self._key(actor)
        if key is None:
            return []
        try:
            raw = await self._redis.get_json(key)
        except Exception:  # noqa: BLE001 -- an empty queue is the safe answer
            _log.warning("agent.site_wait_read_failed", exc_info=True)
            return []
        return [r for r in raw or [] if isinstance(r, dict) and r.get("tool") and isinstance(r.get("args"), dict)]

    async def put(self, actor: Any, items: list[dict[str, Any]]) -> None:
        key = self._key(actor)
        if key is None:
            return
        try:
            if items:
                from .later import _ttl

                await self._redis.set_json(key, items, ttl_seconds=_ttl(actor))
            else:
                await self._redis.delete(self._redis.namespaced(key))
        except Exception:  # noqa: BLE001 -- the model still sees the history
            _log.warning("agent.site_wait_write_failed", exc_info=True)
