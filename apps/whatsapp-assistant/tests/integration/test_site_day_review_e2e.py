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
from channel.whatsapp.templates import SITE_DAY_REVIEW, SITE_NO_UPDATE
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
        # A removed item (WA-05) leaves its correction; a confirmed day names
        # who confirmed it.
        await conn.execute(
            text(
                "DELETE FROM activity_corrections WHERE activity_id IN"
                " (SELECT id FROM activities WHERE organization_id = :o)"
            ),
            {"o": org},
        )
        await conn.execute(
            text(
                "UPDATE daily_report_versions SET approved_by_user_id = NULL WHERE daily_report_id IN"
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

    # 1. A gap-check for Block A; Block B sent nothing: the no-update
    #    reminder (WA-06).
    assert await _review(db) == 2
    assert await _review(db) == 0  # once a day
    async with db.transaction() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT rule_key, recipient_user_id, payload FROM notifications"
                    " WHERE organization_id = :o ORDER BY rule_key"
                ),
                {"o": created.organization_id},
            )
        ).mappings().all()
    assert [(r["rule_key"], r["recipient_user_id"]) for r in rows] == [
        (f"site_day_gap:{block_a}", world.engineer_id),
        (f"site_day_no_update:{block_b}", world.engineer_id),
    ]
    reminder = rows[1]["payload"]
    reminder = json.loads(reminder) if isinstance(reminder, str) else reminder
    assert "No update has come in today for *Block B*" in reminder["message"]
    payload = rows[0]["payload"]
    payload = json.loads(payload) if isinstance(payload, str) else payload
    assert "missing the *labour count*" in payload["message"]
    assert payload["template"]["body_params"] == [
        "Block A (Green Towers)",
        "Labour count is missing.",
        "9:00 pm",
    ]

    # 2. Delivered: Ravi never messaged, so the approved templates go, each
    #    tap carrying the site and day.
    captured: list[dict] = []
    counts = await drain_and_send(
        db=db,
        actor_reader=PostgresActorReader(),
        sender=_meta(captured),
        approved_templates=frozenset({SITE_DAY_REVIEW.name, SITE_NO_UPDATE.name}),
        now_utc=EVENING_UTC,
    )
    assert counts == {"sent": 2, "skipped": 0}
    by_name = {c["template"]["name"]: c for c in captured}
    assert by_name["mesiri_site_no_update"]["template"]["components"][-1]["parameters"] == [
        {"type": "payload", "payload": f"sdr:closed:{block_b}:20261015"}
    ]
    sent = by_name["mesiri_site_day_review"]
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
    # The day turns ready, so the confirmation goes (WA-05): nothing to
    # check, so it offers Confirm all.
    assert await _review(db) == 1
    status, missing = await _status(db, block_a)
    assert status == "READY"
    assert missing["blocking"] == []
    async with db.transaction() as conn:
        confirm = (
            await conn.execute(
                text(
                    "SELECT payload FROM notifications WHERE organization_id = :o"
                    " AND rule_key = :k"
                ),
                {"o": created.organization_id, "k": f"site_day_confirm:{block_a}"},
            )
        ).scalar_one()
    confirm = json.loads(confirm) if isinstance(confirm, str) else confirm
    assert "today's report is ready" in confirm["message"]
    assert "• Labour: 9 workers" in confirm["message"]
    assert [b["title"] for b in confirm["buttons"]] == ["Confirm all", "Fix something"]
    assert confirm["template"]["body_params"][1] == "It is ready to confirm."

    # 5. The reminder's "Site closed today" for Block B: no work, nothing required.
    closed = await review.handle_tap(
        SimpleNamespace(metadata={"interactive_reply_id": f"sdr:closed:{block_b}:20261015"}), actor
    )
    assert closed.text == "👍 Marked *Block B* as closed today. Today's report will say there was no work."
    assert await _status(db, block_b) == ("READY", {"blocking": [], "optional": []})

    # 6. Ravi taps "Confirm all" for Block A: the day is confirmed.
    done = await review.handle_tap(
        SimpleNamespace(metadata={"interactive_reply_id": f"sdr:confirm:{block_a}:20261015"}), actor
    )
    assert done.text == site_day_review.CONFIRMED_DONE.format(site="Block A")
    assert (await _status(db, block_a))[0] == "APPROVED"
    again = await review.handle_tap(
        SimpleNamespace(metadata={"interactive_reply_id": f"sdr:confirm:{block_a}:20261015"}), actor
    )
    assert again.text == site_day_review.ALREADY_CONFIRMED.format(site="Block A")


async def test_confirm_all_is_held_back_until_the_unsure_item_is_checked(world) -> None:
    """WA-05: an item the AI was unsure of holds back Confirm all; Fix
    something lists it, Keep clears it, and the day can then be confirmed.
    A removed item is withdrawn (BE-09's reject)."""
    from mesiri.infrastructure.postgres.repositories.fact_reviews import (
        PostgresFactReviewRepository,
    )

    db, created = world.db, world.created
    block_a = created.sites[0].site_id
    async with db.transaction() as conn:
        work_id = (
            await conn.execute(
                text("SELECT id FROM activities WHERE site_id = :s"), {"s": block_a}
            )
        ).scalar_one()
        await conn.execute(
            text("UPDATE activities SET work_type = 'Plastering', narrative = 'wall 2' WHERE id = :id"),
            {"id": work_id},
        )
        extra_id = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date,"
                " work_type, narrative) VALUES (:id, :org, :p, :s, :d, 'Tiling', 'lobby')"
            ),
            {"id": extra_id, "org": created.organization_id, "p": created.project_id, "s": block_a, "d": DAY},
        )
        report_id = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO labour_attendance_reports (id, organization_id, project_id, site_id,"
                " occurred_date, recorded_via, created_by)"
                " VALUES (:id, :o, :p, :s, :d, 'whatsapp_text', :u)"
            ),
            {"id": report_id, "o": created.organization_id, "p": created.project_id, "s": block_a, "d": DAY, "u": world.engineer_id},
        )
        await conn.execute(
            text(
                "INSERT INTO labour_attendance_lines (id, report_id, trade, headcount)"
                " VALUES (:id, :r, 'mason', 9)"
            ),
            {"id": uuid.uuid4(), "r": report_id},
        )
        reviews = PostgresFactReviewRepository(conn)
        unsure = await reviews.record_extraction(
            organization_id=created.organization_id,
            extracted={"action_type": "activity", "fields": {}},
            confidence="low",
        )
        await reviews.mark_draft(
            organization_id=created.organization_id, fact_type="activity", fact_id=work_id,
            extraction_id=unsure, actor_user_id=world.engineer_id,
        )
        forwarded = await reviews.record_extraction(
            organization_id=created.organization_id,
            extracted={"action_type": "activity", "fields": {"is_forwarded": True, "occurred_date_source": "stated_by_user"}},
            confidence="high",
        )
        await reviews.mark_draft(
            organization_id=created.organization_id, fact_type="activity", fact_id=extra_id,
            extraction_id=forwarded, actor_user_id=world.engineer_id,
        )

    assert await _review(db) >= 1
    async with db.transaction() as conn:
        confirm = (
            await conn.execute(
                text("SELECT payload FROM notifications WHERE rule_key = :k"),
                {"k": f"site_day_confirm:{block_a}"},
            )
        ).scalar_one()
    confirm = json.loads(confirm) if isinstance(confirm, str) else confirm
    assert "• 1 item I wasn't sure I read right" in confirm["message"]
    assert [b["title"] for b in confirm["buttons"]] == ["Fix something"]

    actor = await PostgresActorReader().resolve_by_whatsapp_id(ENGINEER_WA)
    review = site_day_review.SiteDayReview(db=db)

    def tap(value: str):
        return review.handle_tap(SimpleNamespace(metadata={"interactive_reply_id": value}), actor)

    # Confirm all is refused while the unsure item is there.
    held = await tap(f"sdr:confirm:{block_a}:20261015")
    assert "Please check first" in held.text
    assert (await _status(db, block_a))[0] == "READY"

    listed = await tap(f"sdr:fix:{block_a}:20261015")
    titles = [row.title for row in listed.list_rows]
    assert sorted(titles) == ["Plastering", "Tiling"]

    picked = await tap(f"sdr:item:{block_a}:20261015:activity:{work_id}")
    assert picked.text.startswith("*Plastering*")
    assert [b.title for b in picked.buttons] == ["Keep it", "Remove it"]

    kept = await tap(f"sdr:keep:{block_a}:20261015:activity:{work_id}")
    assert "Please check first" not in kept.text
    assert [b.title for b in kept.buttons] == ["Confirm all", "Fix something"]

    removed = await tap(f"sdr:rm:{block_a}:20261015:activity:{extra_id}")
    assert "• Work: 1 item" in removed.text
    gone = await tap(f"sdr:rm:{block_a}:20261015:activity:{extra_id}")
    assert gone.text == site_day_review.ITEM_GONE

    done = await tap(f"sdr:confirm:{block_a}:20261015")
    assert done.text == site_day_review.CONFIRMED_DONE.format(site="Block A")
    assert (await _status(db, block_a))[0] == "APPROVED"


async def test_a_tap_for_a_site_of_another_company_is_refused(world) -> None:
    actor = await PostgresActorReader().resolve_by_whatsapp_id(ENGINEER_WA)
    reply = await site_day_review.SiteDayReview(db=world.db).handle_tap(
        SimpleNamespace(metadata={"interactive_reply_id": f"sdr:closed:{uuid.uuid4()}:20261015"}),
        actor,
    )
    assert reply.text == site_day_review.NOT_YOUR_SITE
