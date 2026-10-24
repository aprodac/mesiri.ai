"""V1 audit WRK-01: work started on an earlier day and updated on the report
day is in that day's DPR, against a real Postgres (integration). Each test
runs in a transaction that is rolled back."""

from __future__ import annotations

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

pytestmark = pytest.mark.integration

DAY = dt.date(2026, 10, 22)
NEXT = DAY + dt.timedelta(days=1)
IST = ZoneInfo("Asia/Kolkata")


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


async def _update(conn, activity_id, at, kind, words, *, quantity=None, supersedes=None, deleted=False):
    update_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO progress_updates (id, activity_id, occurred_at, update_kind, narrative,"
            " quantity, unit_id, supersedes_id, deleted_at)"
            " VALUES (:id, :activity, :at, CAST(:kind AS progress_update_kind), :words, :quantity,"
            " (SELECT id FROM units_of_measure WHERE code = 'cum'), :supersedes,"
            " CASE WHEN :deleted THEN now() END)"
        ),
        {
            "id": update_id,
            "activity": activity_id,
            "at": at,
            "kind": kind,
            "words": words,
            "quantity": quantity,
            "supersedes": supersedes,
            "deleted": deleted,
        },
    )
    return update_id


async def test_earlier_work_updated_today_is_in_todays_dpr(conn) -> None:
    created = await create_company(
        conn,
        NewCompany(
            name="Carried Builders",
            owner_name="Owner",
            owner_phone="9876500077",
            project_name="Green Towers",
            site_names=("Block A",),
        ),
    )
    await conn.execute(
        text("UPDATE projects SET reporting_timezone = 'Asia/Kolkata' WHERE id = :p"),
        {"p": created.project_id},
    )
    activity_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date,"
            " work_type, narrative, status)"
            " VALUES (:id, :org, :project, :site, :day, 'brickwork', 'started brickwork ground floor',"
            " 'COMPLETED')"
        ),
        {
            "id": activity_id,
            "org": created.organization_id,
            "project": created.project_id,
            "site": created.site_id,
            "day": DAY,
        },
    )
    wrong = await _update(conn, activity_id, dt.datetime(2026, 10, 23, 10, 0, tzinfo=IST), "PROGRESS", "50% done")
    await _update(
        conn,
        activity_id,
        dt.datetime(2026, 10, 23, 10, 0, tzinfo=IST),
        "PROGRESS",
        "brickwork 60% done",
        quantity=12,
        supersedes=wrong,
    )
    await _update(conn, activity_id, dt.datetime(2026, 10, 23, 12, 0, tzinfo=IST), "NOTE", "undone", deleted=True)
    await _update(conn, activity_id, dt.datetime(2026, 10, 23, 23, 30, tzinfo=IST), "COMPLETED", "brickwork finished")
    # 00:30 on the 24th in India is still the 23rd in UTC: not the 23rd's work.
    await _update(conn, activity_id, dt.datetime(2026, 10, 24, 0, 30, tzinfo=IST), "NOTE", "pointing next")

    repo = PostgresDprRepository(conn)
    payload, items = await repo.assemble_site_day(
        organization_id=created.organization_id,
        project_id=created.project_id,
        site_id=created.site_id,
        report_date=NEXT,
    )
    (activity,) = payload["activities"]
    assert activity["narrative"] == "brickwork 60% done; brickwork finished (started 22 Oct)"
    assert activity["status"] == "COMPLETED"
    assert activity["quantities"] == [{"work_type": "brickwork", "quantity": "12.000", "unit": "cum"}]
    assert activity["carried_from"] == "2026-10-22"
    assert [i for i in items if i["section"] == "work"] == []

    # The day it started still shows it as its own work, once.
    day_one = await repo.assemble_site_report_payload(
        organization_id=created.organization_id,
        project_id=created.project_id,
        site_id=created.site_id,
        report_date=DAY,
    )
    assert [a.get("carried_from") for a in day_one["activities"]] == [None]

    # The Today page counts it too, so the site isn't "hasn't reported".
    days = await repo.list_site_days(
        organization_id=created.organization_id, project_ids=None, report_date=NEXT
    )
    (today,) = [d for d in days if d["site_id"] == created.site_id]
    assert today["work_items"] == 1
    later = await repo.list_site_days(
        organization_id=created.organization_id, project_ids=None, report_date=NEXT + dt.timedelta(days=1)
    )
    assert [d["work_items"] for d in later if d["site_id"] == created.site_id] == [1]  # 00:30 IST note
    await conn.execute(
        text("UPDATE projects SET reporting_timezone = 'India' WHERE id = :p"), {"p": created.project_id}
    )
    # An unknown zone name reads as UTC instead of failing the page or the DPR.
    await repo.list_site_days(organization_id=created.organization_id, project_ids=None, report_date=NEXT)
    await repo.assemble_site_report_payload(
        organization_id=created.organization_id,
        project_id=created.project_id,
        site_id=created.site_id,
        report_date=NEXT,
    )
