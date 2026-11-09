"""ADM-01: a change made on WhatsApp (through the assistant's API app, as v3 does) is in the company's activity log
with source 'whatsapp', written through the app's real database connection (no test override).

Requires a live Postgres (Settings().postgres) -- run with `pytest -m integration`.
"""

from __future__ import annotations

import json
import uuid

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from agent_api.app import build_api_app
from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import create_access_token
from mesiri.infrastructure.postgres.database import PostgresDatabase

pytestmark = pytest.mark.integration


async def test_a_whatsapp_change_is_logged_as_whatsapp(monkeypatch) -> None:
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    database = PostgresDatabase(Settings().postgres)
    await database.connect()
    try:
        org, user, project = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with database.transaction() as conn:
            await conn.execute(sa.text("INSERT INTO organizations (id, name, deployment_type, db_route, status, "
                                       "created_at, updated_at) VALUES (:id, 'WA Log Co', 'local', 'default', 'active', "
                                       "now(), now())"), {"id": org})
            await conn.execute(sa.text("INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, "
                                       "status, access_policy, created_at, updated_at) VALUES (:id, :o, :e, 'h', 'Ravi', "
                                       "'ADMIN', 'active', CAST(:p AS jsonb), now(), now())"),
                               {"id": user, "o": org, "e": f"{uuid.uuid4().hex[:8]}@x.com",
                                "p": json.dumps({"mode": "all_projects", "projects": []})})
            await conn.execute(sa.text("INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                                       "VALUES (:id, :o, 'Villa', now(), now())"), {"id": project, "o": org})
        token = create_access_token(data={"sub": str(user), "org": str(org), "role": "ADMIN"})
        app = build_api_app(database)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://agent") as c:
            r = await c.post("/tasks", headers={"Authorization": f"Bearer {token}"},
                             json={"project_id": str(project), "title": "Order steel", "source": "whatsapp"})
            assert r.status_code in (200, 201), r.text
        async with database.transaction() as conn:
            rows = (await conn.execute(sa.text("SELECT source, action, record_kind, actor_name FROM activity_log "
                                               "WHERE organization_id = :o"), {"o": org})).all()
        assert [tuple(r) for r in rows] == [("whatsapp", "Create task", "task", "Ravi")]
    finally:
        await database.disconnect()
