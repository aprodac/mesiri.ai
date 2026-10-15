"""apps/whatsapp-assistant/tests/unit/test_user_messages_router.py

Unit tests for users/router.py WhatsApp messages routes.
Mounts users router on a minimal FastAPi app and tests authentication, SQL structure/mocks,
IDOR checks, and tenant organization checks.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY
from users.router import router

USER_ID = uuid.uuid4()
OTHER_USER_ID = uuid.uuid4()
ORG_ID = uuid.uuid4()
OTHER_ORG_ID = uuid.uuid4()


def _token(*, role: str = "ADMIN", org: str = str(ORG_ID)) -> str:
    payload = {
        "sub": "admin_1",
        "org": org,
        "role": role,
        "exp": datetime.now(UTC).timestamp() + 3600,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


class FakeConnection:
    def __init__(self, select_results: list[Any]):
        self.select_results = select_results
        self.executed_queries = []

    async def execute(self, stmt: Any, params: Any = None) -> FakeResult:
        query_str = str(stmt)
        self.executed_queries.append((query_str, params))
        res = self.select_results.pop(0) if self.select_results else []
        return FakeResult(res)


class FakeResult:
    def __init__(self, rows: list[Any]):
        self.rows = rows

    def first(self) -> Any:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[Any]:
        return self.rows

    def scalar_one(self) -> Any:
        return self.rows[0] if self.rows else 0

    def mappings(self) -> FakeMappings:
        return FakeMappings(
            [dict(r) if hasattr(r, "_fields") or isinstance(r, dict) else r for r in self.rows]
        )


class FakeMappings:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def all(self) -> list[dict]:
        return self.rows

    def first(self) -> dict | None:
        return self.rows[0] if self.rows else None


class FakeEngine:
    def __init__(self, select_results: list[Any]):
        self.select_results = select_results
        self.conn = None

    def connect(self) -> AsyncContextManager:
        self.conn = FakeConnection(self.select_results)
        return self

    async def __aenter__(self) -> FakeConnection:
        return self.conn

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


class AsyncContextManager:
    async def __aenter__(self):
        pass

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


def _app(select_results: list[Any]) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.engine = FakeEngine(select_results)
    return app


@pytest.fixture(autouse=True)
def patch_get_engine(monkeypatch):
    # Patch get_engine inside users.router
    import users.router

    monkeypatch.setattr(users.router, "get_engine", lambda: patch_get_engine.engine)


async def _client(app: FastAPI):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_list_messages_requires_token(monkeypatch):
    app = _app([])
    patch_get_engine.engine = app.state.engine
    async with await _client(app) as client:
        resp = await client.get(f"/users/{USER_ID}/whatsapp/messages")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_messages_rejects_cross_org_admin(monkeypatch):
    # 1. Select user_table returns None (user not found in caller's org)
    app = _app([[]])
    patch_get_engine.engine = app.state.engine
    async with await _client(app) as client:
        resp = await client.get(
            f"/users/{USER_ID}/whatsapp/messages",
            headers={"Authorization": f"Bearer {_token(org=str(OTHER_ORG_ID))}"},
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "User not found"


@pytest.mark.asyncio
async def test_list_messages_returns_empty_when_user_has_no_number(monkeypatch):
    user_row = SimpleNamespace(id=USER_ID, organization_id=ORG_ID, whatsapp_number=None)
    # 1. user lookup -> user_row (no WhatsApp number, so nothing else is read)
    app = _app([[user_row]])
    patch_get_engine.engine = app.state.engine
    async with await _client(app) as client:
        resp = await client.get(
            f"/users/{USER_ID}/whatsapp/messages",
            headers={"Authorization": f"Bearer {_token(org=str(ORG_ID))}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_messages_with_data(monkeypatch):
    # Stored as typed; messages carry the digits only.
    user_row = SimpleNamespace(
        id=USER_ID, organization_id=ORG_ID, whatsapp_number="+91 90000 00000"
    )
    message_row = {
        "id": "22222222-2222-4222-8222-222222222222",
        "correlation_id": "cor_123",
        "sender_wa_id": "919000000000",
        "message_type": "text",
        "body_text": "hello",
        "media_object_key": None,
        "occurred_at": datetime.now(UTC).isoformat(),
        "direction": "inbound",
        "processing_status": "completed",
        "error_code": None,
    }
    # 1. user lookup
    # 2. messages list (UNION SELECT * FROM...)
    # 3. messages count (UNION SELECT COUNT(*)...)
    # 4. timeline entries lookup -> empty list
    # 5. interactions lookup -> empty list
    app = _app([[user_row], [message_row], [1], [], []])
    patch_get_engine.engine = app.state.engine
    async with await _client(app) as client:
        resp = await client.get(
            f"/users/{USER_ID}/whatsapp/messages",
            headers={"Authorization": f"Bearer {_token(org=str(ORG_ID))}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["correlation_id"] == "cor_123"
    assert data["items"][0]["body_text"] == "hello"
    _, params = app.state.engine.conn.executed_queries[1]
    assert params["wa_ids"] == ["919000000000"]


@pytest.mark.asyncio
async def test_get_message_detail_cross_org_reject(monkeypatch):
    # Get message details:
    # 1. Select user_table returns None (user not found in caller's org)
    app = _app([[]])
    patch_get_engine.engine = app.state.engine
    async with await _client(app) as client:
        resp = await client.get(
            f"/users/{USER_ID}/whatsapp/messages/22222222-2222-4222-8222-222222222222",
            headers={"Authorization": f"Bearer {_token(org=str(OTHER_ORG_ID))}"},
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "User not found"
