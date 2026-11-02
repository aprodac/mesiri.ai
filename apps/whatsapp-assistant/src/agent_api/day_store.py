"""The Postgres day store behind the API agent's memory (request 185; kept for v3 by WA-134).

An ADK ``BaseSessionService``: one session per person per day, ``user_id`` =
``<organization>:<user>``, ``session_id`` = ``<YYYY-MM-DD>``, under the caller's app name
(``agent_api.memory.APP_NAME``). What goes into a day is decided by ``agent_api.memory``.

``PostgresSessionService``: tables ``assistant_sessions`` / ``assistant_session_events``
(migration 0496), through the same ``PostgresDatabase.transaction()`` the draft store uses.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from google.adk.events import Event
from google.adk.sessions import Session
from google.adk.sessions.base_session_service import (
    BaseSessionService,
    GetSessionConfig,
    ListSessionsResponse,
)


def _organization(user_id: str) -> str:
    """The company of a session's ``<org>:<user>`` key (the row-level-security column)."""
    return user_id.split(":", 1)[0]


def _event_json(event: Event) -> str:
    return event.model_dump_json(exclude_none=True, by_alias=False)


class PostgresSessionService(BaseSessionService):
    """ADK sessions in Mesiri's Postgres (``db`` is ``PostgresDatabase``)."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def create_session(
        self, *, app_name: str, user_id: str, state: dict[str, Any] | None = None, session_id: str | None = None
    ) -> Session:
        from sqlalchemy import text

        session_id = session_id or uuid.uuid4().hex
        now = time.time()
        async with self._db.transaction() as conn:
            await conn.execute(
                text(
                    "INSERT INTO assistant_sessions (app_name, user_id, session_id, organization_id, state) "
                    "VALUES (:app, :user, :sid, CAST(:org AS uuid), CAST(:state AS jsonb)) ON CONFLICT DO NOTHING"
                ),
                {
                    "app": app_name, "user": user_id, "sid": session_id, "org": _organization(user_id),
                    "state": json.dumps(state or {}),
                },
            )
        return Session(id=session_id, app_name=app_name, user_id=user_id, state=dict(state or {}), last_update_time=now)

    async def get_session(
        self, *, app_name: str, user_id: str, session_id: str, config: GetSessionConfig | None = None
    ) -> Session | None:
        from sqlalchemy import text

        limit = config.num_recent_events if config and config.num_recent_events is not None else None
        after = config.after_timestamp if config and config.after_timestamp is not None else None
        async with self._db.transaction() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT state, EXTRACT(EPOCH FROM updated_at) AS updated FROM assistant_sessions "
                        "WHERE app_name = :app AND user_id = :user AND session_id = :sid"
                    ),
                    {"app": app_name, "user": user_id, "sid": session_id},
                )
            ).mappings().first()
            if row is None:
                return None
            if limit == 0:
                rows = []
            else:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT event FROM (SELECT event, seq FROM assistant_session_events "
                            "WHERE app_name = :app AND user_id = :user AND session_id = :sid "
                            "AND (CAST(:after AS double precision) IS NULL OR timestamp >= :after) "
                            "ORDER BY seq DESC LIMIT :limit) recent ORDER BY seq"
                        ),
                        {"app": app_name, "user": user_id, "sid": session_id, "after": after, "limit": limit or 10_000},
                    )
                ).mappings().all()
        state = row["state"] if isinstance(row["state"], dict) else json.loads(row["state"] or "{}")
        events = [Event.model_validate(r["event"] if isinstance(r["event"], dict) else json.loads(r["event"])) for r in rows]
        return Session(
            id=session_id, app_name=app_name, user_id=user_id, state=state, events=events,
            last_update_time=float(row["updated"]),
        )

    async def list_sessions(self, *, app_name: str, user_id: str | None = None) -> ListSessionsResponse:
        from sqlalchemy import text

        async with self._db.transaction() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT user_id, session_id, EXTRACT(EPOCH FROM updated_at) AS updated FROM assistant_sessions "
                        "WHERE app_name = :app AND (CAST(:user AS text) IS NULL OR user_id = :user) ORDER BY updated_at"
                    ),
                    {"app": app_name, "user": user_id},
                )
            ).mappings().all()
        return ListSessionsResponse(
            sessions=[
                Session(id=r["session_id"], app_name=app_name, user_id=r["user_id"], last_update_time=float(r["updated"]))
                for r in rows
            ]
        )

    async def delete_session(self, *, app_name: str, user_id: str, session_id: str) -> None:
        from sqlalchemy import text

        async with self._db.transaction() as conn:
            await conn.execute(
                text("DELETE FROM assistant_sessions WHERE app_name = :app AND user_id = :user AND session_id = :sid"),
                {"app": app_name, "user": user_id, "sid": session_id},
            )

    async def append_event(self, session: Session, event: Event) -> Event:
        from sqlalchemy import text

        event = await super().append_event(session, event)
        if event.partial:
            return event
        async with self._db.transaction() as conn:
            await conn.execute(
                text(
                    "INSERT INTO assistant_session_events (app_name, user_id, session_id, organization_id, event_id, "
                    "invocation_id, author, timestamp, event) "
                    "VALUES (:app, :user, :sid, CAST(:org AS uuid), :eid, :inv, :author, :ts, CAST(:event AS jsonb))"
                ),
                {
                    "app": session.app_name, "user": session.user_id, "sid": session.id,
                    "org": _organization(session.user_id), "eid": event.id,
                    "inv": event.invocation_id, "author": event.author, "ts": event.timestamp, "event": _event_json(event),
                },
            )
            await conn.execute(
                text(
                    "UPDATE assistant_sessions SET state = CAST(:state AS jsonb), updated_at = now() "
                    "WHERE app_name = :app AND user_id = :user AND session_id = :sid"
                ),
                {"app": session.app_name, "user": session.user_id, "sid": session.id, "state": json.dumps(session.state, default=str)},
            )
        return event
