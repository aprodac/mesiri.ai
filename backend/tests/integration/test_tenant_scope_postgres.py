"""BE-03 step 1 against a real Postgres (integration): the bound company
reaches every transaction PostgresDatabase opens, is transaction-local (a
pooled connection never carries it into the next transaction), and the
dashboard's get_auth_context sets it on the request's own transaction."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.bootstrap.settings import Settings
from mesiri.domains.projects.router import get_auth_context
from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri.infrastructure.postgres.tenant import TENANT_SETTING, current_tenant, tenant_scope

pytestmark = pytest.mark.integration

ORG = uuid.UUID("11111111-1111-4111-8111-111111111111")
_SHOW = text(f"SELECT current_setting('{TENANT_SETTING}', true)")


@pytest.fixture
async def db():
    settings = Settings().postgres.model_copy(update={"pool_min_size": 1, "pool_max_size": 1})
    database = PostgresDatabase(settings)
    await database.connect()
    yield database
    await database.disconnect()


async def _setting(conn) -> str | None:
    return (await conn.execute(_SHOW)).scalar_one() or None


async def test_transactions_carry_the_bound_company_and_nothing_else(db) -> None:
    async with db.transaction() as conn:
        assert await _setting(conn) is None

    pid = text("SELECT pg_backend_pid()")
    with tenant_scope(ORG):
        async with db.transaction() as conn:
            assert await _setting(conn) == str(ORG)
            scoped_pid = (await conn.execute(pid)).scalar_one()

    # Same pooled connection, next transaction: gone.
    async with db.transaction() as conn:
        assert (await conn.execute(pid)).scalar_one() == scoped_pid
        assert await _setting(conn) is None


async def test_get_auth_context_scopes_the_request_transaction(db) -> None:
    async with db.transaction() as conn:
        created = await create_company(
            conn,
            NewCompany(name="Tenant Scope Co", owner_name="Owner", owner_phone="919876500199"),
            now=dt.datetime.now(dt.UTC),
        )
        payload = {"sub": str(created.owner_user_id), "org": str(created.organization_id), "role": "ADMIN"}
        with tenant_scope(None):
            context = await get_auth_context(jwt_payload=payload, conn=conn)
            assert context.organization_id == created.organization_id
            assert await _setting(conn) == str(created.organization_id)
            assert current_tenant() == created.organization_id
        await conn.rollback()
