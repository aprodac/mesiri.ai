"""WRK-01 (audit 04): work started on an earlier day and updated on a later one
reaches that later day's DPR and the Today page (integration, real Postgres).
Every test rolls back."""

from __future__ import annotations

import datetime as dt
import itertools
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

pytestmark = pytest.mark.integration

DAY1, DAY2 = dt.date(2026, 10, 20), dt.date(2026, 10, 21)
_clock = itertools.count(1)


def _at(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(6, 0), tzinfo=dt.UTC)


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


@pytest.fixture
async def company(conn):
    return await create_company(
        conn,
        NewCompany(
            name="Work", owner_name="Owner",
            owner_phone=f"+91 9{uuid.uuid4().int % 10**9:09d}",
            project_name="P", site_name="S",
        ),
    )


async def _activity(conn, company, *, work_type, on, status="IN_PROGRESS", narrative=None):
    activity_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO activities (id, organization_id, project_id, site_id, work_type, narrative,"
            " activity_date, status) VALUES (:id, :org, :project, :site, :work, :narrative, :day,"
            " CAST(:status AS activity_status))"
        ),
        {"id": activity_id, "org": company.organization_id, "project": company.project_id,
         "site": company.site_id, "work": work_type, "narrative": narrative or work_type,
         "day": on, "status": status},
    )
    return activity_id


async def _update(conn, activity_id, *, on, kind, narrative, deleted=False):
    update_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO progress_updates (id, activity_id, occurred_at, update_kind, narrative,"
            " deleted_at, created_at) VALUES (:id, :activity, :at, CAST(:kind AS progress_update_kind),"
            " :narrative, :deleted, :created)"
        ),
        {"id": update_id, "activity": activity_id, "at": _at(on), "kind": kind,
         "narrative": narrative, "deleted": _at(on) if deleted else None,
         # one transaction means one now(): order the rows as they were sent
         "created": _at(on) + dt.timedelta(minutes=next(_clock))},
    )
    return update_id


async def _day(conn, company, day):
    return await PostgresDprRepository(conn).assemble_site_day(
        organization_id=company.organization_id, project_id=company.project_id,
        site_id=company.site_id, report_date=day,
    )


async def test_wrk01_work_continued_on_a_later_day_is_on_that_days_report(conn, company):
    brickwork = await _activity(conn, company, work_type="brickwork", on=DAY1)
    await _update(conn, brickwork, on=DAY2, kind="PROGRESS", narrative="Brickwork 60% done")
    await _update(conn, brickwork, on=DAY2, kind="COMPLETED", narrative="Brickwork finished")

    day2, items = await _day(conn, company, DAY2)
    assert day2["activity_count"] == 1
    work = day2["activities"][0]
    assert (work["work_type"], work["continued"], work["started_on"]) == ("brickwork", True, str(DAY1))
    # that day's latest update stands in for the activity's own words and status
    assert (work["narrative"], work["status"]) == ("Brickwork finished", "COMPLETED")
    # an update is confirmed with the work it belongs to: no second review item
    assert [i for i in items if i["section"] == "work"] == []

    day1, day1_items = await _day(conn, company, DAY1)
    assert [a["continued"] for a in day1["activities"]] == [False]
    assert len([i for i in day1_items if i["section"] == "work"]) == 1


async def test_wrk01_day_two_shows_the_days_own_percent_not_day_ones(conn, company):
    plastering = await _activity(conn, company, work_type="plastering", on=DAY1, narrative="started")
    await _update(conn, plastering, on=DAY2, kind="PROGRESS", narrative="Plastering 40%")

    day2, _ = await _day(conn, company, DAY2)
    assert [(a["narrative"], a["status"]) for a in day2["activities"]] == [("Plastering 40%", "IN_PROGRESS")]


async def test_wrk01_a_withdrawn_update_does_not_bring_the_work_in(conn, company):
    wiring = await _activity(conn, company, work_type="wiring", on=DAY1)
    await _update(conn, wiring, on=DAY2, kind="PROGRESS", narrative="Wiring 30%", deleted=True)

    day2, _ = await _day(conn, company, DAY2)
    assert day2["activity_count"] == 0


async def test_wrk01_work_started_and_updated_the_same_day_is_listed_once(conn, company):
    slab = await _activity(conn, company, work_type="slab", on=DAY2)
    await _update(conn, slab, on=DAY2, kind="PROGRESS", narrative="Slab 50%")

    day2, _ = await _day(conn, company, DAY2)
    assert [(a["work_type"], a["continued"]) for a in day2["activities"]] == [("slab", False)]


async def test_wrk01_today_page_counts_the_continued_work(conn, company):
    brickwork = await _activity(conn, company, work_type="brickwork", on=DAY1)
    await _update(conn, brickwork, on=DAY2, kind="PROGRESS", narrative="Brickwork 60% done")

    days = await PostgresDprRepository(conn).list_site_days(
        organization_id=company.organization_id, project_ids=None, report_date=DAY2
    )
    mine = next(d for d in days if d["site_id"] == company.site_id)
    assert mine["work_items"] == 1
