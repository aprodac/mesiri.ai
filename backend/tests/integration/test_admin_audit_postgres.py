"""BE-05: the superadmin audit log against a real Postgres (integration).

Every test runs in a transaction that is rolled back, so nothing is left in
the database.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.audit.record import record_admin_action
from mesiri.application.organizations.create_company import (
    CompanyCreationError,
    NewCompany,
    create_company,
)
from mesiri.domains.audit import actions as audit
from mesiri.infrastructure.postgres.repositories.admin_audit import (
    PostgresAdminAuditRepository,
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


def _phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


async def test_superadmin_creation_is_recorded_with_the_admin(conn) -> None:
    admin_id = uuid.uuid4()
    created = await create_company(
        conn,
        NewCompany(name="Suresh Builders", owner_name="Suresh", owner_phone=_phone()),
        now=_NOW,
        actor=audit.actor_from_admin({"sub": str(admin_id), "name": "Priya"}),
    )
    [entry] = await PostgresAdminAuditRepository(conn).list_for_organization(
        created.organization_id
    )
    assert entry.action == "company.created"
    assert (entry.actor_kind, entry.actor_user_id, entry.actor_label) == (
        "platform_admin",
        admin_id,
        "Priya",
    )
    assert entry.occurred_at == _NOW
    assert entry.details["owner_user_id"] == str(created.owner_user_id)
    assert entry.details["signup_source"] == "superadmin"


async def test_whatsapp_signup_is_recorded_as_the_owner(conn) -> None:
    phone = _phone()
    created = await create_company(
        conn,
        NewCompany(
            name="Kerala Homes",
            owner_name="Anu",
            owner_phone=phone,
            project_name="Villa",
            start_as="trial",
            signup_source="whatsapp",
        ),
        now=_NOW,
    )
    [entry] = await PostgresAdminAuditRepository(conn).list_for_organization(
        created.organization_id
    )
    assert entry.actor_kind == "self_signup"
    assert entry.actor_user_id == created.owner_user_id
    assert entry.actor_label == "91" + phone
    assert entry.details["status"] == "trial"
    assert entry.details["trial_ends_at"] == created.trial_ends_at.isoformat()


async def test_refused_company_leaves_no_entry(conn) -> None:
    phone = _phone()
    await create_company(conn, NewCompany(name="A", owner_name="A", owner_phone=phone), now=_NOW)
    before = (await conn.execute(text("SELECT count(*) FROM admin_audit_log"))).scalar_one()
    with pytest.raises(CompanyCreationError):
        await create_company(
            conn, NewCompany(name="B", owner_name="B", owner_phone=phone), now=_NOW
        )
    after = (await conn.execute(text("SELECT count(*) FROM admin_audit_log"))).scalar_one()
    assert after == before


async def test_entries_outlive_the_deleted_company(conn) -> None:
    created = await create_company(
        conn, NewCompany(name="Gone Ltd", owner_name="G", owner_phone=_phone()), now=_NOW
    )
    org_id = created.organization_id
    await conn.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": org_id})
    await record_admin_action(
        conn,
        actor=audit.SYSTEM,
        action=audit.COMPANY_DELETED,
        organization_id=org_id,
        now=_NOW + dt.timedelta(minutes=1),
    )
    entries = await PostgresAdminAuditRepository(conn).list_for_organization(org_id)
    # Newest first.
    assert [e.action for e in entries] == ["company.deleted", "company.created"]


async def test_paging_back_with_before(conn) -> None:
    org_id = uuid.uuid4()
    for minute in range(3):
        await record_admin_action(
            conn,
            actor=audit.SYSTEM,
            action=audit.COMPANY_SETTING_CHANGED,
            organization_id=org_id,
            summary=str(minute),
            now=_NOW + dt.timedelta(minutes=minute),
        )
    repo = PostgresAdminAuditRepository(conn)
    first = await repo.list_for_organization(org_id, limit=2)
    assert [e.summary for e in first] == ["2", "1"]
    rest = await repo.list_for_organization(org_id, limit=2, before=first[-1].occurred_at)
    assert [e.summary for e in rest] == ["0"]
