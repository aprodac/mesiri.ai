"""SA-25: a number's free trials, deleted companies included, against a real Postgres.

Runs in a transaction that is rolled back, so nothing is left in the database.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from admin import people_router
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.organizations.delete_company import delete_company

pytestmark = pytest.mark.integration

_NOW = dt.datetime(2026, 11, 4, 6, 0, tzinfo=dt.UTC)


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


async def test_a_deleted_trial_company_is_still_found_by_its_number(conn) -> None:
    number = f"9190{uuid.uuid4().int % 10**8:08d}"
    kept = await create_company(
        conn, NewCompany(name="Kept Builders", owner_name="K", owner_phone=number, start_as="trial"), now=_NOW
    )
    rows = (await conn.execute(people_router.trials_statement(number[-10:]))).fetchall()
    assert [(r.company, r.organization_id) for r in rows] == [("Kept Builders", kept.organization_id)]

    # The control panel's Delete Tenant leaves the audit row: the trial still counts, the company is gone.
    await delete_company(conn, kept.organization_id)
    assert (await conn.execute(text("SELECT 1 FROM organizations WHERE id = :id"), {"id": kept.organization_id})).first() is None
    rows = (await conn.execute(people_router.trials_statement(number[-10:]))).fetchall()
    assert [(r.company, r.organization_id, r.number) for r in rows] == [("Kept Builders", None, number)]


async def test_a_company_that_did_not_start_on_trial_is_not_a_trial(conn) -> None:
    number = f"9191{uuid.uuid4().int % 10**8:08d}"
    await create_company(
        conn, NewCompany(name="Paid Builders", owner_name="P", owner_phone=number, start_as="active"), now=_NOW
    )
    assert (await conn.execute(people_router.trials_statement(number[-10:]))).fetchall() == []
