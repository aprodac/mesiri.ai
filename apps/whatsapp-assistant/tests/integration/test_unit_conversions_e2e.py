"""WA-41 against a real database: a conversion is set once, company-wide, only
by an admin or project manager, and found again for the next report."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.database import PostgresDatabase
from runtime.material_catalog_query import MaterialCatalogQueryService

pytestmark = pytest.mark.integration


@pytest.fixture
async def world():
    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    async with db.transaction() as conn:
        created = await create_company(
            conn,
            NewCompany(
                name=f"Conversions {uuid.uuid4().hex[:6]}",
                owner_name="Owner",
                owner_phone=f"9194{uuid.uuid4().int % 10**8:08d}",
                project_name="Green Villa",
                site_names=("Kakkanad",),
            ),
            now=dt.datetime(2026, 10, 21, 6, tzinfo=dt.UTC),
        )
    yield db, created
    async with db.transaction() as conn:
        await conn.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": created.organization_id})
    await db.disconnect()


async def test_set_once_by_a_project_manager_then_found_for_the_next_report(world):
    db, created = world
    catalog = MaterialCatalogQueryService(db)
    org = str(created.organization_id)

    refused = await catalog.set_conversion(
        organization_id=org, role="SITE_ENGINEER", user_id=str(created.owner_user_id),
        material_name="sand", unit_text="bags", count=28,
    )
    assert refused.startswith("Only your admin or a project manager")

    said = await catalog.set_conversion(
        organization_id=org, role="PROJECT_MANAGER", user_id=str(created.owner_user_id),
        material_name="sand", unit_text="bags", count=28,
    )
    # The starter catalog's Sand, in whatever unit it is stocked in.
    [sand] = await catalog.find_materials(organization_id=org, name="Sand")
    bags = await catalog.resolve_unit("bags")
    cum = await catalog.get_unit(str(sand["default_unit_id"]))
    assert said == f"Saved for the company: 28 bags of Sand = 1 {cum['display_name']}."
    assert await catalog.find_conversion(
        organization_id=org, material=sand, from_unit=bags, stock_unit=cum
    ) == Decimal("28")

    # A second answer replaces the first (the latest answer wins).
    await catalog.set_conversion(
        organization_id=org, role="ADMIN", user_id=None, material_name="sand", unit_text="bags", count=30
    )
    assert await catalog.find_conversion(
        organization_id=org, material=sand, from_unit=bags, stock_unit=cum
    ) == Decimal("30")
