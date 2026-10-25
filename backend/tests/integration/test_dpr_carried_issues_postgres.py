"""BE-51 (audit ISS-04): an issue reported on an earlier day stays on the
site DPR while it is open, and shows on the day it was closed (integration,
real Postgres). Every test rolls back."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

pytestmark = pytest.mark.integration

DAY1, DAY2, DAY3 = dt.date(2026, 10, 20), dt.date(2026, 10, 21), dt.date(2026, 10, 22)


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
            name="Issues", owner_name="Owner",
            owner_phone=f"+91 9{uuid.uuid4().int % 10**9:09d}",
            project_name="P", site_name="S",
        ),
    )


async def _issue(conn, company, *, narrative, on, status="OPEN", resolved=None, minutes=None):
    await conn.execute(
        text(
            "INSERT INTO site_issues (id, organization_id, project_id, site_id, issue_type, occurred_at,"
            " status, narrative, resolved_at, delay_duration_minutes)"
            " VALUES (:id, :org, :project, :site, 'EQUIPMENT_BREAKDOWN', :at, :status, :narrative,"
            " :resolved, :minutes)"
        ),
        {"id": uuid.uuid4(), "org": company.organization_id, "project": company.project_id,
         "site": company.site_id, "at": _at(on), "status": status, "narrative": narrative,
         "resolved": _at(resolved) if resolved else None, "minutes": minutes},
    )


async def _day(conn, company, day):
    payload, items = await PostgresDprRepository(conn).assemble_site_day(
        organization_id=company.organization_id, project_id=company.project_id,
        site_id=company.site_id, report_date=day,
    )
    return payload, items


async def test_an_open_issue_stays_on_the_next_days_dpr(conn, company) -> None:
    await _issue(conn, company, narrative="Crane breakdown", on=DAY1, minutes=240)

    payload, items = await _day(conn, company, DAY2)

    assert payload["issues"] == []
    [carried] = payload["carried_issues"]
    assert (carried["narrative"], carried["status"], carried["reported_on"]) == (
        "Crane breakdown", "OPEN", "2026-10-20",
    )
    assert payload["open_issue_count"] == 1
    # Not the day's own entry: no hours lost, nothing to review.
    assert payload["conditions"]["hours_lost"] is None
    assert [i for i in items if i["section"] == "issues"] == []


async def test_closed_on_the_day_shows_once_then_drops(conn, company) -> None:
    await _issue(conn, company, narrative="Crane breakdown", on=DAY1, status="RESOLVED", resolved=DAY2)

    on_close, _ = await _day(conn, company, DAY2)
    after, _ = await _day(conn, company, DAY3)

    assert [(c["narrative"], c["status"]) for c in on_close["carried_issues"]] == [
        ("Crane breakdown", "RESOLVED")
    ]
    assert on_close["open_issue_count"] == 0
    assert after["carried_issues"] == []


async def test_a_past_day_shows_an_issue_closed_later_as_open(conn, company) -> None:
    await _issue(conn, company, narrative="Crane breakdown", on=DAY1, status="RESOLVED", resolved=DAY3)

    payload, _ = await _day(conn, company, DAY2)

    assert [c["status"] for c in payload["carried_issues"]] == ["OPEN"]


async def test_withdrawn_and_engineer_questions_are_not_carried(conn, company) -> None:
    await _issue(conn, company, narrative="Wrong site", on=DAY1, status="CANCELLED")
    await _issue(conn, company, narrative="Question for your engineer: which mix?", on=DAY1)

    payload, _ = await _day(conn, company, DAY2)

    assert payload["carried_issues"] == []
