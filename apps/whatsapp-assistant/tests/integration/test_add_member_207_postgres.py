"""WA-158 on a real database, through the router the live app mounts: [207] shipped "add a person to a project"
and "a project name is never created twice" in backend/src/mesiri/domains/projects/router.py, which production does
not mount for /projects. Its people lookup answered 404, so every "add Rajesh to Zeta Plaza" was refused (3 Nov).

- the assistant's lookup (member-candidates) answers, and the v3 tool adds a person by the name they said;
- "Rana Mart" can't be created twice (any case or spacing), nor renamed onto another project's name;
- guards: a project manager who isn't on the project, or a site engineer, may not add; nobody is created.

Needs Postgres at head; marked ``integration``.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from tests.integration.test_api_agent_119_postgres import _company

from agent_api.agent import PendingWrite, confirm
from agent_api.app import build_api_app
from agent_api.client import Actor, ApiClient, new_idempotency_key

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _fresh_projects_engine():
    import projects.router as projects_router

    projects_router._engine = None
    yield
    if projects_router._engine is not None:
        await projects_router._engine.dispose()
    projects_router._engine = None


@pytest.fixture
async def database():
    from mesiri.bootstrap.settings import Settings
    from mesiri.infrastructure.postgres.database import PostgresDatabase

    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    yield db
    await db.disconnect()


async def _person(db, company: dict, name: str, role: str) -> str:  # noqa: ANN001
    pid = uuid.uuid4()
    async with db.transaction() as conn:
        await conn.execute(sa.text(
            "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, created_at, updated_at) "
            "VALUES (:id, :org, :email, 'x', :name, :role, 'active', now(), now())"),
            {"id": pid, "org": company["org"], "email": f"{pid}@t.in", "name": name, "role": role})
    return str(pid)


async def _members(db, project: str) -> list:  # noqa: ANN001
    async with db.transaction() as conn:
        return (await conn.execute(sa.text(
            "SELECT u.full_name, pm.role FROM project_members pm JOIN users u ON u.id = pm.user_id "
            "WHERE pm.project_id = :p"), {"p": project})).all()


async def test_a_person_is_added_by_the_name_they_said(database) -> None:  # noqa: ANN001
    co = await _company(database, "Members test")
    await _person(database, co, "Rajesh Kumar", "SITE_ENGINEER")
    client = ApiClient(Actor(co["user"], co["org"], "ADMIN", "Ravi"), app=build_api_app(database))
    try:
        lookup = await client.call("GET", f"/projects/{co['project']}/member-candidates")
        assert lookup.status == 200, lookup.body  # 3 Nov: 404 here refused every request
        assert "Rajesh Kumar" in [p["fullName"] for p in lookup.body]
        from agent_api.agent import settle_member

        body = {"userId": "Rajesh", "role": "site engineer"}
        path = f"/projects/{co['project']}/members"
        assert await settle_member(client, path, body) == ("", [])
        [saved] = await confirm(client, [PendingWrite("add_project_member", "POST", path, {}, body,
                                                      "Add Rajesh to Green Villa as site engineer", new_idempotency_key())])
    finally:
        await client.close()
    assert saved.ok, saved.body
    assert [(n, r) for n, r in await _members(database, co["project"])] == [("Rajesh Kumar", "SITE_ENGINEER")]


async def test_sibling_a_project_name_is_never_created_twice(database) -> None:  # noqa: ANN001
    co = await _company(database, "Duplicate names test")
    client = ApiClient(Actor(co["user"], co["org"], "ADMIN", "Ravi"), app=build_api_app(database))
    try:
        first = await client.call("POST", "/projects", json={"name": "Rana Mart"})
        again = await client.call("POST", "/projects", json={"name": "  rana   MART "})
        other = await client.call("POST", "/projects", json={"name": "Zeta Plaza"})
        rename = await client.call("PUT", f"/projects/{other.body['id']}", json={"name": "Rana Mart"})
        same = await client.call("PUT", f"/projects/{first.body['id']}", json={"name": "Rana Mart"})
    finally:
        await client.close()
    assert first.status in (200, 201) and other.status in (200, 201), (first.body, other.body)
    assert again.status == 409 and "Rana Mart already exists" in str(again.body)
    assert rename.status == 409
    assert same.status == 200  # guard: keeping its own name is not a duplicate


async def test_guard_who_may_add(database) -> None:  # noqa: ANN001
    co = await _company(database, "Who may add test")
    pm = await _person(database, co, "Priya", "PROJECT_MANAGER")  # not on the project
    se = await _person(database, co, "Suresh", "SITE_ENGINEER")
    worker = await _person(database, co, "Anil", "SITE_ENGINEER")
    app = build_api_app(database)
    for who, role in ((pm, "PROJECT_MANAGER"), (se, "SITE_ENGINEER")):
        client = ApiClient(Actor(who, co["org"], role, "x"), app=app)
        try:
            add = await client.call("POST", f"/projects/{co['project']}/members", json={"userId": worker, "role": "SITE_ENGINEER"})
            look = await client.call("GET", f"/projects/{co['project']}/member-candidates")
        finally:
            await client.close()
        assert add.status == 403 and look.status == 403, (role, add.body, look.body)
    assert await _members(database, co["project"]) == []
