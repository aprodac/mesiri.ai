"""WEB-04: what the site DPR page reads, against a real Postgres
(integration): the day with every confirmable item and its id, where an
item came from, versions, and who may see them. Each test runs in a
transaction that is rolled back.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from mesiri.application.dpr import fact_review
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.projects import auto_dpr
from mesiri.authorization.context import (
    AuthorizationContext,
    ProjectAccessScope,
    SiteAccessScope,
)
from mesiri.domains.dpr import router as dpr_router
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository
from mesiri.infrastructure.postgres.repositories.fact_reviews import (
    PostgresFactReviewRepository,
)

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


class _Storage:
    async def generate_presigned_url(self, key: str, *, expires_in_seconds: int) -> str:
        return f"https://media.example/{key}"


def _auth(created, *, sites: set[uuid.UUID] | None = None) -> AuthorizationContext:
    """Org-wide by default; `sites` = a member limited to those sites."""
    if sites is None:
        project_scope = ProjectAccessScope(mode="all_projects", project_ids=set())
        site_scope = SiteAccessScope(mode="all_sites", site_ids=set())
    else:
        project_scope = ProjectAccessScope(
            mode="custom_projects", project_ids={created.project_id}
        )
        site_scope = SiteAccessScope(mode="custom_sites", site_ids=sites)
    return AuthorizationContext(
        user_id=created.owner_user_id,
        organization_id=created.organization_id,
        role="SITE_ENGINEER",
        status="active",
        access_policy={},  # type: ignore[arg-type]
        project_scope=project_scope,
        site_scopes={created.project_id: site_scope},
    )


async def _day(conn, phone: str):
    """A site day with a draft work item (sent on WhatsApp), labour, cement
    received then used beyond stock, and an issue."""
    created = await create_company(
        conn,
        NewCompany(
            name=f"Page Builders {phone[-4:]}",
            owner_name="Suresh",
            owner_phone=phone,
            project_name="Green Towers",
            site_names=("Block A",),
            auto_dpr=True,
        ),
        now=EVENING_UTC,
    )
    org, project, site, by = (
        created.organization_id,
        created.project_id,
        created.site_id,
        created.owner_user_id,
    )
    ids = {k: uuid.uuid4() for k in ("activity", "labour", "receipt", "usage", "issue", "msg")}
    p = {"org": org, "project": project, "site": site, "day": DAY, "by": by, **ids}
    for sql in (
        "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date,"
        " work_type, narrative) VALUES (:activity, :org, :project, :site, :day,"
        " 'plastering', 'wall 2')",
        "INSERT INTO labour_attendance_reports (id, organization_id, project_id, site_id,"
        " occurred_date, recorded_via, created_by)"
        " VALUES (:labour, :org, :project, :site, :day, 'whatsapp_text', :by)",
        "INSERT INTO labour_attendance_lines (id, report_id, trade, headcount)"
        " VALUES (gen_random_uuid(), :labour, 'mason', 8)",
        "INSERT INTO site_issues (id, organization_id, project_id, site_id, issue_type,"
        " narrative, occurred_at) VALUES (:issue, :org, :project, :site, 'MATERIAL_SHORTAGE',"
        " 'sand late', CAST(:day AS date) + time '10:00')",
        "INSERT INTO inbound_messages (id, correlation_id, sender_wa_id, message_type,"
        " raw_payload, dedup_key, body_text, organization_id, received_at)"
        " VALUES (:msg, 'corr-web04', :phone, 'text', '{}', 'wamid-web04',"
        " 'plastering wall 2 done', :org, now())",
    ):
        await conn.execute(text(sql), {**p, "phone": "91" + phone})
    for key, kind, table, qty in (
        ("receipt", "RECEIPT", "material_receipts", 20),
        ("usage", "ISSUE", "material_usage", 30),
    ):
        await conn.execute(
            text(
                f"INSERT INTO {table} (id, organization_id, project_id, site_id, material_name,"
                " quantity, unit, occurred_date, created_by, material_id, unit_id)"
                " SELECT :fid, :org, :project, :site, m.name, :qty, 'bags', :day, :by, m.id,"
                " m.default_unit_id FROM materials_catalog m"
                " WHERE m.organization_id = :org AND m.name = 'Cement'"
            ),
            {**p, "fid": ids[key], "qty": qty},
        )
        await conn.execute(
            text(
                "INSERT INTO material_movements (id, organization_id, project_id, site_id,"
                " material_id, unit_id, movement_type, quantity, occurred_at, source_type,"
                " source_id, recorded_by_user_id)"
                " SELECT gen_random_uuid(), :org, :project, :site, m.id, m.default_unit_id,"
                " :kind, :qty, CAST(:day AS date) + time '09:00', :source, :fid, :by"
                " FROM materials_catalog m WHERE m.organization_id = :org AND m.name = 'Cement'"
            ),
            {**p, "fid": ids[key], "qty": qty, "kind": kind, "source": table.rstrip("s")},
        )
    reviews = PostgresFactReviewRepository(conn)
    extraction = await reviews.record_extraction(
        organization_id=org,
        extracted={"work_type": "plastering"},
        correlation_id="corr-web04",
        provider="anthropic",
        model="test-model",
        confidence="HIGH",
    )
    await reviews.mark_draft(
        organization_id=org,
        fact_type=fact_review.ACTIVITY,
        fact_id=ids["activity"],
        extraction_id=extraction,
        actor_user_id=by,
    )
    await reviews.mark_draft(
        organization_id=org, fact_type=fact_review.MATERIAL_USAGE, fact_id=ids["usage"]
    )
    await auto_dpr.generate_project_dpr(
        conn, organization_id=org, project_id=project, report_date=DAY
    )
    return created, ids


async def test_the_day_lists_every_item_with_its_id_and_state(conn) -> None:
    created, ids = await _day(conn, "9876500041")

    day = await dpr_router.get_site_day(
        created.site_id, report_date=DAY, auth_context=_auth(created), conn=conn
    )

    by_type = {(i["fact_type"], i["id"]): i for i in day["items"]}
    activity = by_type[(fact_review.ACTIVITY, str(ids["activity"]))]
    assert activity["review"] == "draft"
    assert activity["title"] == "plastering"
    labour = by_type[(fact_review.LABOUR_REPORT, str(ids["labour"]))]
    assert (labour["title"], labour["review"]) == ("8 workers", "confirmed")
    usage = by_type[(fact_review.MATERIAL_USAGE, str(ids["usage"]))]
    assert usage["review"] == "draft"
    assert usage["flags"] == ["beyond_stock"]  # 30 used, 20 received
    assert usage["detail"] == "30 bags used"
    assert by_type[(fact_review.MATERIAL_RECEIPT, str(ids["receipt"]))]["flags"] == []
    assert (fact_review.SITE_ISSUE, str(ids["issue"])) in by_type
    assert day["drafts"] == 2
    assert day["day"]["site_name"] == "Block A"
    assert [v["version_no"] for v in day["versions"]] == [1]
    # The stored payload is unchanged: no ids leak into versions or PDFs.
    assert "items" not in day["report"]
    # WA-77 (Alan, 25 Oct): the report is made of saved entries; the draft
    # work item is only listed for review, and the saved labour is in it.
    assert day["report"]["activities"] == []
    assert day["report"]["labour"]["headcount"] == 8
    assert day["report"]["drafts"]["total"] == 2


async def test_sources_show_the_message_sender_and_what_the_ai_read(conn) -> None:
    created, ids = await _day(conn, "9876500042")

    sources = await dpr_router.get_fact_sources(
        fact_review.ACTIVITY,
        ids["activity"],
        auth_context=_auth(created),
        conn=conn,
        object_storage=_Storage(),
    )

    [message] = sources["messages"]
    assert message["text"] == "plastering wall 2 done"
    assert message["sender_name"] == "Suresh"
    assert message["media_url"] is None
    [reading] = sources["readings"]
    assert (reading["model"], reading["confidence"]) == ("test-model", "HIGH")
    assert reading["extracted"] == {"work_type": "plastering"}
    assert [h["state"] for h in sources["history"]] == ["draft"]
    assert sources["photos"] == []


async def test_versions_and_a_pdf_of_an_older_version(conn) -> None:
    created, _ = await _day(conn, "9876500043")
    repo = PostgresDprRepository(conn)
    day = await dpr_router.get_site_day(
        created.site_id, report_date=DAY, auth_context=_auth(created), conn=conn
    )
    report_id = uuid.UUID(str(day["day"]["daily_report_id"]))
    assert await repo.approve_report(created.organization_id, created.owner_user_id, report_id, None)

    versions = (
        await dpr_router.list_daily_report_versions(
            report_id, auth_context=_auth(created), conn=conn
        )
    )["items"]
    assert [v["version_no"] for v in versions] == [2, 1]  # approving confirmed the drafts
    assert [v["is_current"] for v in versions] == [True, False]
    assert versions[0]["approved_by"] == "Suresh"

    old = await repo.get_report_for_pdf(
        organization_id=created.organization_id,
        report_id=report_id,
        version_id=uuid.UUID(versions[1]["id"]),
    )
    assert old["payload"]["drafts"] != {}
    assert old["version_id"] == uuid.UUID(versions[1]["id"])
    other = await repo.get_report_for_pdf(
        organization_id=created.organization_id, report_id=report_id, version_id=uuid.uuid4()
    )
    assert other is None


async def test_a_member_limited_to_other_sites_gets_not_found(conn) -> None:
    created, ids = await _day(conn, "9876500044")
    limited = _auth(created, sites={uuid.uuid4()})

    with pytest.raises(HTTPException) as day:
        await dpr_router.get_site_day(
            created.site_id, report_date=DAY, auth_context=limited, conn=conn
        )
    with pytest.raises(HTTPException) as sources:
        await dpr_router.get_fact_sources(
            fact_review.ACTIVITY,
            ids["activity"],
            auth_context=limited,
            conn=conn,
            object_storage=_Storage(),
        )
    assert day.value.status_code == sources.value.status_code == 404

    allowed = _auth(created, sites={created.site_id})
    ok = await dpr_router.get_site_day(
        created.site_id, report_date=DAY, auth_context=allowed, conn=conn
    )
    assert ok["drafts"] == 2
