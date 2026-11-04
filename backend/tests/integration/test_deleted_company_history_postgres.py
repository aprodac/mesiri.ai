"""SS-24: a deleted company's messages and costs stay readable, against a real Postgres.

Delete Tenant used to take every WhatsApp message with the company (and leave its
costs with no name), so the team couldn't see what a deleted trial had done or cost.
Runs in a transaction that is rolled back.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.audit.record import record_admin_action
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.organizations.delete_company import delete_company
from mesiri.domains.audit import actions as audit
from mesiri.infrastructure.postgres.repositories.admin_audit import company_name_sql

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


async def _company(conn):
    phone = "919" + str(uuid.uuid4().int)[:9]
    return await create_company(
        conn,
        NewCompany(name="AD GROUPS", owner_name="A", owner_phone=phone, project_name="CALICUT",
                   start_as="trial", signup_source="whatsapp"),
        now=_NOW,
    )  # fmt: skip


async def _message(conn, created) -> uuid.UUID:
    message_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO inbound_messages (id, correlation_id, sender_wa_id, message_type, raw_payload, "
            "dedup_key, organization_id, project_id, site_id) VALUES (:id, :c, :wa, 'text', '{}', :d, :o, :p, :s)"
        ),
        {"id": message_id, "c": f"test-{message_id}", "wa": "917907793657", "d": f"d-{message_id}",
         "o": created.organization_id, "p": created.project_id, "s": created.site_id},
    )  # fmt: skip
    return message_id


async def test_a_deleted_companys_messages_stay_named_deleted(conn) -> None:
    created = await _company(conn)
    message_id = await _message(conn, created)

    await delete_company(conn, created.organization_id)
    await record_admin_action(
        conn,
        actor=audit.AuditActor(kind=audit.ACTOR_PLATFORM_ADMIN),
        action=audit.COMPANY_DELETED,
        organization_id=created.organization_id,
        target_type="organization",
        target_id=created.organization_id,
        details={"name": "AD GROUPS"},
        now=_NOW,
    )

    row = (
        await conn.execute(
            text(
                f"SELECT im.organization_id, im.project_id, im.site_id, "
                f"{company_name_sql('im.organization_id')} AS company "
                "FROM inbound_messages im LEFT JOIN organizations o ON o.id = im.organization_id "
                "WHERE im.id = :id"
            ),
            {"id": message_id},
        )
    ).mappings().one()
    assert row["organization_id"] == created.organization_id  # kept, so it can be named
    assert row["project_id"] is None and row["site_id"] is None  # the project and site are gone
    assert row["company"] == "Deleted: AD GROUPS"


async def test_a_live_company_keeps_its_own_name(conn) -> None:
    created = await _company(conn)
    await _message(conn, created)
    name = (
        await conn.execute(
            text(
                f"SELECT {company_name_sql('im.organization_id')} AS company FROM inbound_messages im "
                "LEFT JOIN organizations o ON o.id = im.organization_id WHERE im.organization_id = :o"
            ),
            {"o": created.organization_id},
        )
    ).scalar_one()
    assert name == "AD GROUPS"
