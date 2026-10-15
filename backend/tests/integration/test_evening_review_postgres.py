"""WA-04: the evening review's reads and the after-cutoff refresh against a
real Postgres (integration). Each test runs in a transaction that is rolled
back."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.dpr import evening_review
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.projects import auto_dpr

pytestmark = pytest.mark.integration

DAY = dt.date(2026, 10, 15)
# 19:00 in India: after the 18:00 cutoff, before the 21:00 deadline.
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


async def _company(conn, phone: str, sites: tuple[str, ...] = ("Block A",)):
    return await create_company(
        conn,
        NewCompany(
            name=f"Evening Builders {phone[-4:]}",
            owner_name="Owner",
            owner_phone=phone,
            project_name="Green Towers",
            site_names=sites,
            auto_dpr=True,
        ),
        now=EVENING_UTC,
    )


async def _activity(conn, created, site_id) -> None:
    await conn.execute(
        text(
            "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date)"
            " VALUES (:id, :org, :project, :site, :day)"
        ),
        {
            "id": uuid.uuid4(),
            "org": created.organization_id,
            "project": created.project_id,
            "site": site_id,
            "day": DAY,
        },
    )


async def _labour(conn, created, site_id, headcount: int) -> None:
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
            "site": site_id,
            "day": DAY,
            "by": created.owner_user_id,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO labour_attendance_lines (id, report_id, trade, headcount)"
            " VALUES (:id, :report, 'mason', :n)"
        ),
        {"id": uuid.uuid4(), "report": report_id, "n": headcount},
    )


async def _cutoff(conn, created) -> None:
    await auto_dpr.generate_project_dpr(
        conn,
        organization_id=created.organization_id,
        project_id=created.project_id,
        report_date=DAY,
    )
    await auto_dpr.mark_project_auto_dpr_run(conn, project_id=created.project_id, ran_on=DAY)


async def _days(conn, created):
    days = await auto_dpr.site_days_for_review(
        conn,
        organization_id=created.organization_id,
        project_id=created.project_id,
        report_date=DAY,
    )
    return {day["site_name"]: day for day in days}


def _step(day) -> str | None:
    return evening_review.evening_step(
        status=day["status"], missing=day["missing_sections"], has_facts=day["has_facts"]
    )


async def _version_count(conn, daily_report_id) -> int:
    return (
        await conn.execute(
            text("SELECT count(*) FROM daily_report_versions WHERE daily_report_id = :id"),
            {"id": daily_report_id},
        )
    ).scalar_one()


async def test_after_the_cutoff_each_site_gets_its_evening_step(conn) -> None:
    created = await _company(conn, "+91 98765 20001", sites=("Block A", "Block B", "Block C"))
    site_a, site_b, _ = (site.site_id for site in created.sites)
    await _activity(conn, created, site_a)  # work, no labour
    await _activity(conn, created, site_b)
    await _labour(conn, created, site_b, 12)  # work and labour
    await _cutoff(conn, created)

    days = await _days(conn, created)

    assert _step(days["Block A"]) == evening_review.GAP_CHECK
    assert days["Block A"]["missing_sections"]["blocking"] == ["labour"]
    assert _step(days["Block B"]) == evening_review.CONFIRM
    assert _step(days["Block C"]) == evening_review.NO_UPDATE
    assert days["Block C"]["has_facts"] is False


async def test_a_labour_count_sent_after_the_gap_check_makes_the_day_ready(conn) -> None:
    created = await _company(conn, "+91 98765 20002")
    await _activity(conn, created, created.site_id)
    await _cutoff(conn, created)
    await _labour(conn, created, created.site_id, 8)

    day = (await _days(conn, created))["Block A"]
    assert evening_review.needs_refresh(
        last_fact_at=day["last_fact_at"], day_updated_at=day["day_updated_at"]
    )
    refreshed = await auto_dpr.refresh_site_day(
        conn,
        organization_id=created.organization_id,
        project_id=created.project_id,
        site_id=created.site_id,
        report_date=DAY,
    )

    assert refreshed == {
        "status": "READY",
        "missing_sections": {"blocking": [], "optional": ["photos", "materials", "weather", "tomorrow_plan"]},
    }
    assert _step((await _days(conn, created))["Block A"]) == evening_review.CONFIRM


async def test_a_refresh_with_nothing_new_writes_no_version(conn) -> None:
    created = await _company(conn, "+91 98765 20003")
    await _activity(conn, created, created.site_id)
    await _cutoff(conn, created)
    day = (await _days(conn, created))["Block A"]
    before = await _version_count(conn, day["daily_report_id"])

    await auto_dpr.refresh_site_day(
        conn,
        organization_id=created.organization_id,
        project_id=created.project_id,
        site_id=created.site_id,
        report_date=DAY,
    )

    assert await _version_count(conn, day["daily_report_id"]) == before


async def test_labour_alone_on_a_day_with_no_version_gets_a_version(conn) -> None:
    created = await _company(conn, "+91 98765 20004")
    await _cutoff(conn, created)  # nothing sent: labelled, no version
    await _labour(conn, created, created.site_id, 5)

    refreshed = await auto_dpr.refresh_site_day(
        conn,
        organization_id=created.organization_id,
        project_id=created.project_id,
        site_id=created.site_id,
        report_date=DAY,
    )
    day = (await _days(conn, created))["Block A"]

    assert refreshed["status"] == "NEEDS_DETAILS"
    assert refreshed["missing_sections"]["blocking"] == ["work_done"]
    assert await _version_count(conn, day["daily_report_id"]) == 1
    assert _step(day) == evening_review.GAP_CHECK


async def test_a_confirmed_day_is_not_refreshed(conn) -> None:
    created = await _company(conn, "+91 98765 20005")
    await _activity(conn, created, created.site_id)
    await _cutoff(conn, created)
    await conn.execute(
        text("UPDATE daily_reports SET status = 'APPROVED' WHERE site_id = :site"),
        {"site": created.site_id},
    )

    assert (
        await auto_dpr.refresh_site_day(
            conn,
            organization_id=created.organization_id,
            project_id=created.project_id,
            site_id=created.site_id,
            report_date=DAY,
        )
        is None
    )


async def test_the_review_window_runs_from_the_cutoff_to_the_deadline(conn) -> None:
    created = await _company(conn, "+91 98765 20006")
    nine_pm_ist = dt.datetime(2026, 10, 15, 15, 30, tzinfo=dt.UTC)

    async def window(now_utc):
        rows = await auto_dpr.projects_in_review_window(conn, now_utc=now_utc)
        return {row["id"]: row for row in rows}

    assert created.project_id not in await window(EVENING_UTC)  # cutoff not run yet
    await _cutoff(conn, created)

    row = (await window(EVENING_UTC))[created.project_id]
    assert row["report_date"] == DAY
    assert row["send_deadline"] == "21:00"
    assert created.project_id not in await window(nine_pm_ist)  # the DPR goes out now

    await conn.execute(
        text("UPDATE projects SET dpr_last_sent_on = :d WHERE id = :id"),
        {"d": DAY, "id": created.project_id},
    )
    assert created.project_id not in await window(EVENING_UTC)


async def test_the_reporters_of_the_day_are_found_from_their_drafts(conn) -> None:
    created = await _company(conn, "+91 98765 20007")
    activity_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date)"
            " VALUES (:id, :org, :project, :site, :day)"
        ),
        {
            "id": activity_id,
            "org": created.organization_id,
            "project": created.project_id,
            "site": created.site_id,
            "day": DAY,
        },
    )
    from mesiri.infrastructure.postgres.repositories.fact_reviews import (
        PostgresFactReviewRepository,
    )

    await PostgresFactReviewRepository(conn).mark_draft(
        organization_id=created.organization_id,
        fact_type="activity",
        fact_id=activity_id,
        actor_user_id=created.owner_user_id,
    )

    assert await auto_dpr.site_day_reporters(
        conn, organization_id=created.organization_id, site_id=created.site_id, report_date=DAY
    ) == [str(created.owner_user_id)]
