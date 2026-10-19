"""SS-05: join codes and join requests, against a real Postgres
(integration). Each test runs in a transaction that is rolled back."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations import team_join
from mesiri.application.organizations.create_company import (
    START_TRIAL,
    NewCompany,
    create_company,
)
from mesiri.domains.organizations import settings as settings_spec
from mesiri.domains.organizations import team_join as rules

pytestmark = pytest.mark.integration

NOW = dt.datetime(2026, 10, 19, 9, 0, tzinfo=dt.UTC)


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


async def _company(conn, phone: str, name: str = "Acme Builders"):
    return await create_company(
        conn,
        NewCompany(
            name=name,
            owner_name="Suresh",
            owner_phone=phone,
            project_name="P1",
            site_names=("S1",),
            start_as=START_TRIAL,
        ),
        now=dt.datetime.now(dt.UTC),
    )


async def test_the_code_is_made_once_found_and_replaced(conn) -> None:
    created = await _company(conn, "9876500081")
    org = created.organization_id

    code = await team_join.join_code(conn, org, now=NOW)
    assert code.startswith("ACME-") and rules.normalize_code(code) == code
    assert await team_join.join_code(conn, org, now=NOW) == code  # stable
    found = await team_join.company_for_code(conn, code)
    assert found is not None and (found.organization_id, found.name) == (org, "Acme Builders")

    new = await team_join.join_code(conn, org, rotate=True, now=NOW)
    assert new != code
    assert await team_join.company_for_code(conn, code) is None  # the old code is dead
    assert (await team_join.company_for_code(conn, new)).organization_id == org


async def test_a_suspended_or_ended_company_takes_no_one(conn) -> None:
    created = await _company(conn, "9876500082")
    code = await team_join.join_code(conn, created.organization_id, now=NOW)
    await conn.execute(
        text("UPDATE organizations SET status = 'suspended' WHERE id = :id"),
        {"id": created.organization_id},
    )
    assert await team_join.company_for_code(conn, code) is None
    await conn.execute(
        text(
            "UPDATE organizations SET status = 'trial', trial_ends_at = now() - interval '1 day' "
            "WHERE id = :id"
        ),
        {"id": created.organization_id},
    )
    assert await team_join.company_for_code(conn, code) is None


async def test_requests_are_recorded_once_and_decided_once(conn) -> None:
    created = await _company(conn, "9876500083")
    org = created.organization_id

    request, new = await team_join.request_to_join(
        conn, org, phone="919876500091", name="Ravi", now=NOW
    )
    again, new_again = await team_join.request_to_join(
        conn, org, phone="919876500091", name="Ravi", now=NOW
    )
    assert new and not new_again and again["id"] == request["id"]

    decided_request, decided = await team_join.decide_request(
        conn, org, request_id=request["id"], approve=True, by="u1", now=NOW
    )
    assert decided and decided_request["status"] == rules.APPROVED
    _, twice = await team_join.decide_request(
        conn, org, request_id=request["id"], approve=False, by="u2", now=NOW
    )
    assert not twice


async def test_only_active_admins_with_a_number_are_asked(conn) -> None:
    created = await _company(conn, "9876500084")
    org = created.organization_id
    for role, status, number in (
        ("PROJECT_MANAGER", "active", "919876500085"),
        ("ADMIN", "inactive", "919876500086"),
        ("ADMIN", "active", None),
    ):
        await conn.execute(
            text(
                "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role,"
                " status, whatsapp_number, created_at) VALUES (gen_random_uuid(), :org, :email,"
                " 'x', 'Other', :role, :status, :number, now())"
            ),
            {"org": org, "email": f"{uuid.uuid4()}@example.test", "role": role,
             "status": status, "number": number},
        )

    approvers = await team_join.approvers(conn, org)

    assert [a.user_id for a in approvers] == [created.owner_user_id]


def test_join_settings_cannot_be_written_through_the_settings_api() -> None:
    for key in (settings_spec.JOIN_CODE, settings_spec.JOIN_REQUESTS):
        with pytest.raises(ValueError):
            settings_spec.validate(key, {"code": "EVIL-0000"})
