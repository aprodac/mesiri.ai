"""admin.friction + the /admin/review friction and findings routes (WA-15). Fakes only."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import jwt
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from admin.friction import annotate, score, signals_for
from admin.review_router import router
from channel.replies import render_unsupported_reply
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY

T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


def _m(seconds: int, text: str | None, **kw: Any) -> dict[str, Any]:
    base = {
        "at": (T0 + timedelta(seconds=seconds)).isoformat(),
        "type": "text",
        "text": text,
        "reply": "ok",
        "status": "completed",
        "error_code": None,
        "workflow_key": None,
        "workflow_phase": None,
        "wall_ms": 2000,
        "stages": [],
    }
    base.update(kw)
    return base


def _names(conv_messages: list[dict[str, Any]]) -> list[str]:
    return [s["signal"] for s in signals_for({"messages": conv_messages})]


def test_clean_conversation_has_no_signals():
    msgs = [
        _m(
            0,
            "50 bags cement arrived",
            workflow_key="material.receipt",
            workflow_phase="awaiting_confirmation",
        ),
        _m(20, "yes", workflow_key="material.receipt", workflow_phase="completed"),
    ]
    assert _names(msgs) == []


def test_repeat_within_window_is_flagged_but_not_after_it():
    assert "repeat" in _names([_m(0, "DPR not received today"), _m(60, "dpr not received today?")])
    assert "repeat" not in _names(
        [_m(0, "DPR not received today"), _m(600, "DPR not received today")]
    )
    assert "repeat" not in _names([_m(0, "50 bags cement"), _m(30, "and 20 rods steel")])


def test_strong_and_weak_negatives():
    assert "negative" in _names([_m(0, "add cement"), _m(30, "no that's wrong, 60 bags")])
    assert "negative" in _names([_m(0, "add cement"), _m(30, "galat hai")])
    assert _names([_m(0, "save it?"), _m(30, "no")]) == ["weak_negative"]
    # A first message can't be a reaction to a reply.
    assert _names([_m(0, "no")]) == []


def test_failure_unsupported_correction_slow_abandoned():
    unsupported = render_unsupported_reply()
    msgs = [
        _m(0, "do my GST filing", reply=unsupported),
        _m(30, "50 cement", status="failed", error_code="E1"),
        _m(60, "change yesterday's work", workflow_key="site.activity_correction"),
        _m(90, "photo", type="image", wall_ms=45_000),
        _m(120, "20 rods", workflow_key="material.receipt", workflow_phase="awaiting_confirmation"),
    ]
    names = _names(msgs)
    for expected in ("unsupported", "failed", "correction", "slow", "abandoned"):
        assert expected in names, expected
    # 45 s on an image is over the media limit; 20 s on text is over the text limit.
    assert "slow" not in _names([_m(0, "photo", type="image", wall_ms=20_000)])
    assert "slow" in _names([_m(0, "hi", wall_ms=20_000)])


def test_score_and_annotate_totals():
    convs = [
        {"messages": [_m(0, "hi")]},
        {"messages": [_m(0, "x", status="failed"), _m(20, "wrong")]},
    ]
    totals = annotate(convs)
    assert convs[0]["friction"] == {"score": 0, "signals": []}
    assert convs[1]["friction"]["score"] == score(convs[1]["friction"]["signals"]) == 3 + 2
    assert totals["conversations"] == 2
    assert totals["with_friction"] == 1
    assert totals["friction_rate"] == 0.5
    assert totals["signals"] == {"failed": 1, "negative": 1}


# --- routes ----------------------------------------------------------------


@dataclass
class FakeMessageLogger:
    rows: list[dict[str, Any]] = field(default_factory=list)

    async def list_for_review(self, *, since: datetime, limit: int) -> list[dict[str, Any]]:
        return self.rows[:limit]


@dataclass
class FakeFindings:
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def record(
        self, findings: list[dict[str, Any]], *, seen_on: date
    ) -> list[dict[str, Any]]:
        for f in findings:
            row = self.rows.setdefault(f["fingerprint"], {**f, "days_seen": 0, "status": "open"})
            row["days_seen"] += 1
            row["last_seen_on"] = seen_on
        return [self.rows[f["fingerprint"]] for f in findings]

    async def list(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return [r for r in self.rows.values() if status in (None, r["status"])][:limit]

    async def update(self, fingerprint: str, **changes: Any) -> dict[str, Any] | None:
        if changes.get("status") not in (None, "open", "fixing", "fixed", "wont_fix"):
            raise ValueError("bad status")
        row = self.rows.get(fingerprint)
        if row is not None:
            row.update({k: v for k, v in changes.items() if v is not None})
        return row


def _row(cid: str, sender: str, at: datetime, text: str, **kw: Any) -> dict[str, Any]:
    row = {
        "correlation_id": cid,
        "sender_wa_id": sender,
        "organization_id": None,
        "message_type": "text",
        "body_text": text,
        "assistant_reply": "ok",
        "processing_status": "completed",
        "error_code": None,
        "received_at": at,
        "processed_at": at + timedelta(seconds=2),
        "workflow_key": None,
        "workflow_phase": None,
    }
    row.update(kw)
    return row


def _client(message_logger=None, findings=None) -> AsyncClient:
    app = FastAPI()
    app.include_router(router)
    app.state.container = SimpleNamespace(
        message_logger=message_logger or FakeMessageLogger(),
        trace_logger=None,
        review_findings=findings or FakeFindings(),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth(org: str = "") -> dict[str, str]:
    token = jwt.encode(
        {"sub": "u", "org": org, "role": "ADMIN", "exp": datetime.now(UTC) + timedelta(hours=1)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


async def test_friction_trend_groups_by_local_day():
    day1 = datetime(2026, 10, 12, 5, 0, tzinfo=UTC)  # 10:30 IST, 12 Oct
    day2 = datetime(2026, 10, 12, 20, 0, tzinfo=UTC)  # 01:30 IST, 13 Oct
    logger = FakeMessageLogger(
        rows=[
            _row("a", "911", day1, "hi"),
            _row("b", "922", day2, "50 cement", processing_status="failed"),
        ]
    )
    async with _client(message_logger=logger) as client:
        resp = await client.get("/admin/review/friction?days=7", headers=_auth())
        bad_tz = await client.get("/admin/review/friction?tz=Mars/Base", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert [d["day"] for d in body["days"]] == ["2026-10-12", "2026-10-13"]
    assert body["days"][1]["with_friction"] == 1
    assert body["overall"]["friction_rate"] == 0.5
    assert bad_tz.status_code == 422


async def test_findings_routes_need_platform_admin_and_round_trip():
    findings = FakeFindings()
    payload = {
        "seen_on": "2026-10-14",
        "findings": [
            {
                "fingerprint": "confirmation-shows-raw-field-names",
                "category": "copy",
                "title": "Confirmation shows internal field names",
                "occurrences": 4,
                "examples": ["u_ab12 @ 09:12"],
            }
        ],
    }
    async with _client(findings=findings) as client:
        assert (await client.post("/admin/review/findings", json=payload)).status_code == 401
        assert (
            await client.post("/admin/review/findings", json=payload, headers=_auth(org="org_1"))
        ).status_code == 403
        assert (
            await client.post("/admin/review/findings", json=payload, headers=_auth())
        ).status_code == 200

        bad = {**payload, "findings": [{**payload["findings"][0], "fingerprint": "Has Spaces"}]}
        assert (
            await client.post("/admin/review/findings", json=bad, headers=_auth())
        ).status_code == 422

        listed = (await client.get("/admin/review/findings?status=open", headers=_auth())).json()
        assert listed["findings"][0]["fingerprint"] == "confirmation-shows-raw-field-names"

        patched = await client.patch(
            "/admin/review/findings/confirmation-shows-raw-field-names",
            json={"status": "fixed", "fix_commit": "abc1234"},
            headers=_auth(),
        )
        assert patched.status_code == 200 and patched.json()["status"] == "fixed"
        assert (
            await client.patch(
                "/admin/review/findings/nope", json={"status": "fixed"}, headers=_auth()
            )
        ).status_code == 404
        assert (
            await client.patch(
                "/admin/review/findings/confirmation-shows-raw-field-names",
                json={"status": "done"},
                headers=_auth(),
            )
        ).status_code == 422
