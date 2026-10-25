"""BE-37: withdrawing an attendance report tells the timeline (integration,
real Postgres). It used to write nothing, so the dashboard timeline kept
"N workers recorded" with no sign it was withdrawn. Every test rolls back."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.events.consumers.timeline_projector import project_pending_events
from mesiri.infrastructure.postgres.repositories.workforce import PostgresWorkforceReadRepository

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


async def _report(conn):
    company = await create_company(
        conn,
        NewCompany(
            name="Void", owner_name="Owner",
            owner_phone=f"+91 9{uuid.uuid4().int % 10**9:09d}",
            project_name="P", site_name="S",
        ),
    )
    report_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO labour_attendance_reports (id, organization_id, project_id, site_id,"
            " occurred_date, recorded_via, created_by)"
            " VALUES (:id, :org, :project, :site, :day, 'whatsapp_text', :user)"
        ),
        {"id": report_id, "org": company.organization_id, "project": company.project_id,
         "site": company.site_id, "day": dt.date(2026, 10, 20), "user": company.owner_user_id},
    )
    return company, report_id


async def test_withdrawing_attendance_shows_on_the_timeline(conn) -> None:
    company, report_id = await _report(conn)
    repo = PostgresWorkforceReadRepository(conn)

    assert await repo.void_attendance_report(
        organization_id=company.organization_id, report_id=report_id,
        reason="sent twice", voided_by_user_id=company.owner_user_id,
    ) is None
    await project_pending_events(conn, batch_size=1000)

    rows = (
        await conn.execute(
            text("SELECT event_type, summary, site_id FROM timeline_entries WHERE organization_id = :org"),
            {"org": company.organization_id},
        )
    ).mappings().all()
    voided = [r for r in rows if r["event_type"] == "LabourAttendanceVoided"]
    assert len(voided) == 1
    assert voided[0]["summary"] == "Attendance withdrawn"
    assert voided[0]["site_id"] == company.site_id


async def test_a_second_withdrawal_writes_nothing_more(conn) -> None:
    company, report_id = await _report(conn)
    repo = PostgresWorkforceReadRepository(conn)
    kw = dict(organization_id=company.organization_id, report_id=report_id, reason="x", voided_by_user_id=None)

    await repo.void_attendance_report(**kw)
    assert await repo.void_attendance_report(**kw) is not None

    count = (
        await conn.execute(
            text("SELECT count(*) FROM outbox_events WHERE aggregate_id = :id AND event_type = 'LabourAttendanceVoided'"),
            {"id": report_id},
        )
    ).scalar_one()
    assert count == 1
