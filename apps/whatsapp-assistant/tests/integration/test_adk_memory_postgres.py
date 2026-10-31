"""Request 185: the v2-on-ADK conversation memory against a real database (migration 0496).

ADK's own Runner writes a two-turn conversation through ``PostgresSessionService``; a fresh
service then reads it back whole, in order, and a company's rows go when the company goes.

    pytest apps/whatsapp-assistant/tests/integration/test_adk_memory_postgres.py -m integration
"""

from __future__ import annotations

import uuid

import pytest
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.genai import types
from sqlalchemy import text

from agent_v2.adk.memory import APP_NAME, PostgresSessionService, session_keys
from agent_v2.adk.models import ScriptedLlm
from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.database import PostgresDatabase

pytestmark = pytest.mark.integration


@pytest.fixture
async def db():
    database = PostgresDatabase(Settings().postgres)
    await database.connect()
    org = uuid.uuid4()
    async with database.transaction() as conn:
        await conn.execute(
            text("INSERT INTO organizations (id, name, deployment_type, db_route, status) VALUES (:id, :name, 'shared', 'shared', 'active')"),
            {"id": org, "name": f"ADK memory {org.hex[:6]}"},
        )
    yield database, str(org)
    async with database.transaction() as conn:
        await conn.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": org})
    await database.disconnect()


def _run(model, sessions):  # noqa: ANN001, ANN202
    agent = LlmAgent(name="mesiri", model=model, instruction="rules")
    return Runner(app_name=APP_NAME, agent=agent, session_service=sessions)


async def _say(runner, user_id, session_id, words):  # noqa: ANN001, ANN202
    async for _ in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=types.Content(role="user", parts=[types.Part(text=words)])
    ):
        pass


async def test_a_conversation_is_kept_whole_and_read_back_in_order(db):
    database, org = db
    user_id, session_id = session_keys(org, uuid.uuid4())
    sessions = PostgresSessionService(database)
    await sessions.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    model = ScriptedLlm(["Ethu project?", "Sheri, Hospital Project."])
    runner = _run(model, sessions)
    await _say(runner, user_id, session_id, "aa issue close cheyyu")
    await _say(runner, user_id, session_id, "Hospital Project")

    # The second model call was sent the whole first turn, from the database.
    assert [t for _, t in model.seen_texts(-1)] == ["aa issue close cheyyu", "Ethu project?", "Hospital Project"]

    fresh = PostgresSessionService(database)  # another worker
    session = await fresh.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    texts = [p.text for e in session.events for p in (e.content.parts or []) if p.text]
    assert texts == ["aa issue close cheyyu", "Ethu project?", "Hospital Project", "Sheri, Hospital Project."]
    listed = await fresh.list_sessions(app_name=APP_NAME, user_id=user_id)
    assert [s.id for s in listed.sessions] == [session_id]


async def test_recent_events_limit_keeps_the_newest(db):
    database, org = db
    user_id, session_id = session_keys(org, uuid.uuid4())
    sessions = PostgresSessionService(database)
    await sessions.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    runner = _run(ScriptedLlm(["a", "b"]), sessions)
    await _say(runner, user_id, session_id, "one")
    await _say(runner, user_id, session_id, "two")
    from google.adk.sessions.base_session_service import GetSessionConfig

    session = await sessions.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id, config=GetSessionConfig(num_recent_events=2)
    )
    assert [p.text for e in session.events for p in e.content.parts] == ["two", "b"]


async def test_deleting_the_company_deletes_its_conversations(db):
    database, org = db
    user_id, session_id = session_keys(org, uuid.uuid4())
    sessions = PostgresSessionService(database)
    await sessions.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    await _say(_run(ScriptedLlm(["ok"]), sessions), user_id, session_id, "hi")
    async with database.transaction() as conn:
        await conn.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": uuid.UUID(org)})
    assert await sessions.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id) is None
    async with database.transaction() as conn:
        left = (await conn.execute(text("SELECT count(*) FROM assistant_session_events WHERE organization_id = :o"), {"o": uuid.UUID(org)})).scalar()
    assert left == 0
