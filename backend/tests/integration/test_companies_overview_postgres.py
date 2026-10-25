"""SA-02: the companies list's status and setup progress against a real
Postgres (integration). Each test runs in a transaction that is rolled back."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.companies_overview import list_companies
from mesiri.application.organizations.create_company import NewCompany, create_company

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


async def _company(conn, name: str, phone: str, **overrides):
    fields = {
        "name": name,
        "owner_name": "Owner",
        "owner_phone": phone,
        "project_name": "Skyline Apartments",
        "start_as": "trial",
        "signup_source": "whatsapp",
    }
    fields.update(overrides)
    return await create_company(conn, NewCompany(**fields), now=_NOW)


def _find(companies, org_id):
    return next(c for c in companies if c.id == org_id)


async def test_new_trial_has_a_site_and_nothing_else(conn) -> None:
    created = await _company(conn, "Fresh Trial Builders", "+91 98765 10001")

    company = _find(await list_companies(conn, now=_NOW), created.organization_id)

    assert company.effective_status == "trial"
    assert company.trial_days_left == 7  # platform default
    assert company.signup_source == "whatsapp"
    assert company.setup.has_site is True
    assert company.setup.has_team is False
    assert company.setup.first_update_at is None
    assert company.setup.first_dpr_sent_at is None


async def test_team_update_and_sent_dpr_are_seen(conn) -> None:
    created = await _company(conn, "Busy Builders", "+91 98765 10002")
    org, project, site = created.organization_id, created.project_id, created.site_id
    reported_at = _NOW - dt.timedelta(hours=3)
    supervisor = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO users (id, organization_id, hashed_password, full_name, role, status,"
            " whatsapp_number) VALUES (:id, :org, 'x', 'Supervisor', 'SITE_ENGINEER', 'active',"
            " '919876510099')"
        ),
        {"id": supervisor, "org": org},
    )
    # SS-19: they count once they are on a project, so they can report.
    assert _find(await list_companies(conn, now=_NOW), org).setup.has_team is False
    await conn.execute(
        text(
            "INSERT INTO project_members (id, project_id, user_id, role, site_access_mode)"
            " VALUES (:id, :project, :user, 'SITE_ENGINEER', 'all_sites')"
        ),
        {"id": uuid.uuid4(), "project": project, "user": supervisor},
    )
    await conn.execute(
        text(
            "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date,"
            " created_at) VALUES (:id, :org, :project, :site, :day, :at)"
        ),
        {
            "id": uuid.uuid4(),
            "org": org,
            "project": project,
            "site": site,
            "day": reported_at.date(),
            "at": reported_at,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO timeline_entries (id, organization_id, event_type, summary, payload,"
            " occurred_at, source_aggregate_type, source_aggregate_id)"
            " VALUES (:id, :org, 'MaterialReceived', 'cement', '{}', :at, 'material', :id)"
        ),
        {"id": uuid.uuid4(), "org": org, "at": _NOW - dt.timedelta(hours=1)},
    )
    await conn.execute(
        text(
            "INSERT INTO daily_reports (id, organization_id, project_id, level, report_date,"
            " status, updated_at) VALUES (:id, :org, :project, 'PROJECT', :day, 'PUBLISHED', :at)"
        ),
        {"id": uuid.uuid4(), "org": org, "project": project, "day": _NOW.date(), "at": _NOW},
    )

    company = _find(await list_companies(conn, now=_NOW), org)

    assert company.setup.has_team is True
    assert company.setup.first_update_at == reported_at  # the earlier of the two
    assert company.setup.first_dpr_sent_at == _NOW


async def test_ended_trial_reads_expired_and_newest_comes_first(conn) -> None:
    older = await _company(conn, "Old Trial Builders", "+91 98765 10003")
    await conn.execute(
        text(
            "UPDATE organizations SET trial_ends_at = :ended, created_at = :created WHERE id = :id"
        ),
        {
            "ended": _NOW - dt.timedelta(days=1),
            "created": _NOW - dt.timedelta(days=9),
            "id": older.organization_id,
        },
    )
    newer = await _company(conn, "New Active Builders", "+91 98765 10004", start_as="active")

    companies = await list_companies(conn, now=_NOW)

    expired = _find(companies, older.organization_id)
    assert expired.status == "trial"
    assert expired.effective_status == "expired"
    assert expired.trial_days_left is None
    ids = [c.id for c in companies]
    assert ids.index(newer.organization_id) < ids.index(older.organization_id)


async def test_open_branding_requests_are_counted(conn) -> None:
    import json

    created = await _company(conn, "Logo Builders", "+91 98765 10005")
    requests = [
        {"id": "a", "status": "open", "files": []},
        {"id": "b", "status": "done", "files": []},
        {"id": "c", "status": "open", "files": []},
    ]
    await conn.execute(
        text(
            "INSERT INTO organization_settings (id, organization_id, key, value)"
            " VALUES (:id, :org, 'branding_requests', CAST(:v AS jsonb))"
        ),
        {"id": uuid.uuid4(), "org": created.organization_id, "v": json.dumps(requests)},
    )

    company = _find(await list_companies(conn, now=_NOW), created.organization_id)

    assert company.open_branding_requests == 2
