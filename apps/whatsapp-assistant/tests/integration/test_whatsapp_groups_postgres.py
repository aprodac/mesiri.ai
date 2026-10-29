"""WA-87: a site's WhatsApp group rows against a real database (migration 0492).

Run with a live database:
    pytest apps/whatsapp-assistant/tests/integration/test_whatsapp_groups_postgres.py -m integration
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.database import PostgresDatabase
from runtime.whatsapp_group_query import WhatsAppGroupQueryService

pytestmark = pytest.mark.integration


@pytest.fixture
async def world():
    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    phone = f"9196{uuid.uuid4().int % 10**8:08d}"
    async with db.transaction() as conn:
        created = await create_company(
            conn,
            NewCompany(
                name=f"Groups E2E {uuid.uuid4().hex[:6]}",
                owner_name="Owner",
                owner_phone=phone,
                project_name="Green Villa",
                site_names=("Block A", "Block B"),
            ),
            now=dt.datetime(2026, 10, 28, 6, tzinfo=dt.UTC),
        )
    try:
        yield db, created, phone
    finally:
        async with db.transaction() as conn:
            await conn.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": created.organization_id})
        await db.disconnect()


async def test_one_live_group_per_site_and_lookups(world) -> None:
    db, created, _phone = world
    groups = WhatsAppGroupQueryService(db)
    org, project = str(created.organization_id), str(created.project_id)
    site_a, site_b = (str(s.site_id) for s in created.sites)

    first = await groups.start(
        organization_id=org, project_id=project, site_id=site_a,
        subject="Block A · Mesiri", created_by_user_id=str(created.owner_user_id),
    )
    assert first is not None and first["status"] == "creating" and first["site_name"] == "Block A"
    # A second tap for the same site makes nothing.
    assert await groups.start(
        organization_id=org, project_id=project, site_id=site_a, subject="again", created_by_user_id=None
    ) is None
    assert await groups.start(
        organization_id=org, project_id=project, site_id=site_b, subject="Block B · Mesiri", created_by_user_id=None
    ) is not None
    assert (await groups.creating_by_subject("Block B · Mesiri"))["site_id"] == site_b

    await groups.update(first["id"], create_request_id="req-1")
    assert (await groups.by_request_id("req-1"))["id"] == first["id"]
    await groups.update(first["id"], wa_group_id="120363000000000001", invite_link="https://chat.whatsapp.com/Ab", status="active")

    found = await groups.by_wa_group_id("120363000000000001")
    assert found["organization_id"] == org and found["site_id"] == site_a and found["invite_link"].endswith("/Ab")
    assert [g["site_id"] for g in await groups.active_for_project(organization_id=org, project_id=project)] == [site_a]
    assert (await groups.live_for_site(organization_id=org, site_id=site_a))["status"] == "active"

    # A closed group frees the site for a new one.
    await groups.update(first["id"], status="closed")
    assert await groups.live_for_site(organization_id=org, site_id=site_a) is None
    assert await groups.start(
        organization_id=org, project_id=project, site_id=site_a, subject="new", created_by_user_id=None
    ) is not None


async def test_site_team_and_join_requests(world) -> None:
    db, created, phone = world
    groups = WhatsAppGroupQueryService(db)
    org = str(created.organization_id)
    site_a = str(created.sites[0].site_id)

    team = await groups.site_team(organization_id=org, site_id=site_a)
    # The owner (ADMIN) reaches every site.
    assert [m["user_id"] for m in team] == [str(created.owner_user_id)]
    assert team[0]["wa_id"].endswith(phone[-8:])

    group = await groups.start(
        organization_id=org, project_id=str(created.project_id), site_id=site_a,
        subject="Block A · Mesiri", created_by_user_id=None,
    )
    stored = await groups.record_join_request(group=group, join_request_id="jr-1", wa_id="919800000001", status="pending")
    assert stored is not None
    # The same webhook twice records it once.
    assert await groups.record_join_request(group=group, join_request_id="jr-1", wa_id="919800000001", status="pending") is None

    row = await groups.join_request(stored["id"])
    assert row["group_id"] == group["id"] and row["status"] == "pending"
    assert await groups.decide_join_request(stored["id"], status="approved", user_id=str(created.owner_user_id))
    # Decided once: a second tap changes nothing.
    assert not await groups.decide_join_request(stored["id"], status="rejected", user_id=None)
    assert (await groups.join_request(stored["id"]))["status"] == "approved"
    assert await groups.join_request("not-a-uuid") is None


async def test_super_admin_and_companies(world) -> None:
    db, created, _phone = world
    groups = WhatsAppGroupQueryService(db)
    number = f"9195{uuid.uuid4().int % 10**8:08d}"
    async with db.transaction() as conn:
        user_id = (
            await conn.execute(
                text(
                    "INSERT INTO users (id, full_name, role, whatsapp_number, status, hashed_password, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), 'Ops', 'ADMIN', :n, 'active', 'x', now(), now()) RETURNING id"
                ),
                {"n": f"+{number}"},
            )
        ).scalar_one()
    try:
        assert (await groups.is_super_admin(number))["user_id"] == str(user_id)
        assert await groups.is_super_admin(str(created.organization_id)[:8]) is None
        names = {c["name"] for c in await groups.companies()}
        assert any(n.startswith("Groups E2E") for n in names)
    finally:
        async with db.transaction() as conn:
            await conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


async def test_another_company_never_sees_the_rows(world) -> None:
    """Row-level security (0484's rule) on both new tables, as a login that
    is neither superuser nor owner -- the same probe as backend's
    test_tenant_rls_postgres.py; rolled back with the role."""
    from mesiri.infrastructure.postgres.tenant import TENANT_SETTING

    db, created, _phone = world
    groups = WhatsAppGroupQueryService(db)
    group = await groups.start(
        organization_id=str(created.organization_id), project_id=str(created.project_id),
        site_id=str(created.sites[0].site_id), subject="Block A · Mesiri", created_by_user_id=None,
    )
    await groups.record_join_request(group=group, join_request_id="jr-rls", wa_id="919800000003", status="pending")

    role = f"wa87_rls_{uuid.uuid4().hex[:6]}"
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(Settings().postgres.dsn())
    try:
        async with engine.connect() as conn:
            tx = await conn.begin()
            await conn.execute(text(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS"))
            await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            await conn.execute(text(f"GRANT SELECT ON whatsapp_groups, whatsapp_group_join_requests TO {role}"))
            await conn.execute(text(f"SET LOCAL ROLE {role}"))

            async def visible(org) -> tuple[int, int]:
                await conn.execute(text("SELECT set_config(:s, :v, true)"), {"s": TENANT_SETTING, "v": str(org)})
                g = (await conn.execute(text("SELECT count(*) FROM whatsapp_groups WHERE id = :id"), {"id": group["id"]})).scalar()
                r = (await conn.execute(
                    text("SELECT count(*) FROM whatsapp_group_join_requests WHERE group_id = :id"), {"id": group["id"]}
                )).scalar()
                return g, r

            assert await visible(created.organization_id) == (1, 1)
            assert await visible(uuid.uuid4()) == (0, 0)
            await tx.rollback()
    finally:
        await engine.dispose()
