"""BE-03 step 2: row-level security against a real Postgres (integration).

The app's future login (`mesiri_app`, step 3) is neither superuser nor table
owner, so the tests switch to such a role (`SET LOCAL ROLE`) after setting
up two companies as the superuser. Everything runs in one transaction that
is rolled back, the role included.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from mesiri.application.identity.phone_numbers import whatsapp_number_taken
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.infrastructure.postgres.tenant import TENANT_SETTING, apply_tenant, unscoped

pytestmark = pytest.mark.integration

ROLE = "mesiri_rls_probe"


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


async def _two_companies(conn):
    now = dt.datetime.now(dt.UTC)
    a = await create_company(
        conn, NewCompany(
            name="Alpha Builders",
            owner_name="Anil",
            owner_phone="919876500201",
            project_name="Alpha Towers",
            site_names=("Block A",),
        ), now=now
    )
    b = await create_company(
        conn, NewCompany(
            name="Beta Builders",
            owner_name="Bina",
            owner_phone="919876500202",
            project_name="Beta Heights",
            site_names=("Tower 1",),
        ), now=now
    )
    await conn.execute(text(f"CREATE ROLE {ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS"))
    await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {ROLE}"))
    await conn.execute(
        text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROLE}")
    )
    await conn.execute(text(f"SET LOCAL ROLE {ROLE}"))
    return a, b


async def _ids(conn, sql: str, **params) -> set:
    return {r[0] for r in (await conn.execute(text(sql), params)).all()}


async def _as(conn, org) -> None:
    await conn.execute(
        text("SELECT set_config(:s, :v, true)"), {"s": TENANT_SETTING, "v": str(org) if org else ""}
    )


async def _refused(conn, sql: str, **params) -> bool:
    try:
        async with conn.begin_nested():
            await conn.execute(text(sql), params)
    except DBAPIError as exc:
        assert "row-level security" in str(exc)
        return True
    return False


async def test_a_company_sees_only_its_own_rows(conn) -> None:
    a, b = await _two_companies(conn)
    both = {a.organization_id, b.organization_id}

    await apply_tenant(conn, a.organization_id)
    assert await _ids(conn, "SELECT organization_id FROM projects") == {a.organization_id}
    assert await _ids(conn, "SELECT organization_id FROM sites") == {a.organization_id}
    assert await _ids(conn, "SELECT organization_id FROM users") == {a.organization_id}
    assert await _ids(conn, "SELECT organization_id FROM materials_catalog") == {a.organization_id}
    assert await _ids(conn, "SELECT id FROM organizations") == {a.organization_id}
    # A forgotten filter on the other company's id still returns nothing.
    assert not await _ids(conn, "SELECT id FROM projects WHERE id = :p", p=b.project_id)

    await _as(conn, None)  # nothing set: unchanged, as system jobs need
    assert both <= await _ids(conn, "SELECT organization_id FROM projects")


async def test_a_company_cannot_write_into_another(conn) -> None:
    a, b = await _two_companies(conn)
    await apply_tenant(conn, a.organization_id)

    assert await _refused(
        conn,
        "INSERT INTO projects (id, organization_id, name, status) "
        "VALUES (gen_random_uuid(), :org, 'Sneaky', 'on_track')",
        org=b.organization_id,
    )
    assert await _refused(
        conn, "UPDATE projects SET organization_id = :b WHERE id = :p", b=b.organization_id, p=a.project_id
    )
    # Another company's row can't be changed or deleted: it isn't visible.
    changed = await conn.execute(
        text("UPDATE projects SET name = 'Renamed' WHERE id = :p"), {"p": b.project_id}
    )
    assert changed.rowcount == 0
    deleted = await conn.execute(text("DELETE FROM sites WHERE id = :s"), {"s": b.site_id})
    assert deleted.rowcount == 0
    # Its own rows work as before.
    own = await conn.execute(
        text("UPDATE projects SET name = 'Alpha Towers' WHERE id = :p"), {"p": a.project_id}
    )
    assert own.rowcount == 1


async def test_rows_with_no_company_are_hidden_but_still_writable(conn) -> None:
    a, _ = await _two_companies(conn)
    await apply_tenant(conn, a.organization_id)
    message = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO inbound_messages (id, correlation_id, sender_wa_id, message_type,"
            " raw_payload, dedup_key) VALUES (:id, 'c-rls', '1', 'text', '{}', 'd-rls')"
        ),
        {"id": message},
    )
    assert not await _ids(conn, "SELECT id FROM inbound_messages WHERE id = :m", m=message)


async def test_checks_that_must_see_every_company_still_do(conn) -> None:
    a, _ = await _two_companies(conn)
    await apply_tenant(conn, a.organization_id)

    # B's owner's number, checked while scoped to A (BE-04 + unscoped).
    assert await whatsapp_number_taken(conn, "919876500202")
    # ...and the scope is back afterwards.
    setting = (
        await conn.execute(text("SELECT current_setting(:s, true)"), {"s": TENANT_SETTING})
    ).scalar_one()
    assert setting == str(a.organization_id)
    async with unscoped(conn):
        assert len(await _ids(conn, "SELECT organization_id FROM projects")) >= 2
    assert await _ids(conn, "SELECT organization_id FROM projects") == {a.organization_id}


async def test_every_company_table_has_the_policy(conn) -> None:
    """A new table with organization_id must get a policy (migration 0484)."""
    missing = await _ids(
        conn,
        """
        SELECT c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
        WHERE c.relkind = 'r'
          AND EXISTS (SELECT 1 FROM information_schema.columns col
                      WHERE col.table_schema = 'public' AND col.table_name = c.relname
                        AND col.column_name = 'organization_id')
          AND NOT (c.relrowsecurity AND EXISTS (
                SELECT 1 FROM pg_policies p
                WHERE p.schemaname = 'public' AND p.tablename = c.relname
                  AND p.policyname = 'tenant_isolation'))
        """,
    )
    assert missing == set()
