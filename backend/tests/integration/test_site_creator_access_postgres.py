"""WA-46: someone with "selected sites only" access who creates a site over
WhatsApp gets that site, so they can report on it (integration, real
Postgres). Everyone else already reaches every site. Every test rolls back."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.projects.create_site_commands import CreateSiteCommand
from mesiri.infrastructure.postgres.repositories.site_execution import (
    PostgresCreateSiteExecutionRepository,
)

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


async def _setup(conn, site_access_mode: str | None):
    company = await create_company(
        conn,
        NewCompany(
            name="Sites", owner_name="Owner",
            owner_phone=f"+91 9{uuid.uuid4().int % 10**9:09d}",
            project_name="P", site_name="S",
        ),
    )
    pm_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO users (id, organization_id, full_name, role, whatsapp_number, hashed_password)"
            " VALUES (:id, :org, 'Priya', 'PROJECT_MANAGER', :phone, 'x')"
        ),
        {"id": pm_id, "org": company.organization_id, "phone": f"91{uuid.uuid4().int % 10**10:010d}"},
    )
    if site_access_mode is not None:
        await conn.execute(
            text(
                "INSERT INTO project_members (id, project_id, user_id, role, site_access_mode)"
                " VALUES (:id, :project, :user, 'PROJECT_MANAGER', :mode)"
            ),
            {"id": uuid.uuid4(), "project": company.project_id, "user": pm_id, "mode": site_access_mode},
        )
    return company, pm_id


async def _create_site(conn, company, user_id) -> uuid.UUID:
    result = await PostgresCreateSiteExecutionRepository().persist_success(
        conn,
        CreateSiteCommand(
            idempotency_key=f"test-{uuid.uuid4()}",
            organization_id=str(company.organization_id),
            project_id=str(company.project_id),
            created_by=str(user_id),
            created_by_role="PROJECT_MANAGER",
            name="Block C",
        ),
    )
    return uuid.UUID(result.material_row_id)


async def _members(conn, site_id) -> list[uuid.UUID]:
    rows = await conn.execute(text("SELECT user_id FROM site_members WHERE site_id = :s"), {"s": site_id})
    return [r[0] for r in rows]


async def test_a_selected_sites_creator_gets_the_new_site(conn) -> None:
    company, pm_id = await _setup(conn, "custom_sites")

    site_id = await _create_site(conn, company, pm_id)

    assert await _members(conn, site_id) == [pm_id]


async def test_a_creator_who_reaches_every_site_gets_no_extra_row(conn) -> None:
    company, pm_id = await _setup(conn, "all_sites")

    assert await _members(conn, await _create_site(conn, company, pm_id)) == []


async def test_an_admin_with_no_membership_gets_no_row(conn) -> None:
    company, _ = await _setup(conn, None)

    assert await _members(conn, await _create_site(conn, company, company.owner_user_id)) == []
