"""WA-04 end to end against a real Postgres: the cutoff labels the day, the
scheduler step queues the gap-check to the site engineer, the shared send
step delivers it (Meta mocked at the HTTP transport), the engineer's labour
count turns the day ready, and "Site closed today" marks a site closed.

Data is committed (the recipient lookup and the actor reader open their own
connections), so the company is deleted again afterwards."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text

from backend.postgres.actor import PostgresActorReader
from channel.whatsapp.outbound import WhatsAppSender
from channel.whatsapp.templates import SITE_DAY_REVIEW
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.projects import auto_dpr
from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.database import PostgresDatabase
from runtime import site_day_review
from runtime.send_pending_notifications import drain_and_send

pytestmark = pytest.mark.integration

DAY = dt.date(2026, 10, 15)
EVENING_UTC = dt.datetime(2026, 10, 15, 13, 30, tzinfo=dt.UTC)  # 19:00 in India
ENGINEER_WA = "919800012345"


@pytest.fixture
async def world():
    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    engineer_id = uuid.uuid4()
    async with db.transaction() as conn:
        created = await create_company(
            conn,
            NewCompany(
                name=f"Evening E2E {uuid.uuid4().hex[:6]}",
                owner_name="Owner",
                owner_phone=f"9198{uuid.uuid4().int % 10**8:08d}",
                project_name="Green Towers",
                site_names=("Block A", "Block B"),
                auto_dpr=True,
            ),
            now=EVENING_UTC,
        )
        await conn.execute(
            text(
                "INSERT INTO users (id, organization_id, hashed_password, full_name, role, status,"
                " whatsapp_number) VALUES (:id, :org, 'x', 'Ravi', 'SITE_ENGINEER', 'active', :wa)"
            ),
            {"id": engineer_id, "org": created.organization_id, "wa": ENGINEER_WA},
        )
        await conn.execute(
            text(
                "INSERT INTO project_members (id, project_id, user_id, site_access_mode)"
                " VALUES (:id, :p, :u, 'all_sites')"
            ),
            {"id": uuid.uuid4(), "p": created.project_id, "u": engineer_id},
        )
        # Block A: work reported, no labour count. Block B: nothing.
        await conn.execute(
            text(
                "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date)"
                " VALUES (:id, :org, :p, :s, :d)"
            ),
            {
                "id": uuid.uuid4(),
                "org": created.organization_id,
                "p": created.project_id,
                "s": created.sites[0].site_id,
                "d": DAY,
            },
        )
        # The cutoff (what queue_due_project_auto_dprs does at 18:00).
        await auto_dpr.generate_project_dpr(
            conn,
            organization_id=created.organization_id,
            project_id=created.project_id,
            report_date=DAY,
        )
        await auto_dpr.mark_project_auto_dpr_run(conn, project_id=created.project_id, ran_on=DAY)

    yield SimpleNamespace(db=db, created=created, engineer_id=engineer_id)

    async with db.transaction() as conn:
        org = created.organization_id
        await conn.execute(text("DELETE FROM notifications WHERE organization_id = :o"), {"o": org})
        await conn.execute(text("DELETE FROM fact_reviews WHERE organization_id = :o"), {"o": org})
        await conn.execute(
            text(
                "DELETE FROM labour_attendance_lines WHERE report_id IN"
                " (SELECT id FROM labour_attendance_reports WHERE organization_id = :o)"
            ),
            {"o": org},
        )
        await conn.execute(
            text(
                "DELETE FROM daily_report_sources WHERE site_daily_report_id IN"
                " (SELECT id FROM daily_reports WHERE organization_id = :o)"
            ),
            {"o": org},
        )
        await conn.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
    await db.disconnect()


def _meta(captured: list[dict]) -> WhatsAppSender:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": f"wamid.{len(captured)}"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WhatsAppSender(client=client, access_token="token", phone_number_id="PHONE_NUMBER_ID")


async def _review(db) -> int:
    async with db.transaction() as conn:
        return await site_day_review.queue_site_day_reviews(conn, db=db, now_utc=EVENING_UTC)


async def _status(db, site_id) -> tuple[str, dict]:
    async with db.transaction() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status::text AS status, missing_sections FROM daily_reports"
                    " WHERE site_id = :s AND report_date = :d AND level = 'SITE'"
                ),
                {"s": site_id, "d": DAY},
            )
        ).mappings().one()
    missing = row["missing_sections"]
    return row["status"], json.loads(missing) if isinstance(missing, str) else missing


async def test_the_evening_loop_end_to_end(world) -> None:
    db, created = world.db, world.created
    block_a, block_b = (site.site_id for site in created.sites)

    # 1. One gap-check, for Block A only (Block B sent nothing: WA-06's).
    assert await _review(db) == 1
    assert await _review(db) == 0  # once a day
    async with db.transaction() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT rule_key, recipient_user_id, payload FROM notifications"
                    " WHERE organization_id = :o"
                ),
                {"o": created.organization_id},
            )
        ).mappings().all()
    assert [(r["rule_key"], r["recipient_user_id"]) for r in rows] == [
        (f"site_day_gap:{block_a}", world.engineer_id)
    ]
    payload = rows[0]["payload"]
    payload = json.loads(payload) if isinstance(payload, str) else payload
    assert "missing the *labour count*" in payload["message"]
    assert payload["template"]["body_params"] == [
        "Block A (Green Towers)",
        "Labour count is missing.",
        "9:00 pm",
    ]

    # 2. Delivered: Ravi never messaged, so the approved template goes, with
    #    the "Open report" tap carrying the site and day.
    captured: list[dict] = []
    counts = await drain_and_send(
        db=db,
        actor_reader=PostgresActorReader(),
        sender=_meta(captured),
        approved_templates=frozenset({SITE_DAY_REVIEW.name}),
        now_utc=EVENING_UTC,
    )
    assert counts == {"sent": 1, "skipped": 0}
    (sent,) = captured
    assert sent["to"] == ENGINEER_WA
    assert sent["template"]["name"] == "mesiri_site_day_review"
    assert sent["template"]["components"][-1] == {
        "type": "button",
        "sub_type": "quick_reply",
        "index": "0",
        "parameters": [{"type": "payload", "payload": f"sdr:open:{block_a}:20261015"}],
    }

    # 3. Ravi taps "Open report": the full message, with its button.
    actor = await PostgresActorReader().resolve_by_whatsapp_id(ENGINEER_WA)
    review = site_day_review.SiteDayReview(db=db)
    opened = await review.handle_tap(
        SimpleNamespace(metadata={"interactive_reply_id": f"sdr:open:{block_a}:20261015"}), actor
    )
    assert "missing the *labour count*" in opened.text
    assert opened.buttons[0].id == f"sdr:closed:{block_a}:20261015"

    # 4. He sends the labour count (saved as a draft); the next tick
    #    refreshes the day and it is ready.
    async with db.transaction() as conn:
        report_id = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO labour_attendance_reports (id, organization_id, project_id, site_id,"
                " occurred_date, recorded_via, created_by)"
                " VALUES (:id, :o, :p, :s, :d, 'whatsapp_text', :u)"
            ),
            {
                "id": report_id,
                "o": created.organization_id,
                "p": created.project_id,
                "s": block_a,
                "d": DAY,
                "u": world.engineer_id,
            },
        )
        await conn.execute(
            text(
                "INSERT INTO labour_attendance_lines (id, report_id, trade, headcount)"
                " VALUES (:id, :r, 'mason', 9)"
            ),
            {"id": uuid.uuid4(), "r": report_id},
        )
    assert (await _status(db, block_a))[0] == "NEEDS_DETAILS"
    assert await _review(db) == 0
    status, missing = await _status(db, block_a)
    assert status == "READY"
    assert missing["blocking"] == []

    # 5. "Site closed today" for Block B: no work, nothing required.
    closed = await review.handle_tap(
        SimpleNamespace(metadata={"interactive_reply_id": f"sdr:closed:{block_b}:20261015"}), actor
    )
    assert closed.text == "👍 Marked *Block B* as closed today. Today's report will say there was no work."
    assert await _status(db, block_b) == ("READY", {"blocking": [], "optional": []})


async def test_a_tap_for_a_site_of_another_company_is_refused(world) -> None:
    actor = await PostgresActorReader().resolve_by_whatsapp_id(ENGINEER_WA)
    reply = await site_day_review.SiteDayReview(db=world.db).handle_tap(
        SimpleNamespace(metadata={"interactive_reply_id": f"sdr:closed:{uuid.uuid4()}:20261015"}),
        actor,
    )
    assert reply.text == site_day_review.NOT_YOUR_SITE
