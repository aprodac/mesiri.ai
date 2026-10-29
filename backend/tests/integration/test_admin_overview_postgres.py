"""SA-18: GET /admin/overview against a real Postgres (integration). Each
test runs in a transaction that is rolled back; other data in a shared
database may add to the totals, so the checks are on what these tests add.
"""

from __future__ import annotations

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from mesiri.domains.admin import overview_router

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


async def _org(conn, name: str) -> uuid.UUID:
    org = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO organizations (id, name, deployment_type, db_route, status,"
            " trial_started_at, trial_ends_at, created_at)"
            " VALUES (:id, :name, 'local', 'default', 'trial', now() - interval '1 day',"
            " now() + interval '2 days', now() - interval '1 day')"
        ),
        {"id": org, "name": name},
    )
    return org


async def _message(conn, org, *, minutes_ago: int, status: str) -> None:
    corr = f"corr-{uuid.uuid4()}"
    received = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=minutes_ago)
    await conn.execute(
        text(
            "INSERT INTO inbound_messages (id, correlation_id, sender_wa_id, message_type,"
            " raw_payload, dedup_key, organization_id, processing_status, received_at, processed_at)"
            " VALUES (gen_random_uuid(), :corr, '919876500091', 'text', '{}', :corr, :org, :st,"
            " :at, :done)"
        ),
        {
            "corr": corr,
            "org": org,
            "st": status,
            "at": received,
            "done": None if status == "pending" else received + dt.timedelta(seconds=4),
        },
    )


async def test_overview_counts_what_happened_today(conn) -> None:
    before = await overview_router.get_overview(_admin={}, conn=conn)
    org = await _org(conn, "Overview Builders")
    await _message(conn, org, minutes_ago=2, status="completed")
    await _message(conn, org, minutes_ago=3, status="failed")
    await _message(conn, org, minutes_ago=30, status="pending")  # no reply for 30 min

    out = await overview_router.get_overview(_admin={}, conn=conn)

    s, b = out["status"], before["status"]
    assert s["messages_24h"] - b["messages_24h"] == 3
    assert s["failed_24h"] - b["failed_24h"] == 1
    assert s["unanswered"] - b["unanswered"] == 1
    assert out["companies"]["trial"] - before["companies"]["trial"] == 1
    assert out["companies"]["active_7d"] - before["companies"]["active_7d"] == 1

    keys = {i["key"]: i for i in out["attention"]}
    assert keys["failed"]["severity"] == "critical"
    assert keys["unanswered"]["link"] == "/logs?status=pending"
    ending = keys["trial_ending"]["companies"]
    assert any(c["name"] == "Overview Builders" for c in ending)

    today = dt.datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    assert [d["day"] for d in out["activity"]][-1] == today
    assert len(out["activity"]) == 14
    assert out["activity"][-1]["messages"] - before["activity"][-1]["messages"] == 3
    assert any(r["name"] == "Overview Builders" for r in out["most_active"])


def test_only_platform_admins_can_read_the_overview() -> None:
    from mesiri.domains.shared.auth import require_platform_admin

    [route] = overview_router.router.routes
    assert require_platform_admin in [d.call for d in route.dependant.dependencies]
