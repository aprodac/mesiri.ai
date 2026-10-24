"""WEB-24: the Analytics read model against a real Postgres (integration).

Totals over the whole range (not the first page of a list), the same worker
rule as the DPR, and the same scope as the Reports list: company, project,
site, and BE-42's custom site scope. Every test rolls back.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.infrastructure.postgres.repositories.analytics import PostgresAnalyticsRepository

pytestmark = pytest.mark.integration

DAY = dt.date(2026, 10, 20)


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


async def _company(conn, name: str):
    return await create_company(
        conn,
        NewCompany(
            name=name,
            owner_name="Owner",
            owner_phone=f"+91 9{uuid.uuid4().int % 10**9:09d}",
            project_name="P",
            site_names=("A", "B"),
        ),
    )


async def _day(conn, created, site_id, *, workers: int, work_items: int, day=DAY) -> None:
    for _ in range(work_items):
        await conn.execute(
            text(
                "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date)"
                " VALUES (:id, :org, :p, :s, :d)"
            ),
            {"id": uuid.uuid4(), "org": created.organization_id, "p": created.project_id, "s": site_id, "d": day},
        )
    report = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO labour_attendance_reports (id, organization_id, project_id, site_id, occurred_date,"
            " recorded_via, created_by) VALUES (:id, :org, :p, :s, :d, 'whatsapp_text', :by)"
        ),
        {"id": report, "org": created.organization_id, "p": created.project_id, "s": site_id, "d": day, "by": created.owner_user_id},
    )
    await conn.execute(
        text("INSERT INTO labour_attendance_lines (id, report_id, trade, headcount) VALUES (:id, :r, 'mason', :n)"),
        {"id": uuid.uuid4(), "r": report, "n": workers},
    )


def _summary(conn, created, **kw):
    args = dict(
        organization_id=created.organization_id,
        project_ids=None,
        site_id=None,
        restricted_project_ids=set(),
        allowed_site_ids=set(),
        date_from=DAY - dt.timedelta(days=1),
        date_to=DAY,
    )
    args.update(kw)
    return PostgresAnalyticsRepository(conn).summary(**args)


async def test_totals_per_day_and_per_site(conn) -> None:
    mine = await _company(conn, "Mine")
    a, b = (s.site_id for s in mine.sites)
    await _day(conn, mine, a, workers=10, work_items=3)
    await _day(conn, mine, b, workers=5, work_items=1)
    other = await _company(conn, "Other")
    await _day(conn, other, other.sites[0].site_id, workers=99, work_items=9)

    result = await _summary(conn, mine)

    assert [d["day"] for d in result["days"]] == [(DAY - dt.timedelta(days=1)).isoformat(), DAY.isoformat()]
    today = result["days"][-1]
    assert (today["workers"], today["work_items"]) == (15, 4)  # the other company is not counted
    by_site = {s["site_id"]: s for s in result["sites"]}
    assert by_site[str(a)]["days_with_updates"] == 1
    assert by_site[str(a)]["days_confirmed"] == 0
    assert len(result["sites"]) == 2


async def test_site_filter_and_custom_site_scope(conn) -> None:
    mine = await _company(conn, "Mine")
    a, b = (s.site_id for s in mine.sites)
    await _day(conn, mine, a, workers=10, work_items=3)
    await _day(conn, mine, b, workers=5, work_items=1)

    only_a = await _summary(conn, mine, site_id=a)
    assert only_a["days"][-1]["workers"] == 10

    # BE-42: a member limited to site B of this project sees only B.
    scoped = await _summary(conn, mine, restricted_project_ids={mine.project_id}, allowed_site_ids={b})
    assert scoped["days"][-1]["workers"] == 5
    assert [s["site_id"] for s in scoped["sites"]] == [str(b)]

    other_project = await _summary(conn, mine, project_ids={uuid.uuid4()})
    assert other_project["days"][-1]["workers"] == 0
    assert other_project["sites"] == []
