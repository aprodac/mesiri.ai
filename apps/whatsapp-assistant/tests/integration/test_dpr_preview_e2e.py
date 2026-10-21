"""WA-40 against a real database: the "so far today" preview reads the day the
report will be built from, and writes nothing."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.database import PostgresDatabase
from runtime.dpr_request_query import DprRequestQueryService

pytestmark = pytest.mark.integration

DAY = dt.date(2026, 10, 21)


async def test_the_preview_is_the_days_sections_and_stores_nothing():
    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    async with db.transaction() as conn:
        created = await create_company(
            conn,
            NewCompany(
                name=f"Preview E2E {uuid.uuid4().hex[:6]}",
                owner_name="Owner",
                owner_phone=f"9196{uuid.uuid4().int % 10**8:08d}",
                project_name="Green Villa",
                site_names=("Kakkanad",),
            ),
            now=dt.datetime(2026, 10, 21, 6, tzinfo=dt.UTC),
        )
        for _ in range(2):
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
    try:
        lines = await DprRequestQueryService(db).preview_lines(
            organization_id=str(created.organization_id),
            project_id=str(created.project_id),
            site_id=str(created.sites[0].site_id),
            report_date=DAY,
        )
        assert lines == ["• Work: 2 items"]
        async with db.transaction() as conn:
            reports = (
                await conn.execute(
                    text("SELECT count(*) FROM daily_reports WHERE organization_id = :o"),
                    {"o": created.organization_id},
                )
            ).scalar_one()
        assert reports == 0  # a preview, never a report
    finally:
        async with db.transaction() as conn:
            await conn.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": created.organization_id})
        await db.disconnect()


async def test_a_day_waiting_on_details_is_not_called_signed_off():
    """Round 3b: a NEEDS_DETAILS day read as signed off, so "send today's
    report" said "being prepared, ask again in a few minutes"."""
    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    async with db.transaction() as conn:
        created = await create_company(
            conn,
            NewCompany(
                name=f"Waiting E2E {uuid.uuid4().hex[:6]}",
                owner_name="Owner",
                owner_phone=f"9197{uuid.uuid4().int % 10**8:08d}",
                project_name="Green Villa",
                site_names=("Kakkanad",),
            ),
            now=dt.datetime(2026, 10, 21, 6, tzinfo=dt.UTC),
        )
        await conn.execute(
            text(
                "INSERT INTO daily_reports (id, organization_id, project_id, site_id, level,"
                " report_date, code, status, missing_sections)"
                " VALUES (:id, :o, :p, :s, 'SITE', :d, 'DPR-T', 'NEEDS_DETAILS',"
                " '{\"blocking\": [\"work_done\"]}'::jsonb)"
            ),
            {
                "id": uuid.uuid4(),
                "o": created.organization_id,
                "p": created.project_id,
                "s": created.sites[0].site_id,
                "d": DAY,
            },
        )
    try:
        found = await DprRequestQueryService(db).find_report(
            organization_id=str(created.organization_id),
            project_id=str(created.project_id),
            site_id=str(created.sites[0].site_id),
            report_date=DAY,
        )
        assert found["status"] == "pending_confirmation"
        assert found["confirmed"] is False
        assert found["missing"] == ["work_done"]
    finally:
        await db.disconnect()
