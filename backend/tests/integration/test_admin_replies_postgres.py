"""SA-17: the control panel's Reply Insights, against a real Postgres
(integration): reply time and AI tokens per WhatsApp message, the overview
(summary, speed bands, trend, by model and step), the feed's sorting and
filters, and one message's calls. Each test runs in a transaction that is
rolled back, scoped to a company of its own.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from mesiri.domains.admin import replies_router
from mesiri.infrastructure.postgres.repositories.usage_costs import (
    CostRow,
    PostgresUsageCostRepository,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def conn():
    from sqlalchemy.ext.asyncio import create_async_engine

    from mesiri.bootstrap.settings import Settings

    engine = create_async_engine(Settings().postgres.dsn())
    async with engine.connect() as connection:
        tx = await connection.begin()
        yield connection
        await tx.rollback()
    await engine.dispose()


def _ago(minutes: float) -> dt.datetime:
    return dt.datetime.now(dt.UTC) - dt.timedelta(minutes=minutes)


async def _message(
    conn,
    org,
    *,
    minutes_ago: float,
    reply_s: float | None,
    kind="text",
    body="hi",
    status="completed",
) -> str:
    corr = f"corr-{uuid.uuid4()}"
    received = _ago(minutes_ago)
    await conn.execute(
        text(
            "INSERT INTO inbound_messages (id, correlation_id, sender_wa_id, message_type,"
            " raw_payload, dedup_key, body_text, assistant_reply, organization_id,"
            " processing_status, received_at, processed_at)"
            " VALUES (gen_random_uuid(), :corr, '919876500081', :kind, '{}', :dedup, :body,"
            " 'Recorded.', :org, :status, :at, :done)"
        ),
        {
            "corr": corr,
            "dedup": f"wamid-{corr}",
            "kind": kind,
            "body": body,
            "org": org,
            "status": status,
            "at": received,
            "done": None if reply_s is None else received + dt.timedelta(seconds=reply_s),
        },
    )
    return corr


async def _acme(conn):
    """Acme: a text answered in 3 s with two AI calls (one unpriced), a
    voice note answered in 20 s with one call, a 'hi' answered in 1 s by the
    fast path (no AI), one still waiting, and one from two days ago. Its
    owner, Ravi, sent them all. The WhatsApp reply row must not count."""
    org = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at)"
            " VALUES (:id, 'Acme Replies', 'local', 'default', 'active', now())"
        ),
        {"id": org},
    )
    await conn.execute(
        text(
            "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role,"
            " status, whatsapp_number, created_at) VALUES (gen_random_uuid(), :org,"
            " :email, 'x', 'Ravi Kumar', 'ADMIN', 'active', '+91 98765 00081', now())"
        ),
        {"org": org, "email": f"ravi-{org}@example.in"},
    )
    text_msg = await _message(conn, org, minutes_ago=30, reply_s=3, body="12 masons today")
    voice = await _message(conn, org, minutes_ago=20, reply_s=20, kind="audio", body=None)
    await _message(conn, org, minutes_ago=10, reply_s=1, body="hi")
    await _message(conn, org, minutes_ago=5, reply_s=None, status="pending")
    await _message(conn, org, minutes_ago=2 * 1440, reply_s=2, body="old")

    repo = PostgresUsageCostRepository(conn)
    for row in (
        CostRow(
            provider="gemini",
            operation="extract",
            model="gemini-2.5-flash",
            correlation_id=text_msg,
            latency_ms=900,
            input_tokens=1200,
            cached_input_tokens=200,
            output_tokens=300,
            cost_inr=Decimal("0.0900"),
        ),
        CostRow(
            provider="deepseek",
            operation="reply",
            purpose="compose_reply",
            model="deepseek-chat",
            correlation_id=text_msg,
            latency_ms=600,
            input_tokens=500,
            output_tokens=50,
            cost_inr=None,
        ),
        CostRow(
            provider="sarvam",
            operation="transcribe",
            model="saarika",
            correlation_id=voice,
            latency_ms=4000,
            input_tokens=0,
            output_tokens=40,
            cost_inr=Decimal("0.3000"),
        ),
    ):
        await repo.insert(row)
    await repo.record_whatsapp_sent(
        CostRow(
            provider="whatsapp",
            operation="send_text",
            correlation_id=text_msg,
            organization_id=org,
            category="service",
            external_id=f"wamid.r-{org}",
            recipient="919876500081",
            cost_inr=Decimal("0.1150"),
        )
    )
    return org, text_msg, voice


async def test_overview_reply_time_bands_and_tokens(conn) -> None:
    org, _, _ = await _acme(conn)

    out = await replies_router.get_reply_overview(
        since_minutes=1440, organization_id=org, message_type=None, _admin={}, conn=conn
    )

    s = out["summary"]
    assert (s["messages"], s["replied"], s["no_ai"], s["with_ai"]) == (4, 3, 1, 2)
    assert float(s["p50_ms"]) == pytest.approx(3000, abs=50)
    assert float(s["max_ms"]) == pytest.approx(20000, abs=50)
    # Under 5 s: the 3 s text and the 1 s "hi"; 15-30 s: the voice note.
    assert [s[f"band_{i}"] for i in range(5)] == [2, 0, 1, 0, 0]
    assert out["bands_ms"] == [5000, 15000, 30000, 60000]
    # Three AI calls; the WhatsApp reply is not one.
    assert (s["ai_calls"], s["input_tokens"], s["output_tokens"]) == (3, 1700, 390)
    assert s["cached_input_tokens"] == 200
    assert Decimal(s["ai_cost_inr"]) == Decimal("0.3900")
    assert s["unpriced"] == 1

    models = {m["model"]: m for m in out["by_model"]}
    assert models["gemini-2.5-flash"]["input_tokens"] == 1200
    assert out["by_model"][0]["model"] == "gemini-2.5-flash"  # most tokens first
    steps = {st["step"] for st in out["by_step"]}
    assert steps == {"extract", "compose_reply", "transcribe"}  # purpose before operation

    # A day in hourly points, every hour present, the messages all counted.
    assert out["step_minutes"] == 60
    assert len(out["timeline"]) in (24, 25)
    assert sum(p["messages"] for p in out["timeline"]) == 4
    assert sum(p["output_tokens"] for p in out["timeline"]) == 390


async def test_type_filter_and_window(conn) -> None:
    org, _, voice = await _acme(conn)

    audio = await replies_router.get_reply_overview(
        since_minutes=1440, organization_id=org, message_type="audio", _admin={}, conn=conn
    )
    week = await replies_router.get_reply_overview(
        since_minutes=10080, organization_id=org, message_type=None, _admin={}, conn=conn
    )

    assert audio["summary"]["messages"] == 1
    assert audio["summary"]["output_tokens"] == 40
    assert week["summary"]["messages"] == 5  # the two-day-old one too
    assert week["step_minutes"] == 360


async def test_feed_sorts_filters_and_names_the_sender(conn) -> None:
    org, text_msg, voice = await _acme(conn)

    async def feed(**kw):
        args = dict(
            since_minutes=1440,
            organization_id=org,
            message_type=None,
            sort="newest",
            slower_than_ms=None,
            limit=50,
            offset=0,
        )
        return await replies_router.get_reply_messages(**{**args, **kw}, _admin={}, conn=conn)

    newest = await feed()
    assert newest["total"] == 4
    assert newest["items"][0]["processing_status"] == "pending"  # 5 min ago
    first = next(i for i in newest["items"] if i["correlation_id"] == text_msg)
    assert first["sender_name"] == "Ravi Kumar"
    assert first["organization_name"] == "Acme Replies"
    assert first["text"] == "12 masons today" and first["reply"] == "Recorded."
    assert (first["ai_calls"], first["input_tokens"], first["output_tokens"]) == (2, 1700, 350)
    assert float(first["ai_ms"]) == 1500
    assert "total" not in first

    slowest = await feed(sort="slowest")
    assert slowest["items"][0]["correlation_id"] == voice
    assert slowest["items"][-1]["reply_ms"] is None  # unanswered last

    by_tokens = await feed(sort="tokens")
    assert by_tokens["items"][0]["correlation_id"] == text_msg

    slow = await feed(slower_than_ms=10_000)
    assert [i["correlation_id"] for i in slow["items"]] == [voice]
    assert slow["total"] == 1

    page = await feed(limit=2, offset=2)
    assert page["total"] == 4 and len(page["items"]) == 2


async def test_one_message_calls_in_order(conn) -> None:
    _, text_msg, _ = await _acme(conn)

    calls = await replies_router.get_reply_calls(correlation_id=text_msg, _admin={}, conn=conn)

    assert [c["provider"] for c in calls] == ["gemini", "deepseek"]
    assert calls[0]["cached_input_tokens"] == 200
    assert calls[0]["ai_cost_inr"] == "0.09000000"
    assert calls[1]["ai_cost_inr"] is None


def test_trend_points_stay_readable_whatever_the_window() -> None:
    for minutes in (5, 60, 120, 360, 1440, 10080, 43200):
        points = minutes / (replies_router.step_for(minutes).total_seconds() / 60)
        assert 1 <= points <= 30, minutes


def test_only_platform_admins_can_read_replies() -> None:
    from mesiri.domains.shared.auth import require_platform_admin

    for route in replies_router.router.routes:
        assert require_platform_admin in [d.call for d in route.dependant.dependencies]
