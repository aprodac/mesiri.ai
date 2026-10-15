"""SS-07: the getting-started checklist (GET /company/setup-progress) against a
real Postgres (integration). Each test runs in a transaction that is rolled
back. The update / DPR / team signals are SA-02's and are covered in
test_companies_overview_postgres.py; these cover what SS-07 added."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.domains.organizations import settings as org_settings
from mesiri.domains.organizations import setup_questions
from mesiri.domains.organizations.setup_router import get_setup_progress, keep_report_time
from mesiri.infrastructure.postgres.repositories.organization_settings import (
    PostgresOrganizationSettingsRepository,
)

pytestmark = pytest.mark.integration

_NOW = dt.datetime.now(dt.UTC)


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


async def _signup(conn, phone: str):
    created = await create_company(
        conn,
        NewCompany(
            name="Checklist Builders",
            owner_name="Owner",
            owner_phone=phone,
            project_name="Green Villa",
            start_as="trial",
            signup_source="web",
        ),
        now=_NOW,
    )
    admin = {
        "sub": str(created.owner_user_id),
        "org": str(created.organization_id),
        "role": "ADMIN",
    }
    return created, admin


async def test_a_new_signup_has_only_its_site(conn) -> None:
    created, admin = await _signup(conn, "+91 98765 20001")
    progress = await get_setup_progress(admin=admin, conn=conn)

    assert progress.has_site is True
    assert progress.has_team is False
    assert progress.has_logo is False
    assert progress.report_time_set is False
    assert progress.first_update_at is None
    assert progress.first_dpr_sent_at is None
    assert progress.first_project.id == created.project_id
    assert progress.first_project.name == "Green Villa"
    assert progress.first_project.send_time == "21:00"
    assert progress.effective_status == "trial"
    assert progress.trial_days_left == 7


async def test_logo_ticks_when_branding_holds_one(conn) -> None:
    created, admin = await _signup(conn, "+91 98765 20002")
    await conn.execute(
        text(
            "INSERT INTO organization_settings (id, organization_id, key, value, created_at, updated_at) "
            "VALUES (gen_random_uuid(), :org, 'branding', "
            'CAST(\'{"logo_object_key": "branding/x/logo.png"}\' AS jsonb), now(), now())'
        ),
        {"org": created.organization_id},
    )
    assert (await get_setup_progress(admin=admin, conn=conn)).has_logo is True


async def test_report_time_ticks_when_changed(conn) -> None:
    created, admin = await _signup(conn, "+91 98765 20003")
    await conn.execute(
        text("UPDATE projects SET dpr_send_deadline = '19:30' WHERE id = :id"),
        {"id": created.project_id},
    )
    progress = await get_setup_progress(admin=admin, conn=conn)
    assert progress.report_time_set is True
    assert progress.first_project.send_time == "19:30"


async def test_keeping_the_default_in_the_dashboard_answers_the_whatsapp_question(conn) -> None:
    created, admin = await _signup(conn, "+91 98765 20004")
    progress = await keep_report_time(admin=admin, conn=conn)
    assert progress.report_time_set is True

    # Recorded in SS-14's own record, so WhatsApp won't ask it again.
    stored = await PostgresOrganizationSettingsRepository(conn).get(
        created.organization_id, org_settings.SETUP_PROGRESS
    )
    assert stored["report_time"]["state"] == setup_questions.ANSWERED
    assert (
        setup_questions.next_question(stored, today=_NOW.date(), company_created_on=_NOW.date())
        != setup_questions.REPORT_TIME
    )

    # Another company's answer is not this one's.
    _, other_admin = await _signup(conn, "+91 98765 20005")
    assert (await get_setup_progress(admin=other_admin, conn=conn)).report_time_set is False


async def test_whatsapp_answer_ticks_it_but_a_skip_does_not(conn) -> None:
    created, admin = await _signup(conn, "+91 98765 20006")
    repo = PostgresOrganizationSettingsRepository(conn)

    async def answer(state):
        await repo.set(
            created.organization_id,
            org_settings.SETUP_PROGRESS,
            setup_questions.record({}, setup_questions.REPORT_TIME, state, today=_NOW.date()),
            updated_by=None,
        )

    await answer(setup_questions.SKIPPED)
    assert (await get_setup_progress(admin=admin, conn=conn)).report_time_set is False
    await answer(setup_questions.ANSWERED)
    assert (await get_setup_progress(admin=admin, conn=conn)).report_time_set is True
