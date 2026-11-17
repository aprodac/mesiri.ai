"""SS-66: a person's learning sandbox against a real Postgres (integration).

The sandbox's history goes through the whole app in-process (``sample_story.seed``); that path was run end to end on
17 Nov against the full app (about 550 records, none failed) and the demo reset runs the same story. Here the seed is
replaced by a recorder, so these tests check what this item owns: the company, its people, the token, what may not
reach it, and that removing it leaves nothing.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid

import jwt
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from mesiri.application.learn import sandbox
from mesiri.application.organizations.companies_overview import list_companies
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.organizations.delete_company import delete_company
from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY
from mesiri.domains.organizations.lifecycle import SANDBOX, operational_sql

pytestmark = pytest.mark.integration

NOW = dt.datetime.now(dt.UTC)


@pytest.fixture
async def engine():
    eng = create_async_engine(Settings().postgres.dsn())
    yield eng
    await eng.dispose()


@pytest.fixture
async def person(engine):
    """A real company with its owner; removed afterwards with any sandbox left."""
    async with engine.begin() as conn:
        made = await create_company(conn, NewCompany(
            name="Acme Real Builders", owner_name="Asha Menon", owner_email=f"asha.{uuid.uuid4().hex}@acme.test",
            project_name="Real Tower", site_names=("Block 1",)))
    yield sandbox.RealPerson(user_id=made.owner_user_id, organization_id=made.organization_id, full_name="Asha Menon")
    async with engine.begin() as conn:
        for (org,) in (await conn.execute(text("SELECT id FROM organizations WHERE sandbox_user_id = :u"),
                                          {"u": made.owner_user_id})).all():
            await delete_company(conn, org)
        await delete_company(conn, made.organization_id)


@pytest.fixture(autouse=True)
def recorded_seed(monkeypatch):
    calls = []

    async def fake(app, info, real_org, today):
        calls.append({"info": info, "real_org": real_org})
        return {"project": 1}, []

    monkeypatch.setattr(sandbox, "_seed_in_fresh_context", fake)
    return calls


async def _rows(engine, org_id) -> int:
    """Rows anywhere that carry this company's id (the audit log keeps its line by design)."""
    async with engine.connect() as conn:
        tables = [r[0] for r in (await conn.execute(text(
            "SELECT c.table_name FROM information_schema.columns c JOIN information_schema.tables t "
            "ON t.table_name = c.table_name AND t.table_schema = c.table_schema "
            "WHERE c.column_name = 'organization_id' AND c.table_schema = 'public' AND t.table_type = 'BASE TABLE' "
            "AND c.table_name <> 'admin_audit_log'"))).all()]
        total = 0
        for table in tables:
            total += (await conn.execute(text(f'SELECT count(*) FROM "{table}" WHERE organization_id = :o'),  # noqa: S608
                                         {"o": org_id})).scalar()
        total += (await conn.execute(text("SELECT count(*) FROM organizations WHERE id = :o"), {"o": org_id})).scalar()
        return total


async def test_open_makes_a_private_non_operational_company_with_four_people(engine, person, recorded_seed):
    out = await sandbox.open_sandbox(engine, app=None, person=person, now=NOW)
    assert out.created and out.role == "ADMIN" and out.user_name == "Asha Menon"
    async with engine.connect() as conn:
        org = (await conn.execute(text("SELECT * FROM organizations WHERE id = :o"), {"o": out.organization_id})).mappings().one()
        people = (await conn.execute(text("SELECT role, email, whatsapp_number FROM users WHERE organization_id = :o"),
                                     {"o": out.organization_id})).mappings().all()
        operational = (await conn.execute(text(f"SELECT count(*) FROM organizations o WHERE o.id = :o AND {operational_sql('o')}"),  # noqa: S608
                                          {"o": out.organization_id})).scalar()
        listed = {c.id for c in await list_companies(conn)}
    assert org["status"] == SANDBOX and org["sandbox_of"] == person.organization_id
    assert org["sandbox_user_id"] == person.user_id and org["sandbox_expires_at"] > NOW + dt.timedelta(days=29)
    assert sorted(p["role"] for p in people) == ["ADMIN", "FINANCE", "PROJECT_MANAGER", "SITE_ENGINEER"]
    # Nothing can be sent: no number anywhere, and no real inbox.
    assert all(p["whatsapp_number"] is None and p["email"].endswith("@sandbox.mesiri.invalid") for p in people)
    assert operational == 0  # no scheduled job, report or WhatsApp reaches it
    assert out.organization_id not in listed and person.organization_id in listed  # not in the control panel
    assert recorded_seed[0]["real_org"] == person.organization_id
    claims = jwt.decode(out.token, SECRET_KEY, algorithms=[ALGORITHM])
    assert claims["org"] == str(out.organization_id) and claims["sandbox"] == str(person.organization_id)


async def test_opening_again_returns_the_same_one_and_any_role(engine, person, recorded_seed):
    first = await sandbox.open_sandbox(engine, None, person, now=NOW)
    again = await sandbox.open_sandbox(engine, None, person, role="site_engineer", now=NOW + dt.timedelta(days=10))
    assert again.organization_id == first.organization_id and not again.created and len(recorded_seed) == 1
    assert again.role == "SITE_ENGINEER" and again.user_name.startswith("Ravi")
    async with engine.connect() as conn:
        expires = (await conn.execute(text("SELECT sandbox_expires_at FROM organizations WHERE id = :o"),
                                      {"o": first.organization_id})).scalar()
    assert expires > NOW + dt.timedelta(days=39)  # opening moves it on
    with pytest.raises(sandbox.SandboxError):
        await sandbox.open_sandbox(engine, None, person, role="SUPER_ADMIN", now=NOW)


async def test_two_opens_at_once_make_one(engine, person, recorded_seed):
    a, b = await asyncio.gather(sandbox.open_sandbox(engine, None, person, now=NOW),
                                sandbox.open_sandbox(engine, None, person, now=NOW))
    assert a.organization_id == b.organization_id


async def test_a_sandbox_person_cannot_make_one(engine, person):
    out = await sandbox.open_sandbox(engine, None, person, now=NOW)
    async with engine.connect() as conn:
        user = (await conn.execute(text("SELECT id FROM users WHERE organization_id = :o AND role = 'ADMIN'"),
                                   {"o": out.organization_id})).scalar()
        with pytest.raises(sandbox.SandboxError) as err:
            await sandbox.real_person(conn, user, out.organization_id)
    assert err.value.status == 403


async def test_remove_leaves_nothing_and_never_touches_a_real_company(engine, person):
    out = await sandbox.open_sandbox(engine, None, person, now=NOW)
    assert await _rows(engine, out.organization_id) > 0
    assert await sandbox.remove_sandbox(engine, person) is True
    assert await _rows(engine, out.organization_id) == 0
    assert await sandbox.remove_sandbox(engine, person) is False
    async with engine.begin() as conn:
        with pytest.raises(sandbox.SandboxError):
            await sandbox._delete(conn, person.organization_id)  # the guard: only ever a sandbox
    assert await _rows(engine, person.organization_id) > 0


async def test_cleanup_removes_unopened_and_orphaned_keeps_fresh(engine, person):
    out = await sandbox.open_sandbox(engine, None, person, now=NOW)
    assert await sandbox.cleanup(engine, now=NOW) == 0
    assert await sandbox.cleanup(engine, now=NOW + dt.timedelta(days=31)) >= 1
    assert await _rows(engine, out.organization_id) == 0
