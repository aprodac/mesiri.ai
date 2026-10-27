"""Request 124: `PostgresDatabase.shared_transaction()` against a real Postgres.

Everything a Save writes through several services must commit together or not at
all, and a service that opens its own `transaction()` inside the block must join
it (in a savepoint), take turns on the one connection, and leave a failure a
caller catches as a failure of that service only.

Run with a live database:
    pytest backend/tests/integration/test_shared_transaction_postgres.py -m integration
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri.infrastructure.postgres.tenant import tenant_scope
from mesiri_contracts.common.errors import MesiriError

pytestmark = pytest.mark.integration


@pytest.fixture
async def db():
    database = PostgresDatabase(Settings().postgres)
    await database.connect()
    yield database
    await database.disconnect()


@pytest.fixture
async def company():
    """A company and a user, committed (the block under test uses its own connections)."""
    org, user = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(Settings().postgres.dsn())
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at) "
                "VALUES (:id, :name, 'local', 'default', 'active', now())"
            ),
            {"id": org, "name": f"shared-tx-{org}"},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, created_at) "
                "VALUES (:id, :org, :email, 'x', 'Test', 'admin', 'active', now())"
            ),
            {"id": user, "org": org, "email": f"{user}@example.test"},
        )
    yield org, user
    async with engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM message_drafts WHERE organization_id = :o"), {"o": org})
        await conn.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": user})
        await conn.execute(sa.text("DELETE FROM organizations WHERE id = :o"), {"o": org})
    await engine.dispose()


async def _insert(db: PostgresDatabase, org, user, status: str = "saved") -> uuid.UUID:
    draft_id = uuid.uuid4()
    async with db.transaction() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO message_drafts (id, organization_id, user_id, status, items) "
                "VALUES (:id, :org, :user, :status, CAST(:items AS jsonb))"
            ),
            {"id": draft_id, "org": org, "user": user, "status": status, "items": json.dumps([])},
        )
    return draft_id


async def _count(db: PostgresDatabase, org) -> int:
    async with db.transaction() as conn:
        return (
            await conn.execute(sa.text("SELECT count(*) FROM message_drafts WHERE organization_id = :o"), {"o": org})
        ).scalar_one()


async def test_everything_in_the_block_commits_together(db, company):
    org, user = company
    async with db.shared_transaction():
        await _insert(db, org, user)
        await _insert(db, org, user)
    assert await _count(db, org) == 2


async def test_an_error_out_of_the_block_writes_nothing(db, company):
    org, user = company
    with pytest.raises(RuntimeError):  # the caller's own exception comes out as it is
        async with db.shared_transaction():
            await _insert(db, org, user)
            await _insert(db, org, user)
            raise RuntimeError("the third service failed")
    assert await _count(db, org) == 0


async def test_a_joined_service_sees_what_an_earlier_one_wrote_before_the_commit(db, company):
    org, user = company
    async with db.shared_transaction():
        await _insert(db, org, user)
        assert await _count(db, org) == 1  # the same connection: its own uncommitted row
    assert await _count(db, org) == 1


async def test_without_the_block_each_service_commits_on_its_own(db, company):
    org, user = company
    await _insert(db, org, user)
    with pytest.raises(MesiriError):  # (transaction() maps any exception, as always)
        async with db.transaction():
            await _insert(db, org, user)  # its own transaction: committed at once
            raise RuntimeError("late")
    assert await _count(db, org) == 2


async def test_a_failure_a_caller_catches_is_that_services_alone(db, company):
    org, user = company
    async with db.shared_transaction():
        await _insert(db, org, user)
        with pytest.raises(Exception):  # noqa: B017, PT011 -- the mapped database error
            async with db.transaction() as conn:
                await conn.execute(
                    sa.text(
                        "INSERT INTO message_drafts (id, organization_id, user_id, status) "
                        "VALUES (:id, :org, :user, 'not-a-status')"
                    ),
                    {"id": uuid.uuid4(), "org": org, "user": user},
                )
        await _insert(db, org, user)  # the transaction is not aborted
    assert await _count(db, org) == 2


async def test_tasks_started_inside_take_turns_on_the_one_connection(db, company):
    org, user = company

    async def one() -> None:
        await _insert(db, org, user)

    async with db.shared_transaction():
        await asyncio.gather(one(), one(), one(), one())
    assert await _count(db, org) == 4


async def test_only_one_draft_is_open_per_sender(db, company):
    org, user = company
    await _insert(db, org, user, status="open")
    with pytest.raises(Exception):  # noqa: B017, PT011
        await _insert(db, org, user, status="open")
    await _insert(db, org, user, status="saved")  # any number once settled


async def test_a_company_sees_only_its_own_drafts(db, company):
    org, user = company
    other = uuid.uuid4()
    engine = create_async_engine(Settings().postgres.dsn())
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at) "
                "VALUES (:id, :name, 'local', 'default', 'active', now())"
            ),
            {"id": other, "name": f"shared-tx-other-{other}"},
        )
    try:
        await _insert(db, org, user)
        # The app's own login is not a superuser: probe with such a role inside a rolled-back transaction.
        async with engine.connect() as conn:
            tx = await conn.begin()
            await conn.execute(sa.text("DROP ROLE IF EXISTS mesiri_drafts_probe"))
            await conn.execute(sa.text("CREATE ROLE mesiri_drafts_probe NOLOGIN NOSUPERUSER NOBYPASSRLS"))
            await conn.execute(sa.text("GRANT USAGE ON SCHEMA public TO mesiri_drafts_probe"))
            await conn.execute(sa.text("GRANT SELECT, INSERT, UPDATE ON message_drafts TO mesiri_drafts_probe"))
            await conn.execute(sa.text("SET LOCAL ROLE mesiri_drafts_probe"))
            await conn.execute(sa.text("SELECT set_config('mesiri.organization_id', :o, true)"), {"o": str(other)})
            seen = (await conn.execute(sa.text("SELECT count(*) FROM message_drafts"))).scalar_one()
            assert seen == 0  # another company's drafts are invisible
            await conn.execute(sa.text("SELECT set_config('mesiri.organization_id', :o, true)"), {"o": str(org)})
            assert (await conn.execute(sa.text("SELECT count(*) FROM message_drafts"))).scalar_one() == 1
            await tx.rollback()
    finally:
        async with engine.begin() as conn:
            await conn.execute(sa.text("DELETE FROM organizations WHERE id = :o"), {"o": other})
        await engine.dispose()


async def test_the_block_is_scoped_to_the_bound_company(db, company):
    org, user = company
    with tenant_scope(org):
        async with db.shared_transaction():
            async with db.transaction() as conn:
                current = (
                    await conn.execute(sa.text("SELECT current_setting('mesiri.organization_id', true)"))
                ).scalar_one()
            assert current == str(org)
