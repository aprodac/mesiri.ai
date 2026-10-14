"""admin.review_export / admin.review_router -- unit tests (fakes only, no DB).

The export leaves the server for an outside reviewer, so most of these pin
the anonymisation: no phone number, email or raw id may survive.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import jwt
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from admin.review_export import build_export, pseudonym, scrub, summarize_understanding
from admin.review_router import router
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY

KEY = b"test-key"
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
ORG = "22222222-2222-4222-8222-222222222222"


def _msg(cid: str, sender: str, minutes: float, **extra: Any) -> dict[str, Any]:
    row = {
        "correlation_id": cid,
        "sender_wa_id": sender,
        "organization_id": ORG,
        "message_type": "text",
        "body_text": "50 bags cement arrived",
        "assistant_reply": "Saved as a draft.",
        "processing_status": "completed",
        "error_code": None,
        "received_at": T0 + timedelta(minutes=minutes),
        "processed_at": T0 + timedelta(minutes=minutes, seconds=3),
        "workflow_key": "material.receipt",
        "workflow_phase": "completed",
    }
    row.update(extra)
    return row


def _export(messages, stages=(), providers=()) -> dict[str, Any]:
    return build_export(
        messages=list(messages),
        stages=list(stages),
        providers=list(providers),
        since=T0 - timedelta(hours=24),
        until=T0 + timedelta(hours=1),
        truncated=False,
        key=KEY,
    )


def test_scrub_masks_phones_and_emails_but_keeps_quantities():
    text = "call +91 98765 43210 or ravi@site.in, send 1500 bags and ₹250000"
    out = scrub(text)
    assert "98765" not in out and "ravi@site.in" not in out
    assert "[number]" in out and "[email]" in out
    assert "1500 bags" in out and "250000" in out


def test_scrub_cuts_long_text():
    out = scrub("x" * 5000)
    assert len(out) < 2100 and out.endswith("[cut]")


def test_pseudonym_is_stable_and_keyed():
    assert pseudonym("u", "919876543210", KEY) == pseudonym("u", "919876543210", KEY)
    assert pseudonym("u", "919876543210", KEY) != pseudonym("u", "919876543210", b"other")
    assert pseudonym("u", None, KEY) is None


def test_export_never_contains_raw_sender_or_org():
    export = _export([_msg("c1", "919876543210", 0, body_text="my number is 919876543210")])
    dumped = json.dumps(export, default=str)
    assert "919876543210" not in dumped
    assert ORG not in dumped


def test_messages_group_into_conversations_by_sender_and_gap():
    export = _export(
        [
            _msg("c1", "911111111111", 0),
            _msg("c2", "922222222222", 1),
            _msg("c3", "911111111111", 5),  # same conversation as c1
            _msg("c4", "911111111111", 60),  # >30 min gap -> new conversation
        ]
    )
    convs = export["conversations"]
    assert [len(c["messages"]) for c in convs] == [2, 1, 1]
    assert convs[0]["user"] == convs[2]["user"] != convs[1]["user"]
    assert export["summary"]["conversations"] == 3
    assert export["summary"]["users"] == 2
    assert export["summary"]["companies"] == 1


def test_stages_and_ai_calls_attach_to_their_message():
    export = _export(
        [_msg("c1", "911111111111", 0)],
        stages=[
            {
                "correlation_id": "c1",
                "stage": "understanding",
                "duration_ms": 900,
                "succeeded": True,
                "error_code": None,
            },
            {
                "correlation_id": "other",
                "stage": "x",
                "duration_ms": 1,
                "succeeded": True,
                "error_code": None,
            },
        ],
        providers=[
            {
                "correlation_id": "c1",
                "stage": "understanding",
                "provider": "gemini",
                "operation": "generate_json",
                "model": "m",
                "latency_ms": 800,
                "succeeded": True,
                "error_code": None,
            },
        ],
    )
    message = export["conversations"][0]["messages"][0]
    assert [s["stage"] for s in message["stages"]] == ["understanding"]
    assert message["ai_calls"][0]["provider"] == "gemini"
    assert message["wall_ms"] == 3000
    assert export["summary"]["wall_ms_by_type"]["text"]["p50"] == 3000


def test_understanding_summary_keeps_only_what_a_case_needs_and_scrubs_it():
    summary = summarize_understanding(
        {
            "semantic_type": "expense",
            "detected_language": "Malayalam",
            "translated_text": "paid 1500, call 9876543210",
            "normalized_text": "should not appear",
            "candidates": [
                {"fields": {"amount": 1500, "vendor": "a@b.com"}, "missing_fields": ["unit"]}
            ],
        }
    )
    assert summary == {
        "semantic_type": "expense",
        "detected_language": "Malayalam",
        "translated_text": "paid 1500, call [number]",
        "fields": {"amount": 1500, "vendor": "[email]"},
        "missing_fields": ["unit"],
    }
    assert summarize_understanding(None) is None


# --- router -----------------------------------------------------------------


@dataclass
class FakeMessageLogger:
    rows: list[dict[str, Any]] = field(default_factory=list)
    last_limit: int | None = None

    async def list_for_review(self, *, since: datetime, limit: int) -> list[dict[str, Any]]:
        self.last_limit = limit
        return self.rows[:limit]


@dataclass
class FakeTraceLogger:
    async def get_review_stages(self, correlation_ids: list[str]) -> list[dict[str, Any]]:
        return []

    async def get_review_providers(self, correlation_ids: list[str]) -> list[dict[str, Any]]:
        return []

    async def get_review_understanding(self, correlation_ids: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "correlation_id": cid,
                "stage_payload": {
                    "semantic_type": "material_update",
                    "candidates": [
                        {"fields": {"material_name": "cement", "note": "call 9876501234"}}
                    ],
                    "normalized_text": "secret full text",
                },
            }
            for cid in correlation_ids
        ]

    async def get_stage_summary(self, since: datetime) -> list[dict[str, Any]]:
        return [
            {
                "stage": "understanding",
                "n": 3,
                "failures": 0,
                "avg_ms": 10,
                "p50_ms": 9.0,
                "p95_ms": 12.0,
                "max_ms": 12,
            }
        ]


def _token(*, role: str = "ADMIN", org: str = "") -> str:
    payload = {
        "sub": "user_1",
        "org": org,
        "role": role,
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _client(message_logger: FakeMessageLogger) -> AsyncClient:
    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(
        message_logger=message_logger, trace_logger=FakeTraceLogger()
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_export_rejects_missing_token():
    async with _client(FakeMessageLogger()) as client:
        resp = await client.get("/admin/review/export")
    assert resp.status_code == 401


async def test_export_rejects_tenant_admin():
    async with _client(FakeMessageLogger()) as client:
        resp = await client.get(
            "/admin/review/export", headers={"Authorization": f"Bearer {_token(org='org_1')}"}
        )
    assert resp.status_code == 403


async def test_export_returns_anonymised_conversations_and_flags_truncation():
    rows = [_msg(f"c{i}", "919876543210", i) for i in range(3)]
    logger = FakeMessageLogger(rows=rows)
    async with _client(logger) as client:
        resp = await client.get(
            "/admin/review/export?limit=2", headers={"Authorization": f"Bearer {_token()}"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert logger.last_limit == 3  # asks for one extra to detect a cut window
    assert body["truncated"] is True
    assert body["summary"]["messages"] == 2
    assert body["stage_summary"][0]["stage"] == "understanding"
    assert "919876543210" not in resp.text
    first = body["conversations"][0]["messages"][0]
    assert first["understanding"]["fields"] == {"material_name": "cement", "note": "call [number]"}
    assert "secret full text" not in resp.text
    assert "friction" in body and "friction" in body["conversations"][0]
