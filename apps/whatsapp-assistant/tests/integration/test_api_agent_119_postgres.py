"""WA-119 on a real database: the API agent records receipts through the real
materials and projects routers, with the real auth and company checks.

The model is scripted, but every id it sends is read from the API's own answers
(nothing is seeded into the script), so the test proves the read -> write chain
the real model has to follow. A user of another company can neither see the
project nor record into it.

Needs Postgres at head (``alembic upgrade head``); marked ``integration``.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi import FastAPI

from agent_api.agent import ApiAgent, confirm
from agent_api.client import Actor, ApiClient
from agent_api.tools import ALLOWED, SUMMARY_ARG, build_tools
from mesiri.bootstrap.settings import Settings
from mesiri.domains.materials.router import router as materials_router
from mesiri.domains.projects.router import router as projects_router
from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri_ai.fakes import FakeToolCallingProvider

pytestmark = pytest.mark.integration


@pytest.fixture
async def database():
    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    yield db
    await db.disconnect()


async def _company(db: PostgresDatabase, name: str) -> dict:
    ids = {k: uuid.uuid4() for k in ("org", "user", "project", "site", "cement", "tmt")}
    async with db.transaction() as conn:
        run = conn.execute
        await run(sa.text(
            "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
            "VALUES (:org, :name, 'local', 'default', 'active', now(), now())"), {**ids, "name": name})
        await run(sa.text(
            "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, created_at, updated_at) "
            "VALUES (:user, :org, :email, 'x', 'Ravi', 'admin', now(), now())"), {**ids, "email": f"{ids['user']}@t.in"})
        await run(sa.text(
            "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
            "VALUES (:project, :org, 'Green Villa', now(), now())"), ids)
        await run(sa.text(
            "INSERT INTO sites (id, project_id, organization_id, name) VALUES (:site, :project, :org, 'Main block')"), ids)
        for key, material, unit in (("cement", "Cement", "bags"), ("tmt", "TMT bar", "pieces")):
            await run(sa.text(
                "INSERT INTO materials_catalog (id, organization_id, name, default_unit_id, is_active, created_by) "
                "VALUES (:id, :org, :name, (SELECT id FROM units_of_measure WHERE code = :unit), true, :user)"),
                {"id": ids[key], "org": ids["org"], "user": ids["user"], "name": material, "unit": unit})
    return {k: str(v) for k, v in ids.items()}


def _app(db: PostgresDatabase) -> FastAPI:
    app = FastAPI()
    app.include_router(projects_router)
    app.include_router(materials_router)
    app.state.container = SimpleNamespace(material_db=db)
    return app


def _result(records: list, tool: str) -> object:
    """The JSON the API answered to the last call of ``tool`` in this run."""
    last = [r for r in records if r.name == tool][-1]
    return json.loads(last.outcome.content["result"])


def _model() -> FakeToolCallingProvider:
    def receipts(records: list) -> list:
        project = _result(records, "list_projects")[0]["id"]
        site = _result(records, "list_sites")[0]["id"]
        found = {r.arguments["search"]: json.loads(r.outcome.content["result"])["items"][0]
                 for r in records if r.name == "search_materials"}
        return [("record_receipt", {
            "project_id": project, "site_id": site, "material_id": item["id"],
            "unit_id": item["default_unit_id"], "quantity": 50, "occurred_date": "2026-11-01",
            "supplier": "Sri Traders", SUMMARY_ARG: f"50 {name}, Main block",
        }) for name, item in found.items()]

    return FakeToolCallingProvider([
        [("list_projects", {}), ("search_materials", {"search": "Cement"}), ("search_materials", {"search": "TMT"})],
        lambda records: [("list_sites", {"project_id": _result(records, "list_projects")[0]["id"]})],
        receipts,
        "Ready: 50 bags cement and 50 TMT bars at Main block. Confirm to save.",
    ])


def _tools(app: FastAPI):  # noqa: ANN202
    return build_tools(app.openapi(), tuple(a for a in ALLOWED if not a.path.startswith("/materials/transfers")))


async def test_a_receipt_message_is_recorded_through_the_real_api(database: PostgresDatabase) -> None:
    acme = await _company(database, "Acme Builders")
    app = _app(database)
    client = ApiClient(Actor(acme["user"], acme["org"], "admin", "Ravi"), app=app)
    try:
        turn = await ApiAgent(_model(), _tools(app)).run(client, "50 bag cement, 50 TMT vannu, Sri Traders")
        statuses = [c["result"].get("status") for c in turn.calls if c["tool"] != "record_receipt"]
        assert statuses and all(s == 200 for s in statuses), turn.calls
        assert len(turn.pending) == 2
        async with database.transaction() as conn:
            before = (await conn.execute(sa.text(
                "SELECT count(*) FROM material_receipts WHERE organization_id = :o"), {"o": acme["org"]})).scalar_one()
        assert before == 0  # held, not written

        results = await confirm(client, turn.pending)
        assert [r.status for r in results] == [201, 201], [r.body for r in results]
        again = await confirm(client, turn.pending)  # a repeated confirmation records nothing new
        assert all(r.ok for r in again)
    finally:
        await client.close()
    async with database.transaction() as conn:
        rows = (await conn.execute(sa.text(
            "SELECT material_id::text, quantity, site_id::text FROM material_receipts WHERE organization_id = :o"),
            {"o": acme["org"]})).all()
    assert sorted(r[0] for r in rows) == sorted([acme["cement"], acme["tmt"]])
    assert all(float(r[1]) == 50 and r[2] == acme["site"] for r in rows)


async def test_another_companys_user_cannot_see_or_record_into_it(database: PostgresDatabase) -> None:
    acme = await _company(database, "Acme Builders")
    other = await _company(database, "Other Co")
    app = _app(database)
    client = ApiClient(Actor(other["user"], other["org"], "admin"), app=app)
    try:
        projects = await client.call("GET", "/projects")
        assert acme["project"] not in {p["id"] for p in projects.body}
        sites = await client.call("GET", f"/projects/{acme['project']}/sites")
        assert not sites.ok or sites.body == []
        materials = await client.call("GET", "/materials", params={"search": "Cement"})
        assert acme["cement"] not in {m["id"] for m in materials.body["items"]}
        write = await client.call("POST", "/materials/inflows", json={
            "project_id": acme["project"], "site_id": acme["site"], "material_id": acme["cement"],
            "unit_id": str(uuid.uuid4()), "quantity": 5, "occurred_date": "2026-11-01"})
        assert write.status in (400, 403, 404, 422), write.body
    finally:
        await client.close()
    async with database.transaction() as conn:
        count = (await conn.execute(sa.text(
            "SELECT count(*) FROM material_receipts WHERE organization_id = :o"), {"o": acme["org"]})).scalar_one()
    assert count == 0
