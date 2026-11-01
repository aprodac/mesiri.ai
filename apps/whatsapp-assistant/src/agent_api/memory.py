"""WA-124: what the API agent remembers of a person: today and the two days before.

The conversation is kept in the day store v2-on-ADK already uses (``assistant_sessions`` /
``assistant_session_events``, migration 0496, ``agent_v2.adk.memory.PostgresSessionService``):
one session per person per day, under this agent's own app name so the two never mix. Each
turn is two events: what the person said and what Mesiri sent (with the ready list).

Read before the model runs (one query per day, the three in parallel); written after the reply
is sent, so it never adds to the time the person waits. Without google-adk installed the same
turns are kept in Redis per day instead.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from mesiri_ai.models import ChatMessage

_log = logging.getLogger(__name__)

APP_NAME = "mesiri_api"
#: Today in full (up to this many messages); the days before, their last turns.
TODAY_MESSAGES = 120
EARLIER_MESSAGES = 30
EARLIER_DAYS = 2
USER, MODEL = "user", "mesiri"


def _days(timezone: str | None, now: dt.datetime | None = None) -> list[dt.date]:
    """Oldest first: the two days before, then today (the site's own time zone)."""
    today = (now or dt.datetime.now(ZoneInfo(timezone or "Asia/Kolkata"))).date()
    return [today - dt.timedelta(days=n) for n in range(EARLIER_DAYS, -1, -1)]


def _marker(text: str) -> list[ChatMessage]:
    return [ChatMessage(role="user", text=text), ChatMessage(role="model", text="(noted)")]


class DayMemory:
    def __init__(self, sessions: Any | None, redis: Any) -> None:
        self._sessions = sessions
        self._redis = redis

    @staticmethod
    def _user(ctx: Any) -> str:
        return f"{ctx.organization_id}:{ctx.user_id}"

    async def load(self, ctx: Any) -> list[ChatMessage]:
        days = _days(getattr(ctx, "timezone", None))
        turns = await asyncio.gather(*(self._day(ctx, day, day == days[-1]) for day in days))
        messages: list[ChatMessage] = []
        for day, said in zip(days, turns, strict=True):
            if not said:
                continue
            if day != days[-1]:
                # Mark an earlier day, so "the cement" of two days ago is not taken as today's.
                messages += _marker(f"(conversation of {day:%A %d %b}, an earlier day)")
            elif messages:
                messages += _marker(f"(today, {day:%A %d %b})")
            messages.extend(said)
        return messages

    async def _day(self, ctx: Any, day: dt.date, today: bool) -> list[ChatMessage]:
        limit = TODAY_MESSAGES if today else EARLIER_MESSAGES
        try:
            if self._sessions is not None:
                from google.adk.sessions.base_session_service import GetSessionConfig

                session = await self._sessions.get_session(
                    app_name=APP_NAME, user_id=self._user(ctx), session_id=day.isoformat(),
                    config=GetSessionConfig(num_recent_events=limit),
                )
                events = session.events if session else []
                return [
                    ChatMessage(role="user" if e.author == USER else "model",
                                text="".join(p.text or "" for p in (e.content.parts or [])) if e.content else "")
                    for e in events
                ]
            stored = await self._redis.get_json(self._redis_key(ctx, day)) or []
            return [ChatMessage(role=t["role"], text=t["text"]) for t in stored[-limit:]]
        except Exception:  # noqa: BLE001 -- a day it cannot read is a day it does not remember
            _log.warning("agent_api.memory_unreadable user=%s day=%s", ctx.user_id, day, exc_info=True)
            return []

    async def remember(self, ctx: Any, said: str, sent: str) -> None:
        day = _days(getattr(ctx, "timezone", None))[-1]
        try:
            if self._sessions is not None:
                await self._remember_session(ctx, day, said, sent)
                return
            key = self._redis_key(ctx, day)
            stored = await self._redis.get_json(key) or []
            stored += [{"role": "user", "text": said}, {"role": "model", "text": sent}]
            await self._redis.set_json(key, stored[-TODAY_MESSAGES:], ttl_seconds=(EARLIER_DAYS + 2) * 86400)
        except Exception:  # noqa: BLE001 -- memory never breaks a reply that was already sent
            _log.warning("agent_api.memory_unsaved user=%s", ctx.user_id, exc_info=True)

    async def _remember_session(self, ctx: Any, day: dt.date, said: str, sent: str) -> None:
        from google.adk.events import Event
        from google.genai import types

        user = self._user(ctx)
        session = await self._sessions.get_session(app_name=APP_NAME, user_id=user, session_id=day.isoformat())
        if session is None:
            session = await self._sessions.create_session(app_name=APP_NAME, user_id=user, session_id=day.isoformat())
        invocation = f"inv-{uuid.uuid4().hex[:12]}"
        for author, role, text in ((USER, "user", said), (MODEL, "model", sent)):
            await self._sessions.append_event(session, Event(
                invocation_id=invocation, author=author, timestamp=time.time(),
                content=types.Content(role=role, parts=[types.Part(text=text)]),
            ))

    def _redis_key(self, ctx: Any, day: dt.date) -> str:
        return f"agent_api_day:{ctx.organization_id}:{ctx.user_id}:{day.isoformat()}"
