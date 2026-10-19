"""BE-18 end to end against a real Postgres: the engineers confirm both
sites, the project DPR is sent, its summary is written from the frozen
roll-up (AI faked), stored on the version, printed in the PDF and returned
by the dashboard's APIs. Runs in one transaction that is rolled back."""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest
from sqlalchemy import text

import runtime.project_auto_dpr as sender
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.projects import auto_dpr
from mesiri.authorization.context import (
    AuthorizationContext,
    ProjectAccessScope,
    SiteAccessScope,
)
from mesiri.domains.dpr import router as dpr_router
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository
from runtime.dpr_summary import DprSummaryWriter

pytestmark = pytest.mark.integration

DAY = dt.date(2026, 10, 16)
EVENING_UTC = dt.datetime(2026, 10, 16, 13, 30, tzinfo=dt.UTC)
SUMMARY = "Plastering on wall 2 was recorded at Block A. 8 workers were at Block A and 3 at Block B."


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


class _AI:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.facts: list[dict] = []

    async def generate_json(self, system_prompt, user_prompt, *, correlation_id=None):
        self.facts.append(json.loads(user_prompt)["FACTS"])
        return json.dumps({"summary": self.reply})


class _Renderer:
    def __init__(self) -> None:
        self.html: list[str] = []

    async def render_pdf(self, html: str) -> bytes:
        self.html.append(html)
        return b"%PDF-fake"


class _Storage:
    async def put_object(self, key, data, *, content_type):
        pass


def _auth(created) -> AuthorizationContext:
    return AuthorizationContext(
        user_id=created.owner_user_id,
        organization_id=created.organization_id,
        role="ADMIN",
        status="active",
        access_policy={},  # type: ignore[arg-type]
        project_scope=ProjectAccessScope(mode="all_projects", project_ids=set()),
        site_scopes={created.project_id: SiteAccessScope(mode="all_sites", site_ids=set())},
    )


async def _confirmed_project(conn):
    created = await create_company(
        conn,
        NewCompany(
            name=f"Summary Builders {uuid.uuid4().hex[:6]}",
            owner_name="Suresh",
            owner_phone=f"9198{uuid.uuid4().int % 10**8:08d}",
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
    await auto_dpr.generate_project_dpr(conn, organization_id=org, project_id=project, report_date=DAY)
    repo = PostgresDprRepository(conn)
    for name in ("Block A", "Block B"):
        day = await repo.find_site_report(
            organization_id=org, project_id=project, site_id=sites[name], report_date=DAY
        )
        assert await repo.approve_report(org, by, day["id"], None)
    return created, sites


async def _send(conn, ai, monkeypatch) -> _Renderer:
    async def nobody(*_args, **_kwargs):
        return []

    monkeypatch.setattr(sender, "_dpr_audience", nobody)
    renderer = _Renderer()
    sent = await sender.send_due_project_dprs(
        conn,
        db=None,
        renderer=renderer,
        object_storage=_Storage(),
        now_utc=EVENING_UTC,
        summary_writer=DprSummaryWriter(ai),
    )
    assert sent == 1
    return renderer


async def test_confirm_send_stores_the_summary_and_the_apis_return_it(conn, monkeypatch) -> None:
    created, sites = await _confirmed_project(conn)
    ai = _AI(SUMMARY)

    renderer = await _send(conn, ai, monkeypatch)

    # Written from the frozen roll-up, which names both sites.
    assert ai.facts[0]["report"] == "project"
    assert ai.facts[0]["sites_reported"] == 2
    # Printed in the PDF the owner gets.
    assert any(SUMMARY in html for html in renderer.html)

    stored = (
        await conn.execute(
            text(
                "SELECT v.narrative_summary FROM daily_reports dr"
                " JOIN daily_report_versions v ON v.id = dr.current_version_id"
                " WHERE dr.project_id = :p AND dr.level = 'PROJECT'"
            ),
            {"p": created.project_id},
        )
    ).scalar_one()
    assert stored == SUMMARY

    page = await dpr_router.get_project_day(
        created.project_id, report_date=DAY, auth_context=_auth(created), conn=conn
    )
    assert page["report_source"] == "sent"
    assert page["summary"] == SUMMARY

    history = await dpr_router.list_daily_reports(
        project_id=created.project_id, site_id=None, status=None, level="project",
        category=None, date_from=DAY, date_to=DAY, limit=50, offset=0,
        auth_context=_auth(created), conn=conn,
    )
    assert [r["summary"] for r in history["items"]] == [SUMMARY]

    # The site pages have no summary of their own yet (rendered by the cron).
    site_page = await dpr_router.get_site_day(
        sites["Block A"], report_date=DAY, auth_context=_auth(created), conn=conn
    )
    assert site_page["summary"] is None


async def test_a_summary_with_an_invented_number_is_not_stored(conn, monkeypatch) -> None:
    created, _ = await _confirmed_project(conn)

    renderer = await _send(conn, _AI("40 workers were on site."), monkeypatch)

    assert not any("40 workers" in html for html in renderer.html)
    page = await dpr_router.get_project_day(
        created.project_id, report_date=DAY, auth_context=_auth(created), conn=conn
    )
    assert page["report_source"] == "sent"  # the DPR still went out
    assert page["summary"] is None


async def test_a_stored_summary_is_kept_and_a_reopened_day_shows_none(conn) -> None:
    created, sites = await _confirmed_project(conn)
    repo = PostgresDprRepository(conn)
    day = await repo.find_site_report(
        organization_id=created.organization_id, project_id=created.project_id,
        site_id=sites["Block A"], report_date=DAY,
    )
    report = await repo.get_report_for_pdf(
        organization_id=created.organization_id, report_id=day["id"]
    )

    assert await repo.set_narrative_summary(version_id=report["version_id"], summary="First.") == "First."
    # Never regenerated: a second write keeps the first.
    assert await repo.set_narrative_summary(version_id=report["version_id"], summary="Second.") == "First."
    page = await dpr_router.get_site_day(
        sites["Block A"], report_date=DAY, auth_context=_auth(created), conn=conn
    )
    assert page["summary"] == "First."

    await conn.execute(
        text("UPDATE daily_reports SET status = 'DRAFT' WHERE id = :id"), {"id": day["id"]}
    )
    assert await repo.get_current_summary(
        organization_id=created.organization_id, report_id=day["id"]
    ) is None
