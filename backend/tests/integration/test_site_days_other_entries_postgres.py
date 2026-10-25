"""WEB-32: the Today page's site list counts every kind of entry a site
sent, not only work items and labour (integration, real Postgres).

A site that sent only materials, an issue, or progress on work started on
an earlier day used to read "hasn't reported today". Every test rolls back.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

pytestmark = pytest.mark.integration

DAY = dt.date(2026, 10, 20)
NOON = dt.datetime(2026, 10, 20, 6, 30, tzinfo=dt.UTC)


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
            name="Seams", owner_name="Owner",
            owner_phone=f"+91 9{uuid.uuid4().int % 10**9:09d}",
            project_name="P", site_name="S",
        ),
    )


async def _day(conn, company) -> dict:
    days = await PostgresDprRepository(conn).list_site_days(
        organization_id=company.organization_id, project_ids=None, report_date=DAY
    )
    return next(d for d in days if d["site_id"] == company.site_id)


async def _movement(conn, company, *, reversal_of: uuid.UUID | None = None) -> uuid.UUID:
    unit_id = (await conn.execute(text("SELECT id FROM units_of_measure WHERE code = 'bags'"))).scalar_one()
    material_id = (
        await conn.execute(
            text(
                "INSERT INTO materials_catalog (id, organization_id, name, created_by, default_unit_id)"
                " VALUES (:id, :org, :name, :user, :unit) RETURNING id"
            ),
            {"id": uuid.uuid4(), "org": company.organization_id, "name": f"Cement {uuid.uuid4().hex[:6]}",
             "user": company.owner_user_id, "unit": unit_id},
        )
    ).scalar_one()
    movement_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO material_movements (id, organization_id, project_id, site_id, material_id, unit_id,"
            " movement_type, quantity, occurred_at, source_type, source_id, recorded_by_user_id,"
            " reversal_of_movement_id)"
            " VALUES (:id, :org, :project, :site, :material, :unit, 'RECEIPT', 10, :at, 'material_receipt',"
            " :source, :user, :reversal)"
        ),
        {"id": movement_id, "org": company.organization_id, "project": company.project_id,
         "site": company.site_id, "material": material_id, "unit": unit_id, "at": NOON,
         "source": uuid.uuid4(), "user": company.owner_user_id, "reversal": reversal_of},
    )
    return movement_id


async def test_quiet_site_has_no_other_entries(conn, company) -> None:
    day = await _day(conn, company)
    assert (day["materials"], day["issues_today"], day["progress_updates"]) == (0, 0, 0)
    assert day["last_update_at"] is None


async def test_materials_count_and_corrections_cancel_out(conn, company) -> None:
    await _movement(conn, company)
    corrected = await _movement(conn, company)
    await _movement(conn, company, reversal_of=corrected)

    day = await _day(conn, company)

    assert day["materials"] == 1
    assert day["last_update_at"] is not None


async def test_issue_raised_today_counts_but_not_a_cancelled_one(conn, company) -> None:
    for status in ("OPEN", "CANCELLED"):
        await conn.execute(
            text(
                "INSERT INTO site_issues (id, organization_id, project_id, site_id, issue_type, occurred_at,"
                " status, narrative) VALUES (:id, :org, :project, :site, 'ACCESS', :at, :status, 'Gate locked')"
            ),
            {"id": uuid.uuid4(), "org": company.organization_id, "project": company.project_id,
             "site": company.site_id, "at": NOON, "status": status},
        )

    assert (await _day(conn, company))["issues_today"] == 1


async def test_progress_on_earlier_work_counts(conn, company) -> None:
    activity_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date, work_type)"
            " VALUES (:id, :org, :project, :site, :started, 'Plastering')"
        ),
        {"id": activity_id, "org": company.organization_id, "project": company.project_id,
         "site": company.site_id, "started": DAY - dt.timedelta(days=2)},
    )
    await conn.execute(
        text(
            "INSERT INTO progress_updates (id, activity_id, occurred_at, update_kind)"
            " VALUES (:id, :activity, :at, 'PROGRESS')"
        ),
        {"id": uuid.uuid4(), "activity": activity_id, "at": NOON},
    )

    day = await _day(conn, company)

    assert day["progress_updates"] == 1
    assert day["work_items"] == 0
