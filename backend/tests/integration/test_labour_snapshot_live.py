"""BE-10: labour is a snapshot per site and day, against a real Postgres.

A figure re-sent later the same day replaces the earlier one -- latest per
contractor + trade for a headcount, latest per person for a named worker --
while a different contractor or trade still adds on top. The rule is one SQL
predicate (repositories/workforce.py's COUNTED_LINE_SQL) shared by every
reader that totals labour, so this checks each of them gives the same answer
for the same day: the DPR, the Today page, the labour dashboard, the
WhatsApp "how many workers?" answer and the day's counted lines.

Run with a live database:
    pytest backend/tests/integration/test_labour_snapshot_live.py -m integration
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository
from mesiri.infrastructure.postgres.repositories.workforce import (
    PostgresWorkforceReadRepository,
)

pytestmark = pytest.mark.integration

DAY = datetime.date(2026, 8, 3)
NEXT_DAY = datetime.date(2026, 8, 4)


def _at(hour: int, minute: int = 0) -> datetime.datetime:
    return datetime.datetime(2026, 8, 3, hour, minute, tzinfo=datetime.UTC)


@pytest.fixture
async def engine():
    settings = Settings()
    eng = create_async_engine(settings.postgres.dsn())
    yield eng
    await eng.dispose()


@pytest.fixture
async def db():
    database = PostgresDatabase(Settings().postgres)
    await database.connect()
    yield database
    await database.disconnect()


@pytest.fixture
async def scenario(engine: AsyncEngine):
    """One site's day, sent in pieces:

    - 08:00  Ravi 10 masons @800, Kumar 5 helpers @600, Raju (named mason) @900
    - 12:00  Ravi 12 masons @800 (replaces 10), "raju " again (one person)
    - 14:00  Ravi 30 masons -- withdrawn, so it replaces nothing
    - 15:00  Kumar 50 helpers -- superseded by the 15:05 report, replaces nothing
    - 15:05  Kumar 2 painters (corrects 15:00; a new trade, adds on)

    Counted: Ravi masons 12 + Kumar helpers 5 + Raju 1 + Kumar painters 2 = 20.
    The other site's 4 masons and the next day's 3 are untouched.
    """
    org, user, project = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    site, other_site = uuid.uuid4(), uuid.uuid4()
    morning, noon, voided, superseded, correction = (uuid.uuid4() for _ in range(5))
    other, tomorrow = uuid.uuid4(), uuid.uuid4()
    report_ids = [morning, noon, voided, superseded, correction, other, tomorrow]

    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, deployment_type, db_route, status, "
                "created_at) VALUES (:id, :name, 'local', 'default', 'active', now())"
            ),
            {"id": org, "name": f"labour-snapshot-{org}"},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO users (id, organization_id, email, hashed_password, full_name, "
                "role, status, created_at) "
                "VALUES (:id, :org, :email, 'x', 'Test', 'admin', 'active', now())"
            ),
            {"id": user, "org": org, "email": f"{user}@example.test"},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO projects (id, organization_id, name, status, created_at) "
                "VALUES (:id, :org, 'Snapshot Project', 'active', now())"
            ),
            {"id": project, "org": org},
        )
        for site_id, name in ((site, "Tower A"), (other_site, "Tower B")):
            await conn.execute(
                sa.text(
                    "INSERT INTO sites (id, project_id, organization_id, name, status, "
                    "created_at) VALUES (:id, :project, :org, :name, 'active', now())"
                ),
                {"id": site_id, "project": project, "org": org, "name": name},
            )

        async def _report(report_id, created_at, *, on=site, day=DAY, corrects=None,
                          voided_at=None):
            await conn.execute(
                sa.text(
                    "INSERT INTO labour_attendance_reports "
                    "(id, organization_id, project_id, site_id, occurred_date, "
                    " recorded_via, corrects_report_id, created_at, created_by, "
                    " voided_at, voided_by) "
                    "VALUES (:id, :org, :project, :site, :day, 'whatsapp_text', "
                    "        :corrects, :created_at, :user, :voided_at, :voided_by)"
                ),
                {
                    "id": report_id, "org": org, "project": project, "site": on,
                    "day": day, "corrects": corrects, "created_at": created_at,
                    "user": user, "voided_at": voided_at,
                    "voided_by": user if voided_at else None,
                },
            )

        async def _line(report_id, *, name=None, trade=None, headcount=1, wage=None,
                        contractor=None):
            await conn.execute(
                sa.text(
                    "INSERT INTO labour_attendance_lines "
                    "(id, report_id, worker_name, trade, headcount, daily_wage, "
                    " contractor, created_at) "
                    "VALUES (:id, :report, :name, :trade, :headcount, :wage, "
                    "        :contractor, now())"
                ),
                {
                    "id": uuid.uuid4(), "report": report_id, "name": name,
                    "trade": trade, "headcount": headcount, "wage": wage,
                    "contractor": contractor,
                },
            )

        await _report(morning, _at(8))
        await _line(morning, contractor="Ravi", trade="mason", headcount=10,
                    wage=Decimal("800"))
        await _line(morning, contractor="Kumar", trade="helper", headcount=5,
                    wage=Decimal("600"))
        await _line(morning, name="Raju", trade="mason", wage=Decimal("900"))

        await _report(noon, _at(12))
        await _line(noon, contractor=" ravi", trade="Mason ", headcount=12,
                    wage=Decimal("800"))
        await _line(noon, name="raju ", trade="mason", wage=Decimal("900"))

        await _report(voided, _at(14), voided_at=_at(14, 30))
        await _line(voided, contractor="Ravi", trade="mason", headcount=30)

        await _report(superseded, _at(15))
        await _line(superseded, contractor="Kumar", trade="helper", headcount=50)
        await _report(correction, _at(15, 5), corrects=superseded)
        await _line(correction, contractor="Kumar", trade="painter", headcount=2)

        await _report(other, _at(16), on=other_site)
        await _line(other, contractor="Ravi", trade="mason", headcount=4)
        await _report(tomorrow, _at(9) + datetime.timedelta(days=1), day=NEXT_DAY)
        await _line(tomorrow, contractor="Ravi", trade="mason", headcount=3)

    yield {"org": org, "project": project, "site": site, "other_site": other_site}

    async with engine.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM labour_attendance_lines WHERE report_id = ANY(:ids)"),
            {"ids": report_ids},
        )
        await conn.execute(
            sa.text("UPDATE labour_attendance_reports SET corrects_report_id = NULL "
                    "WHERE id = ANY(:ids)"),
            {"ids": report_ids},
        )
        await conn.execute(
            sa.text("DELETE FROM labour_attendance_reports WHERE id = ANY(:ids)"),
            {"ids": report_ids},
        )
        await conn.execute(sa.text("DELETE FROM sites WHERE project_id = :p"), {"p": project})
        await conn.execute(sa.text("DELETE FROM projects WHERE id = :id"), {"id": project})
        await conn.execute(sa.text("DELETE FROM users WHERE id = :id"), {"id": user})
        await conn.execute(sa.text("DELETE FROM organizations WHERE id = :id"), {"id": org})


async def test_dpr_counts_the_latest_figure_per_contractor_and_trade(engine, scenario):
    async with engine.connect() as conn:
        payload = await PostgresDprRepository(conn).assemble_site_report_payload(
            organization_id=scenario["org"],
            project_id=scenario["project"],
            site_id=scenario["site"],
            report_date=DAY,
        )
    labour = payload["labour"]
    assert labour["headcount"] == 20
    # The per-trade list keeps each spelling as sent; fold them to compare.
    trades: dict[str, int] = {}
    for t in labour["trades"]:
        key = t["trade"].strip().lower()
        trades[key] = trades.get(key, 0) + t["headcount"]
    # 12 Ravi masons + Raju; Kumar's 5 helpers stand; Kumar's painters add on.
    assert trades == {"mason": 13, "helper": 5, "painter": 2}
    # 12 x 800 + 5 x 600 + 900 (Raju once); the painters had no wage.
    assert Decimal(labour["total_cost"]) == Decimal("13500")


async def test_today_page_agrees_with_the_dpr(engine, scenario):
    async with engine.connect() as conn:
        days = await PostgresDprRepository(conn).list_site_days(
            organization_id=scenario["org"], project_ids=None, report_date=DAY
        )
    workers = {row["site_id"]: int(row["workers"]) for row in days}
    assert workers[scenario["site"]] == 20
    assert workers[scenario["other_site"]] == 4


async def test_labour_dashboard_agrees_with_the_dpr(engine, scenario):
    async with engine.connect() as conn:
        repo = PostgresWorkforceReadRepository(conn)
        by_date = await repo.aggregate_attendance(
            organization_id=scenario["org"], group_by="date", site_id=scenario["site"]
        )
        by_contractor = await repo.aggregate_attendance(
            organization_id=scenario["org"], group_by="contractor",
            site_id=scenario["site"], date_from=DAY, date_to=DAY,
        )
        full_history = await repo.aggregate_attendance(
            organization_id=scenario["org"], group_by="date", site_id=scenario["site"],
            date_from=DAY, date_to=DAY, include_superseded=True,
        )
    man_days = {str(r["key"])[:10]: int(r["man_days"]) for r in by_date}
    assert man_days == {"2026-08-03": 20, "2026-08-04": 3}
    contractors = {r["key"]: int(r["man_days"]) for r in by_contractor}
    assert contractors == {"ravi": 12, "kumar": 7, "": 1}
    # The full history still shows every line ever sent, for audit.
    assert int(full_history[0]["man_days"]) == 10 + 5 + 1 + 12 + 1 + 30 + 50 + 2


async def test_a_named_worker_sent_twice_is_one_day(engine, scenario):
    async with engine.connect() as conn:
        rows = await PostgresWorkforceReadRepository(conn).worker_statistics(
            organization_id=scenario["org"], site_id=scenario["site"]
        )
    raju = next(r for r in rows if r["key"] == "raju")
    assert Decimal(str(raju["man_days"])) == 1
    assert Decimal(str(raju["total_earnings"])) == Decimal("900")


async def test_whatsapp_answer_agrees_with_the_dpr(db, scenario):
    from runtime.labour_query_service import LabourQueryService

    summary = await LabourQueryService(db).summarize_attendance(
        organization_id=str(scenario["org"]),
        project_id=str(scenario["project"]),
        site_id=str(scenario["site"]),
        start_date=DAY,
        end_date=DAY,
    )
    assert summary["headcount"] == 20


async def test_counted_lines_are_what_the_day_counts_now(db, scenario):
    from runtime.workforce_query import PostgresWorkforceQueryService

    existing = await PostgresWorkforceQueryService(db).find_existing_report_for_day(
        organization_id=str(scenario["org"]),
        project_id=str(scenario["project"]),
        site_id=str(scenario["site"]),
        occurred_date=DAY.isoformat(),
    )
    assert existing is not None
    counted = sorted(
        (
            (line["contractor"] or "").strip().lower(),
            (line["trade"] or "").strip().lower(),
            (line["worker_name"] or "").strip().lower(),
            line["headcount"],
        )
        for line in existing["counted_lines"]
    )
    assert counted == [
        ("", "mason", "raju", 1),
        ("kumar", "helper", "", 5),
        ("kumar", "painter", "", 2),
        ("ravi", "mason", "", 12),
    ]
