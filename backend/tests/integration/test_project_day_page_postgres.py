"""WEB-05: what the project DPR page reads, against a real Postgres
(integration): each site's day, the project DPR as it would go out now
(a preview that writes nothing) and as it was sent, its versions, and who
may see it. Each test runs in a transaction that is rolled back.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.projects import auto_dpr
from mesiri.authorization.context import (
    AuthorizationContext,
    ProjectAccessScope,
    SiteAccessScope,
)
from mesiri.domains.dpr import router as dpr_router
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

pytestmark = pytest.mark.integration

DAY = dt.date(2026, 10, 16)
EVENING_UTC = dt.datetime(2026, 10, 16, 13, 30, tzinfo=dt.UTC)


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


def _auth(created, *, project_ids: set[uuid.UUID] | None = None) -> AuthorizationContext:
    """Org-wide by default; `project_ids` = a member limited to those projects."""
    if project_ids is None:
        project_scope = ProjectAccessScope(mode="all_projects", project_ids=set())
    else:
        project_scope = ProjectAccessScope(mode="custom_projects", project_ids=project_ids)
    return AuthorizationContext(
        user_id=created.owner_user_id,
        organization_id=created.organization_id,
        role="ADMIN",
        status="active",
        access_policy={},  # type: ignore[arg-type]
        project_scope=project_scope,
        site_scopes={created.project_id: SiteAccessScope(mode="all_sites", site_ids=set())},
    )


async def _project(conn, phone: str):
    """Two sites: Block A logged work and 8 masons and was confirmed by the engineer;
    Block B logged 3 helpers but nobody confirmed it."""
    created = await create_company(
        conn,
        NewCompany(
            name=f"Roll-up Builders {phone[-4:]}",
            owner_name="Suresh",
            owner_phone=phone,
            project_name="Green Towers",
            site_names=("Block A", "Block B"),
            auto_dpr=True,
        ),
        now=EVENING_UTC,
    )
    org, project, by = created.organization_id, created.project_id, created.owner_user_id
    sites = {
        row["name"]: row["id"]
        for row in (
            await conn.execute(
                text("SELECT id, name FROM sites WHERE project_id = :p"), {"p": project}
            )
        ).mappings()
    }
    for name, trade, count in (("Block A", "mason", 8), ("Block B", "helper", 3)):
        report = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO labour_attendance_reports (id, organization_id, project_id,"
                " site_id, occurred_date, recorded_via, created_by)"
                " VALUES (:id, :org, :project, :site, :day, 'whatsapp_text', :by)"
            ),
            {"id": report, "org": org, "project": project, "site": sites[name], "day": DAY,
             "by": by},
        )
        await conn.execute(
            text(
                "INSERT INTO labour_attendance_lines (id, report_id, trade, headcount)"
                " VALUES (gen_random_uuid(), :report, :trade, :count)"
            ),
            {"report": report, "trade": trade, "count": count},
        )
    await conn.execute(
        text(
            "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date,"
            " work_type, narrative) VALUES (gen_random_uuid(), :org, :project, :site, :day,"
            " 'plastering', 'wall 2')"
        ),
        {"org": org, "project": project, "site": sites["Block A"], "day": DAY},
    )
    await auto_dpr.generate_project_dpr(
        conn, organization_id=org, project_id=project, report_date=DAY
    )
    repo = PostgresDprRepository(conn)
    block_a = await repo.find_site_report(
        organization_id=org, project_id=project, site_id=sites["Block A"], report_date=DAY
    )
    assert await repo.approve_report(org, by, block_a["id"], None)
    return created, sites


async def _report_rows(conn, project_id) -> tuple[int, int]:
    """Reports and versions on record for the project: a preview adds neither."""
    row = (
        await conn.execute(
            text(
                "SELECT count(DISTINCT dr.id), count(v.id) FROM daily_reports dr"
                " LEFT JOIN daily_report_versions v ON v.daily_report_id = dr.id"
                " WHERE dr.project_id = :p"
            ),
            {"p": project_id},
        )
    ).one()
    return int(row[0]), int(row[1])


async def test_before_sending_the_page_previews_the_rollup_and_writes_nothing(conn) -> None:
    created, _ = await _project(conn, "9876500051")
    reports_before = await _report_rows(conn, created.project_id)

    day = await dpr_router.get_project_day(
        created.project_id, report_date=DAY, auth_context=_auth(created), conn=conn
    )

    assert day["report_source"] == "preview"
    assert day["project"]["project_name"] == "Green Towers"
    assert day["project"]["sent"] is False
    by_site = {s["site_name"]: s for s in day["report"]["sites"]}
    # Only the confirmed site is in the DPR; the other is "not reported".
    assert by_site["Block A"]["reported"] is True
    assert by_site["Block A"]["headcount"] == 8
    assert by_site["Block B"]["reported"] is False
    assert day["report"]["labour"]["headcount"] == 8
    assert (day["report"]["reported_site_count"], day["report"]["total_site_count"]) == (1, 2)
    # Every site's live day is listed, confirmed or not.
    live = {s["site_name"]: s for s in day["sites"]}
    assert live["Block A"]["status"] == "approved"
    assert live["Block B"]["workers"] == 3
    # The cutoff's draft roll-up is not offered: its PDF never goes out.
    assert day["versions"] == []
    assert await _report_rows(conn, created.project_id) == reports_before


async def test_once_sent_the_page_shows_the_dpr_as_it_went_out(conn) -> None:
    created, _ = await _project(conn, "9876500052")
    sent = await auto_dpr.finalize_project_dpr(
        conn,
        organization_id=created.organization_id,
        project_id=created.project_id,
        report_date=DAY,
    )
    await auto_dpr.mark_project_dpr_sent(
        conn,
        project_id=created.project_id,
        report_date=DAY,
        daily_report_id=sent["daily_report_id"],
    )

    day = await dpr_router.get_project_day(
        created.project_id, report_date=DAY, auth_context=_auth(created), conn=conn
    )

    assert day["report_source"] == "sent"
    assert day["project"]["sent"] is True
    assert day["project"]["project_report_status"] == "published"
    assert day["report"]["level"] == "PROJECT"
    assert day["report"]["labour"]["headcount"] == 8
    # Only what went out: the cutoff's unapproved draft (version 1) is left off.
    assert [v["version_no"] for v in day["versions"]] == [2]
    assert day["versions"][0]["is_current"] is True


async def test_a_member_without_the_project_gets_not_found(conn) -> None:
    created, _ = await _project(conn, "9876500053")

    with pytest.raises(HTTPException) as denied:
        await dpr_router.get_project_day(
            created.project_id,
            report_date=DAY,
            auth_context=_auth(created, project_ids={uuid.uuid4()}),
            conn=conn,
        )
    assert denied.value.status_code == 404

    with pytest.raises(HTTPException) as missing:
        await dpr_router.get_project_day(
            uuid.uuid4(), report_date=DAY, auth_context=_auth(created), conn=conn
        )
    assert missing.value.status_code == 404
