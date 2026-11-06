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


# -- WEB-71: adding by number, and what the Live screen shows -------------------------


async def test_add_by_number_makes_them_then_puts_them_on_the_project(conn) -> None:
    from mesiri.application.identity.add_by_number import MemberNotAdded, add_to_project_by_number

    created = await _company(conn, "9876500087")
    org = created.organization_id
    project_id = (
        await conn.execute(text("SELECT id FROM projects WHERE organization_id = :o"), {"o": org})
    ).scalar_one()
    args = dict(
        organization_id=org, project_id=project_id, created_by=created.owner_user_id,
        created_by_role="ADMIN", full_name="Ravi Kumar", role="PROJECT_MANAGER",
    )

    added = await add_to_project_by_number(conn, whatsapp_number="98765 00088", **args)
    assert added.created and not added.already_on_project
    row = (
        await conn.execute(
            text(
                "SELECT u.whatsapp_number, pm.role FROM users u JOIN project_members pm "
                "ON pm.user_id = u.id WHERE u.id = :u AND pm.project_id = :p"
            ),
            {"u": added.user_id, "p": project_id},
        )
    ).one()
    assert row.whatsapp_number.endswith("9876500088") and row.role == "PROJECT_MANAGER"

    again = await add_to_project_by_number(conn, whatsapp_number="+91 98765 00088", **args)
    assert again.user_id == added.user_id and not again.created and again.already_on_project

    await _company(conn, "9876500089", name="Other Co")
    with pytest.raises(MemberNotAdded, match="another company"):
        await add_to_project_by_number(conn, whatsapp_number="9876500089", **args)


async def test_joining_now_follows_a_request_to_joined(conn) -> None:
    from mesiri.application.identity.add_by_number import add_to_project_by_number

    created = await _company(conn, "9876500090")
    org = created.organization_id
    # Signed up an hour ago (one transaction: now() would make everyone the sign-up owner).
    await conn.execute(text("UPDATE organizations SET created_at = now() - interval '1 hour' WHERE id = :o"), {"o": org})
    await conn.execute(text("UPDATE users SET created_at = now() - interval '1 hour' WHERE organization_id = :o"),
                       {"o": org})
    now = dt.datetime.now(dt.UTC)
    request, _ = await team_join.request_to_join(conn, org, phone="919876500092", name="Anu", now=now)
    [asked] = await team_join.joining_now(conn, org, now=now)
    assert (asked["name"], asked["step"], asked["source"], asked["phone_tail"]) == ("Anu", "asked", "code", "0092")

    await team_join.decide_request(conn, org, request_id=request["id"], approve=True, by="u", now=now)
    assert (await team_join.joining_now(conn, org, now=now))[0]["step"] == "approved"
    await team_join.note_step(conn, org, request_id=request["id"], role="SITE_ENGINEER")
    assert (await team_join.joining_now(conn, org, now=now))[0]["step"] == "role"

    project_id = (
        await conn.execute(text("SELECT id FROM projects WHERE organization_id = :o"), {"o": org})
    ).scalar_one()
    await add_to_project_by_number(
        conn, organization_id=org, project_id=project_id, created_by=created.owner_user_id,
        created_by_role="ADMIN", full_name="Anu", whatsapp_number="919876500092", role="SITE_ENGINEER",
    )
    await add_to_project_by_number(
        conn, organization_id=org, project_id=project_id, created_by=created.owner_user_id,
        created_by_role="ADMIN", full_name="Biju", whatsapp_number="919876500093", role="SITE_ENGINEER",
    )
    people = await team_join.joining_now(conn, org, now=dt.datetime.now(dt.UTC))
    by_name = {p["name"]: p for p in people}
    assert "Suresh" not in by_name  # the owner made at sign-up did not join
    assert by_name["Anu"]["step"] == "joined" and by_name["Anu"]["project"] == "P1"
    assert by_name["Anu"]["role"] == "SITE_ENGINEER"
    assert by_name["Biju"]["source"] == "added" and by_name["Biju"]["step"] == "joined"
