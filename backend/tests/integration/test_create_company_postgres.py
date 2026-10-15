"""SS-03: the one create-company step against a real Postgres (integration).

Every test runs in a transaction that is rolled back, so nothing is left in
the database.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import (
    CompanyCreationError,
    NewCompany,
    create_company,
)

pytestmark = pytest.mark.integration

_NOW = dt.datetime(2026, 10, 15, 6, 0, tzinfo=dt.UTC)


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


async def _one(conn, sql: str, **params):
    return (await conn.execute(text(sql), params)).mappings().one()


async def test_whatsapp_owner_with_first_site_on_trial(conn) -> None:
    created = await create_company(
        conn,
        NewCompany(
            name="Suresh Builders",
            owner_name="Suresh",
            owner_phone="+91 98765 00001",
            project_name="Green Villa",
            site_name="Kakkanad",
            auto_dpr=True,
            start_as="trial",
            signup_source="whatsapp",
        ),
        now=_NOW,
    )

    org = await _one(conn, "SELECT * FROM organizations WHERE id = :id", id=created.organization_id)
    assert org["status"] == "trial"
    assert org["signup_source"] == "whatsapp"
    assert org["timezone"] == "Asia/Kolkata"
    assert org["trial_started_at"] == _NOW
    assert org["trial_ends_at"] == _NOW + dt.timedelta(days=7)  # platform default

    owner = await _one(conn, "SELECT * FROM users WHERE id = :id", id=created.owner_user_id)
    assert owner["organization_id"] == created.organization_id
    assert owner["role"] == "ADMIN"
    assert owner["status"] == "active"
    assert owner["email"] is None
    assert owner["whatsapp_number"] == "919876500001"
    assert owner["hashed_password"]  # unusable, but the column is NOT NULL

    project = await _one(conn, "SELECT * FROM projects WHERE id = :id", id=created.project_id)
    assert project["name"] == "Green Villa"
    assert project["reporting_timezone"] == "Asia/Kolkata"
    assert project["auto_generate_dpr"] is True
    site = await _one(conn, "SELECT * FROM sites WHERE id = :id", id=created.site_id)
    assert site["name"] == "Kakkanad"
    assert site["project_id"] == created.project_id
    assert site["organization_id"] == created.organization_id


async def test_trial_length_follows_the_platform_setting(conn) -> None:
    await conn.execute(
        text(
            "INSERT INTO platform_settings (key, value) VALUES ('trial_policy', '{\"trial_days\": 14}') "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        )
    )
    created = await create_company(
        conn,
        NewCompany(
            name="Long Trial Co", owner_name="Asha", owner_phone="9876500002", start_as="trial"
        ),
        now=_NOW,
    )
    assert created.trial_ends_at == _NOW + dt.timedelta(days=14)


async def test_control_panel_request_unchanged(conn) -> None:
    """The six fields the control panel has always sent: active company,
    email + password owner, no project."""
    created = await create_company(
        conn,
        NewCompany(
            name="Acme Construction",
            owner_name="John Doe",
            owner_email="John@Acme.example",
            owner_password="Temp-pass-1",
            deployment_type="SaaS",
            db_route="shared-cluster-01",
        ),
        now=_NOW,
    )
    assert created.status == "active"
    assert created.trial_ends_at is None
    assert created.project_id is None and created.site_id is None

    import bcrypt

    owner = await _one(conn, "SELECT * FROM users WHERE id = :id", id=created.owner_user_id)
    assert owner["email"] == "john@acme.example"
    assert bcrypt.checkpw(b"Temp-pass-1", owner["hashed_password"].encode())


async def test_taken_number_is_refused_before_anything_is_written(conn) -> None:
    # An existing user whose number was typed with spaces and a plus.
    await create_company(
        conn, NewCompany(name="First Co", owner_name="A", owner_phone="9876500003"), now=_NOW
    )
    await conn.execute(
        text("UPDATE users SET whatsapp_number = '+91 98765 00003' WHERE whatsapp_number = :n"),
        {"n": "919876500003"},
    )
    before = (await conn.execute(text("SELECT count(*) FROM organizations"))).scalar_one()

    with pytest.raises(CompanyCreationError, match="already belongs") as exc:
        await create_company(
            conn,
            NewCompany(name="Second Co", owner_name="B", owner_phone="098765 00003"),
            now=_NOW,
        )
    assert exc.value.conflict is True
    after = (await conn.execute(text("SELECT count(*) FROM organizations"))).scalar_one()
    assert after == before


async def test_taken_email_is_refused_whatever_its_case(conn) -> None:
    await create_company(
        conn, NewCompany(name="First Co", owner_name="A", owner_email="owner@x.example"), now=_NOW
    )
    with pytest.raises(CompanyCreationError, match="already registered") as exc:
        await create_company(
            conn,
            NewCompany(name="Second Co", owner_name="B", owner_email="OWNER@x.example"),
            now=_NOW,
        )
    assert exc.value.conflict is True


# --- BE-24: starter materials -------------------------------------------------


async def test_new_company_gets_the_starter_materials(conn) -> None:
    from mesiri.domains.materials.defaults import STARTER_MATERIALS
    from mesiri.infrastructure.postgres.repositories.materials import (
        PostgresMaterialCatalogRepository,
    )

    created = await create_company(
        conn, NewCompany(name="Suresh Builders", owner_name="S", owner_phone="9876500010"), now=_NOW
    )
    assert created.materials_seeded == len(STARTER_MATERIALS)

    rows = (
        (
            await conn.execute(
                text(
                    "SELECT m.name, m.default_unit, u.code, m.created_by, m.is_active "
                    "FROM materials_catalog m JOIN units_of_measure u ON u.id = m.default_unit_id "
                    "WHERE m.organization_id = :org"
                ),
                {"org": created.organization_id},
            )
        )
        .mappings()
        .all()
    )
    by_name = {r["name"]: r for r in rows}
    assert set(by_name) == {m.name for m in STARTER_MATERIALS}
    for material in STARTER_MATERIALS:
        row = by_name[material.name]
        assert row["code"] == row["default_unit"] == material.unit_code
        assert row["created_by"] == created.owner_user_id
        assert row["is_active"] is True

    # What the WhatsApp material gate asks first: "cement" resolves exactly.
    repo = PostgresMaterialCatalogRepository(conn)
    hit = await repo.find_by_name_exact_active(created.organization_id, "cement")
    assert hit is not None and hit["name"] == "Cement"


async def test_seeding_again_adds_nothing_and_keeps_existing_names(conn) -> None:
    from mesiri.application.materials.starter_catalog import seed_starter_materials

    created = await create_company(
        conn, NewCompany(name="Again Co", owner_name="A", owner_phone="9876500011"), now=_NOW
    )
    # The company deleted one of the starter rows.
    await conn.execute(
        text("DELETE FROM materials_catalog WHERE organization_id = :org AND name = 'Steel'"),
        {"org": created.organization_id},
    )
    added = await seed_starter_materials(
        conn, created.organization_id, created_by=created.owner_user_id
    )
    assert added == 1  # only the deleted one comes back
    assert (
        await seed_starter_materials(
            conn, created.organization_id, created_by=created.owner_user_id
        )
        == 0
    )


async def test_materials_stay_per_company(conn) -> None:
    a = await create_company(
        conn, NewCompany(name="A Co", owner_name="A", owner_phone="9876500012"), now=_NOW
    )
    b = await create_company(
        conn, NewCompany(name="B Co", owner_name="B", owner_phone="9876500013"), now=_NOW
    )
    assert a.materials_seeded == b.materials_seeded > 0
