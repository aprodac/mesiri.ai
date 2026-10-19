"""admin.logs_router — unit tests (fakes only, no DB, no live app).

Mounts the router on a minimal standalone FastAPI app with a fake
message_logger/trace_logger on app.state.container, matching how the real
container exposes them (see runtime/dependencies.py's AppContainer).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import jwt
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from admin.logs_router import router
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY

MSG_ID = "11111111-1111-4111-8111-111111111111"


@dataclass
class FakeMessageLogger:
    rows: list[dict[str, Any]] = field(default_factory=list)
    total: int | None = None
    last_call_kwargs: dict[str, Any] | None = None

    created: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    async def list_recent(self, **kwargs: Any) -> tuple[list[dict[str, Any]], int | None]:
        self.last_call_kwargs = kwargs
        return self.rows, self.total

    async def list_created(self, correlation_id: str) -> list[dict[str, Any]]:
        return self.created.get(correlation_id, [])


@dataclass
class FakeTraceLogger:
    rows_by_correlation: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    context_by_correlation: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    async def get_by_correlation_id(self, correlation_id: str) -> list[dict[str, Any]]:
        return self.rows_by_correlation.get(correlation_id, [])

    async def get_stage_context(self, correlation_id: str) -> list[dict[str, Any]]:
        return self.context_by_correlation.get(correlation_id, [])


def _token(*, role: str = "USER", org: str = "org_1") -> str:
    payload = {
        "sub": "user_1",
        "org": org,
        "role": role,
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _app(message_logger: FakeMessageLogger, trace_logger: FakeTraceLogger) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(message_logger=message_logger, trace_logger=trace_logger)
    return app


async def _client(app: FastAPI):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_list_messages_rejects_missing_token():
    app = _app(FakeMessageLogger(), FakeTraceLogger())
    async with await _client(app) as client:
        resp = await client.get("/admin/logs/messages")
    assert resp.status_code == 401


async def test_list_messages_rejects_tenant_admin():
    """Regression test: a tenant's org ADMIN (role=ADMIN, org set) must not
    be able to read another tenant's WhatsApp message content."""
    app = _app(FakeMessageLogger(), FakeTraceLogger())
    async with await _client(app) as client:
        resp = await client.get(
            "/admin/logs/messages",
            headers={"Authorization": f"Bearer {_token(role='ADMIN', org='org_1')}"},
        )
    assert resp.status_code == 403


async def test_list_messages_accepts_platform_admin_and_returns_body_preview_only():
    message_logger = FakeMessageLogger(
        rows=[
            {
                "id": MSG_ID,
                "correlation_id": "cor_1",
                "sender_wa_id": "919000000000",
                "message_type": "text",
                "body_preview": "20 bags of cement arrived",
                "processing_status": "completed",
                "error_code": None,
                "received_at": datetime.now(UTC),
                "processed_at": datetime.now(UTC),
            }
        ]
    )
    app = _app(message_logger, FakeTraceLogger())
    async with await _client(app) as client:
        resp = await client.get(
            "/admin/logs/messages",
            headers={"Authorization": f"Bearer {_token(role='ADMIN', org='')}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["body_preview"] == "20 bags of cement arrived"
    assert "body_text" not in body["items"][0]
    assert "raw_payload" not in body["items"][0]


async def test_list_messages_passes_filters_and_cursor_through():
    message_logger = FakeMessageLogger()
    app = _app(message_logger, FakeTraceLogger())
    async with await _client(app) as client:
        resp = await client.get(
            "/admin/logs/messages",
            params={
                "wa_id": "919000000000",
                "status": "failed",
                "since_id": MSG_ID,
                "since_received_at": "2026-07-10T00:00:00Z",
                "limit": 25,
            },
            headers={"Authorization": f"Bearer {_token(role='ADMIN', org='')}"},
        )

    assert resp.status_code == 200
    assert message_logger.last_call_kwargs["wa_id"] == "919000000000"
    assert message_logger.last_call_kwargs["status"] == "failed"
    assert message_logger.last_call_kwargs["since_id"] == MSG_ID
    assert message_logger.last_call_kwargs["limit"] == 25


async def test_get_trace_rejects_tenant_admin():
    app = _app(FakeMessageLogger(), FakeTraceLogger())
    async with await _client(app) as client:
        resp = await client.get(
            "/admin/logs/messages/cor_1/trace",
            headers={"Authorization": f"Bearer {_token(role='ADMIN', org='org_1')}"},
        )
    assert resp.status_code == 403


async def test_get_trace_returns_stages_without_stage_payload():
    trace_logger = FakeTraceLogger(
        rows_by_correlation={
            "cor_1": [
                {
                    "stage": "understanding",
                    "succeeded": True,
                    "duration_ms": 120,
                    "error_code": None,
                    "error_message": None,
                    "created_at": datetime.now(UTC),
                },
                {
                    "stage": "workflow",
                    "succeeded": False,
                    "duration_ms": 45,
                    "error_code": "SINGLE_ACTIVE_CONFLICT",
                    "error_message": "user already has a pending confirmation",
                    "created_at": datetime.now(UTC),
                },
            ]
        }
    )
    app = _app(FakeMessageLogger(), trace_logger)
    async with await _client(app) as client:
        resp = await client.get(
            "/admin/logs/messages/cor_1/trace",
            headers={"Authorization": f"Bearer {_token(role='ADMIN', org='')}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert [entry["stage"] for entry in body] == ["understanding", "workflow"]
    assert body[1]["succeeded"] is False
    assert body[1]["error_code"] == "SINGLE_ACTIVE_CONFLICT"
    assert all("stage_payload" not in entry for entry in body)


async def test_get_context_rejects_tenant_admin():
    app = _app(FakeMessageLogger(), FakeTraceLogger())
    async with await _client(app) as client:
        resp = await client.get(
            "/admin/logs/messages/cor_1/context",
            headers={"Authorization": f"Bearer {_token(role='ADMIN', org='org_1')}"},
        )
    assert resp.status_code == 403


async def test_get_context_returns_full_stage_payload():
    """Unlike /trace, /context is the one route that DOES return
    stage_payload -- the control panel's AI Context panel."""
    trace_logger = FakeTraceLogger(
        context_by_correlation={
            "cor_1": [
                {
                    "stage": "understanding",
                    "succeeded": True,
                    "created_at": datetime.now(UTC),
                    "stage_payload": {"normalized_text": "20 bags of cement arrived"},
                },
            ]
        }
    )
    app = _app(FakeMessageLogger(), trace_logger)
    async with await _client(app) as client:
        resp = await client.get(
            "/admin/logs/messages/cor_1/context",
            headers={"Authorization": f"Bearer {_token(role='ADMIN', org='')}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["stage"] == "understanding"
    assert body[0]["stage_payload"] == {"normalized_text": "20 bags of cement arrived"}


async def test_messages_filter_by_company_user_project_and_site():
    """BE-26: the superadmin can narrow messages per company, user, project, site."""
    message_logger = FakeMessageLogger(total=0)
    app = _app(message_logger, FakeTraceLogger())
    org, user, project, site = (
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
        "44444444-4444-4444-8444-444444444444",
        "55555555-5555-4555-8555-555555555555",
    )
    async with await _client(app) as client:
        resp = await client.get(
            "/admin/logs/messages",
            params={"organization_id": org, "user_id": user, "project_id": project, "site_id": site},
            headers={"Authorization": f"Bearer {_token(role='ADMIN', org='')}"},
        )
    assert resp.status_code == 200
    kw = message_logger.last_call_kwargs
    assert [str(kw[k]) for k in ("organization_id", "user_id", "project_id", "site_id")] == [
        org,
        user,
        project,
        site,
    ]


async def test_a_message_lists_what_it_created_for_platform_admins_only():
    created = {
        "cor_1": [
            {
                "event_type": "LabourAttendanceRecorded",
                "aggregate_type": "labour_attendance",
                "aggregate_id": "66666666-6666-4666-8666-666666666666",
                "correlation_id": "cor_1",
                "created_at": datetime.now(UTC),
            }
        ]
    }
    app = _app(FakeMessageLogger(created=created), FakeTraceLogger())
    async with await _client(app) as client:
        ok = await client.get(
            "/admin/logs/messages/cor_1/created",
            headers={"Authorization": f"Bearer {_token(role='ADMIN', org='')}"},
        )
        tenant = await client.get(
            "/admin/logs/messages/cor_1/created",
            headers={"Authorization": f"Bearer {_token(role='ADMIN', org='org_1')}"},
        )
    assert ok.status_code == 200
    assert [r["event_type"] for r in ok.json()] == ["LabourAttendanceRecorded"]
    assert tenant.status_code == 403
