"""BE-04: one WhatsApp number = one person, on the number's digits (integration).

Every test runs in a transaction that is rolled back, so nothing is left in
the database.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from mesiri.application.identity.create_user_commands import CreateUserCommand
from mesiri.application.identity.phone_numbers import (
    NUMBER_TAKEN_MESSAGE,
    whatsapp_number_taken,
)
from mesiri.infrastructure.postgres.repositories.create_user_execution import (
    PostgresCreateUserExecutionRepository,
)
from mesiri_contracts.application.results.execution_result import ExecutionStatus

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


async def _org(conn, name: str) -> uuid.UUID:
    org_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO organizations (id, name, deployment_type, db_route, status) "
            "VALUES (:id, :name, 'shared', 'shared', 'active')"
        ),
        {"id": org_id, "name": name},
    )
    return org_id


async def _user(conn, org_id: uuid.UUID, name: str, number: str | None) -> uuid.UUID:
    user_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO users (id, organization_id, hashed_password, full_name, role, "
            "whatsapp_number) VALUES (:id, :org, 'x', :name, 'SITE_ENGINEER', :number)"
        ),
        {"id": user_id, "org": org_id, "name": name, "number": number},
    )
    return user_id


async def test_two_spellings_of_one_number_are_refused_by_the_database(conn) -> None:
    org = await _org(conn, "A")
    await _user(conn, org, "Rajesh", "+91 98765 43210")
    with pytest.raises(IntegrityError, match="ux_users_whatsapp_digits"):
        async with conn.begin_nested():
            await _user(conn, org, "Again", "919876543210")


async def test_rows_without_a_usable_number_do_not_clash(conn) -> None:
    org = await _org(conn, "A")
    for i, number in enumerate([None, None, "n/a", "-"]):
        await _user(conn, org, f"No number {i}", number)


async def test_taken_is_compared_on_digits_across_companies(conn) -> None:
    holder = await _user(conn, await _org(conn, "A"), "Rajesh", "+91 98765 43210")

    assert await whatsapp_number_taken(conn, "919876543210")
    assert await whatsapp_number_taken(conn, "+91-98765-43210")
    assert not await whatsapp_number_taken(conn, "919876543211")
    assert not await whatsapp_number_taken(conn, "")
    # Saving the holder's own number again is not a clash.
    assert not await whatsapp_number_taken(conn, "919876543210", except_user_id=holder)


async def test_whatsapp_add_user_refuses_without_naming_the_holder(conn) -> None:
    await _user(conn, await _org(conn, "A"), "Rajesh Kumar", "+91 98765 43210")
    other = await _org(conn, "B")

    result = await PostgresCreateUserExecutionRepository().persist_success(
        conn,
        CreateUserCommand(
            idempotency_key=f"be04-{uuid.uuid4().hex}",
            organization_id=str(other),
            created_by=str(uuid.uuid4()),
            full_name="Someone",
            whatsapp_number="919876543210",
        ),
    )

    assert result.status is ExecutionStatus.REJECTED
    assert result.rejection_reasons == [NUMBER_TAKEN_MESSAGE]
    assert "Rajesh" not in " ".join(result.rejection_reasons)
    count = (
        await conn.execute(text("SELECT count(*) FROM users WHERE organization_id = :o"), {"o": other})
    ).scalar_one()
    assert count == 0
