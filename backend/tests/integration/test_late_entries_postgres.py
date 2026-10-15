"""BE-13: entries that reach a site day after it was confirmed, against a real
Postgres (integration). Each test runs in a transaction that is rolled back.

Inside one transaction now() never moves, so a late entry's created_at is set
explicitly to after the confirmed version was built.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.dpr import late_entries
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.projects import auto_dpr
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository
from mesiri.infrastructure.postgres.repositories.fact_reviews import (
    PostgresFactReviewRepository,
)

pytestmark = pytest.mark.integration

DAY = dt.date(2026, 10, 15)
NEXT = DAY + dt.timedelta(days=1)
EVENING_UTC = dt.datetime(2026, 10, 15, 13, 30, tzinfo=dt.UTC)


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


async def _company(conn, phone: str):
    return await create_company(
        conn,
        NewCompany(
            name=f"Late Builders {phone[-4:]}",
            owner_name="Owner",
            owner_phone=phone,
            project_name="Green Towers",
            site_names=("Block A",),
            auto_dpr=True,
        ),
        now=EVENING_UTC,
    )


async def _activity(conn, created, day, *, minutes_late: int | None = None) -> uuid.UUID:
    activity_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date,"
            " work_type, narrative, created_at)"
            " VALUES (:id, :org, :project, :site, :day, 'plastering', 'wall 2',"
            " now() + make_interval(mins => :late))"
        ),
        {
            "id": activity_id,
            "org": created.organization_id,
            "project": created.project_id,
            "site": created.site_id,
            "day": day,
            "late": minutes_late or 0,
        },
    )
    return activity_id


async def _labour(conn, created, day) -> None:
    report_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO labour_attendance_reports (id, organization_id, project_id, site_id,"
            " occurred_date, recorded_via, created_by)"
            " VALUES (:id, :org, :project, :site, :day, 'whatsapp_text', :by)"
        ),
        {
            "id": report_id,
            "org": created.organization_id,
            "project": created.project_id,
            "site": created.site_id,
            "day": day,
            "by": created.owner_user_id,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO labour_attendance_lines (id, report_id, trade, headcount)"
            " VALUES (:id, :report, 'mason', 8)"
        ),
        {"id": uuid.uuid4(), "report": report_id},
    )


async def _late_cement(conn, created, day, *, minutes_late: int, bags: int) -> uuid.UUID:
    receipt_id = uuid.uuid4()
    await conn.execute(
        text(
            """
            INSERT INTO material_receipts (id, organization_id, project_id, site_id, material_name,
                quantity, unit, occurred_date, created_by, material_id, unit_id, created_at)
            SELECT :id, :org, :project, :site, m.name, :bags, 'bags', :day, :by, m.id,
                   m.default_unit_id, now() + make_interval(mins => :late)
            FROM materials_catalog m WHERE m.organization_id = :org AND m.name = 'Cement'
            """
        ),
        {
            "id": receipt_id,
            "org": created.organization_id,
            "project": created.project_id,
            "site": created.site_id,
            "day": day,
            "by": created.owner_user_id,
            "bags": bags,
            "late": minutes_late,
        },
    )
    return receipt_id


async def _generate(conn, created, day) -> None:
    await auto_dpr.generate_project_dpr(
        conn,
        organization_id=created.organization_id,
        project_id=created.project_id,
        report_date=day,
    )


async def _site_report(conn, created, day):
    return (
        (
            await conn.execute(
                text(
                    "SELECT dr.id, dr.status::text AS status, v.version_no, v.revision_reason,"
                    " v.payload FROM daily_reports dr"
                    " JOIN daily_report_versions v ON v.id = dr.current_version_id"
                    " WHERE dr.site_id = :site AND dr.report_date = :day AND dr.level::text = 'SITE'"
                ),
                {"site": created.site_id, "day": day},
            )
        )
        .mappings()
        .one()
    )


async def _confirm(conn, created, day) -> None:
    report = await _site_report(conn, created, day)
    assert await PostgresDprRepository(conn).approve_report(
        created.organization_id, created.owner_user_id, report["id"], None
    )


async def _confirmed_day(conn, phone: str):
    created = await _company(conn, phone)
    await _activity(conn, created, DAY)
    await _labour(conn, created, DAY)
    await _generate(conn, created, DAY)
    await _confirm(conn, created, DAY)
    return created


async def test_entry_for_an_unsent_confirmed_day_reopens_it(conn) -> None:
    created = await _confirmed_day(conn, "9876500031")
    assert (await _site_report(conn, created, DAY))["status"] == "APPROVED"

    # Nothing late yet.
    result = await late_entries.process_late_entries(conn, today=NEXT)
    assert result.recorded == 0

    await _late_cement(conn, created, DAY, minutes_late=60, bags=20)
    assert (
        await late_entries.day_status_for_fact(
            conn, organization_id=created.organization_id, site_id=created.site_id, fact_date=DAY
        )
        == late_entries.REOPENED
    )
    result = await late_entries.process_late_entries(conn, today=NEXT)
    assert (result.recorded, result.reopened_days, result.revised_days) == (1, 1, 0)

    report = await _site_report(conn, created, DAY)
    assert report["status"] == "DRAFT"  # back for confirmation
    assert report["revision_reason"].startswith("late entry: Received 20 bags Cement")

    # Recorded once.
    assert (await late_entries.process_late_entries(conn, today=NEXT)).recorded == 0

    # Re-confirming the day claims it, so the next day doesn't list it again.
    await _confirm(conn, created, DAY)
    await _activity(conn, created, NEXT)
    await _generate(conn, created, NEXT)
    assert (await _site_report(conn, created, NEXT))["payload"]["late_entries"] == []


async def test_entry_for_a_sent_day_is_a_revision_and_shows_next_day_once(conn) -> None:
    created = await _confirmed_day(conn, "9876500032")
    await conn.execute(
        text("UPDATE projects SET dpr_last_sent_on = :day WHERE id = :id"),
        {"day": DAY, "id": created.project_id},
    )
    receipt_id = await _late_cement(conn, created, DAY, minutes_late=90, bags=15)
    await _activity(conn, created, DAY, minutes_late=95)

    result = await late_entries.process_late_entries(conn, today=NEXT)
    assert (result.recorded, result.reopened_days, result.revised_days) == (2, 0, 1)

    report = await _site_report(conn, created, DAY)
    assert report["status"] == "APPROVED"  # not reopened, nothing to re-send
    assert report["version_no"] >= 2 and report["revision_reason"].startswith("late entry:")

    # A late draft on a frozen day is recorded as late (so it can be removed).
    reviews = PostgresFactReviewRepository(conn)
    await reviews.mark_draft(
        organization_id=created.organization_id,
        fact_type="material_receipt",
        fact_id=receipt_id,
        extraction_id=None,
        actor_user_id=created.owner_user_id,
    )
    assert await late_entries.is_recorded_late(
        conn, fact_type="material_receipt", fact_id=receipt_id
    )

    # The next day's report lists both, once.
    await _activity(conn, created, NEXT)
    await _labour(conn, created, NEXT)
    await _generate(conn, created, NEXT)
    listed = (await _site_report(conn, created, NEXT))["payload"]["late_entries"]
    assert [e["report_date"] for e in listed] == [DAY.isoformat(), DAY.isoformat()]
    assert any("Received 15 bags Cement" in e["summary"] for e in listed)
    assert all(e["outcome"] == "revised" for e in listed)

    # Confirming the next day claims them and confirms the late draft.
    await _confirm(conn, created, NEXT)
    states = await reviews.states_for("material_receipt", [receipt_id])
    assert states[receipt_id] == "confirmed"
    unshown = (
        await conn.execute(
            text(
                "SELECT count(*) FROM late_entries WHERE site_id = :site"
                " AND shown_in_report_id IS NULL"
            ),
            {"site": created.site_id},
        )
    ).scalar()
    assert unshown == 0


async def test_open_days_and_old_entries_are_not_late(conn) -> None:
    created = await _company(conn, "9876500033")
    await _activity(conn, created, DAY)
    await _generate(conn, created, DAY)  # not confirmed: still open
    await _late_cement(conn, created, DAY, minutes_late=30, bags=5)
    assert (await late_entries.process_late_entries(conn, today=NEXT)).recorded == 0
    assert (
        await late_entries.day_status_for_fact(
            conn, organization_id=created.organization_id, site_id=created.site_id, fact_date=DAY
        )
        is None
    )


async def test_a_late_entry_on_a_frozen_day_can_be_removed(conn) -> None:
    created = await _confirmed_day(conn, "9876500034")
    await conn.execute(
        text("UPDATE projects SET dpr_last_sent_on = :day WHERE id = :id"),
        {"day": DAY, "id": created.project_id},
    )
    on_time = (await _site_report(conn, created, DAY))["id"]
    receipt_id = await _late_cement(conn, created, DAY, minutes_late=45, bags=3)
    reviews = PostgresFactReviewRepository(conn)
    await reviews.mark_draft(
        organization_id=created.organization_id,
        fact_type="material_receipt",
        fact_id=receipt_id,
        extraction_id=None,
        actor_user_id=created.owner_user_id,
    )
    await late_entries.process_late_entries(conn, today=NEXT)

    # The frozen day refuses removals, but not of an entry that was never in it.
    await reviews.reject(
        organization_id=created.organization_id,
        fact_type="material_receipt",
        fact_id=receipt_id,
        actor_user_id=created.owner_user_id,
        reason="sent by mistake",
    )
    assert (await reviews.states_for("material_receipt", [receipt_id]))[receipt_id] == "rejected"
    assert (await _site_report(conn, created, DAY))["id"] == on_time
