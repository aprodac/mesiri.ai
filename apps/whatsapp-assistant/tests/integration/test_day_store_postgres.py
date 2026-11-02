"""The API agent's day store against a real database (migration 0496; request 185, WA-134).

Turns written through ``PostgresSessionService`` are read back whole and in order by a fresh
service (another worker), the newest-events limit keeps the newest, and a company's rows go
when the company goes. (Until WA-134 this drove v2's ADK runner; the store is unchanged.)

    pytest apps/whatsapp-assistant/tests/integration/test_day_store_postgres.py -m integration
"""

from __future__ import annotations

import time
import uuid

import pytest

pytest.importorskip("google.adk")

from google.adk.events import Event  # noqa: E402
from google.adk.sessions.base_session_service import GetSessionConfig  # noqa: E402
from google.genai import types  # noqa: E402
from sqlalchemy import text  # noqa: E402

from agent_api.day_store import PostgresSessionService  # noqa: E402
from agent_api.memory import APP_NAME  # noqa: E402
from mesiri.bootstrap.settings import Settings  # noqa: E402
from mesiri.infrastructure.postgres.database import PostgresDatabase  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.fixture
async def db():
    database = PostgresDatabase(Settings().postgres)
    await database.connect()
    org = uuid.uuid4()
    async with database.transaction() as conn:
        await conn.execute(
            text("INSERT INTO organizations (id, name, deployment_type, db_route, status) VALUES (:id, :name, 'shared', 'shared', 'active')"),
            {"id": org, "name": f"Day store {org.hex[:6]}"},
        )
    yield database, str(org)
    async with database.transaction() as conn:
        await conn.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": org})
    await database.disconnect()


def _keys(org: str) -> tuple[str, str]:
    return f"{org}:{uuid.uuid4()}", "2026-11-02"


async def _turn(sessions: PostgresSessionService, session, said: str, sent: str) -> None:  # noqa: ANN001
    invocation = f"inv-{uuid.uuid4().hex[:12]}"
    for author, role, words in (("user", "user", said), ("mesiri", "model", sent)):
        await sessions.append_event(session, Event(
            invocation_id=invocation, author=author, timestamp=time.time(),
            content=types.Content(role=role, parts=[types.Part(text=words)]),
        ))


def _texts(session) -> list[str]:  # noqa: ANN001
    return [p.text for e in session.events for p in (e.content.parts or []) if p.text]


async def test_a_conversation_is_kept_whole_and_read_back_in_order(db):
    database, org = db
    user_id, session_id = _keys(org)
    sessions = PostgresSessionService(database)
    session = await sessions.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    await _turn(sessions, session, "aa issue close cheyyu", "Ethu project?")
    await _turn(sessions, session, "Hospital Project", "Sheri, Hospital Project.")

    fresh = PostgresSessionService(database)  # another worker
    read = await fresh.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    assert _texts(read) == ["aa issue close cheyyu", "Ethu project?", "Hospital Project", "Sheri, Hospital Project."]
    listed = await fresh.list_sessions(app_name=APP_NAME, user_id=user_id)
    assert [s.id for s in listed.sessions] == [session_id]


async def test_recent_events_limit_keeps_the_newest(db):
    database, org = db
    user_id, session_id = _keys(org)
    sessions = PostgresSessionService(database)
    session = await sessions.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    await _turn(sessions, session, "one", "a")
    await _turn(sessions, session, "two", "b")
    read = await sessions.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id, config=GetSessionConfig(num_recent_events=2)
    )
    assert _texts(read) == ["two", "b"]


async def test_deleting_the_company_deletes_its_conversations(db):
    database, org = db
    user_id, session_id = _keys(org)
    sessions = PostgresSessionService(database)
    session = await sessions.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    await _turn(sessions, session, "hi", "ok")
    async with database.transaction() as conn:
        await conn.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": uuid.UUID(org)})
    assert await sessions.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id) is None
    async with database.transaction() as conn:
        left = (await conn.execute(text("SELECT count(*) FROM assistant_session_events WHERE organization_id = :o"), {"o": uuid.UUID(org)})).scalar()
    assert left == 0
