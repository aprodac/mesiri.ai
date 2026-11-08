"""Contract tests for the Cost control module (CC-01 / CC-04): cost centres, a category's centre, budget against
actual, access.

Requires a live Postgres reachable via Settings().postgres.dsn() -- run with `pytest -m integration`. Fixtures
mirror test_boq_api_contract.py.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import create_access_token
from mesiri.http.app import create_app
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration

_ALL = '{"mode": "all_projects", "projects": []}'


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(test_engine: AsyncEngine, monkeypatch):
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    app = create_app()

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


async def _run(engine, sql: str, **params):
    async with engine.begin() as conn:
        return await conn.execute(sa.text(sql), params)


async def _user(engine, org, role: str) -> tuple[uuid.UUID, str]:
    user_id = uuid.uuid4()
    await _run(engine,
               "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, access_policy, "
               "created_at, updated_at) VALUES (:id, :org, :e, 'hash', 'T', :role, 'active', CAST(:p AS jsonb), now(), now())",
               id=user_id, org=org, e=f"{uuid.uuid4().hex[:8]}@example.com", role=role, p=_ALL)
    return user_id, create_access_token(data={"sub": str(user_id), "org": str(org), "role": role})


@pytest.fixture
async def ctx(test_engine):
    org, project, site = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await _run(test_engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
               "VALUES (:id, 'Cost Org', 'local', 'default', 'active', now(), now())", id=org)
    admin_id, admin = await _user(test_engine, org, "admin")
    await _run(test_engine, "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
               "VALUES (:id, :org, 'Villa', now() - interval '20 days', now())", id=project, org=org)
    await _run(test_engine, "INSERT INTO sites (id, project_id, organization_id, name, status, created_at, updated_at) "
               "VALUES (:id, :p, :org, 'Main', 'active', now(), now())", id=site, p=project, org=org)
    cats = {}
    for name, code, centre in (("Materials", "MAT", "materials"), ("Labour", "LAB", "labour"),
                               ("Fuel & Transport", "FUEL", "fuel"), ("Tea and snacks", None, None)):
        cid = uuid.uuid4()
        await _run(test_engine, "INSERT INTO expense_categories (id, organization_id, name, code, cost_centre, created_by) "
                   "VALUES (:id, :org, :n, :c, :cc, :by)", id=cid, org=org, n=name, c=code, cc=centre, by=admin_id)
        cats[name] = cid
    return {"org": org, "project": project, "site": site, "admin": admin, "admin_id": admin_id, "cats": cats}


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _expense(engine, ctx, category: str, amount: str, days_ago: int = 1) -> uuid.UUID:
    eid = uuid.uuid4()
    await _run(engine, "INSERT INTO expenses (id, organization_id, project_id, site_id, amount, occurred_date, created_by, "
               "category_id, workflow_status) VALUES (:id, :org, :p, :s, :a, current_date - CAST(:d AS integer), :by, :c, "
               "'confirmed')", id=eid, org=ctx["org"], p=ctx["project"], s=ctx["site"], a=Decimal(amount), d=days_ago,
               by=ctx["admin_id"], c=ctx["cats"][category])
    return eid


def _centre(body: dict, key: str) -> Decimal:
    return Decimal(next(c["amount"] for c in body["centres"] if c["key"] == key))


async def test_centres_split_the_full_cost_and_add_up_to_it(client, ctx, test_engine):
    await _expense(test_engine, ctx, "Materials", "12000")
    await _expense(test_engine, ctx, "Fuel & Transport", "1500")
    await _expense(test_engine, ctx, "Tea and snacks", "300")
    await _expense(test_engine, ctx, "Materials", "999", days_ago=60)  # outside the period
    body = (await client.get(f"/cost/centres?project_id={ctx['project']}", headers=_h(ctx["admin"]))).json()
    assert _centre(body, "materials") == 12000 and _centre(body, "fuel") == 1500
    assert Decimal(body["not_set"]["amount"]) == 300
    assert body["not_set"]["parts"][0]["source"] == "Expenses: Tea and snacks"
    added = sum((Decimal(c["amount"]) for c in body["centres"]), Decimal(body["not_set"]["amount"]))
    assert added == Decimal(body["total"]) == 13800
    # The Expenses page's Full cost (finance /costs) is the same read model and the same total.
    full = (await client.get(f"/finance/costs?project_id={ctx['project']}", headers=_h(ctx["admin"]))).json()
    assert Decimal(full["total"]) == Decimal(body["total"])


async def test_a_category_centre_is_set_by_money_roles_and_moves_its_spending(client, ctx, test_engine):
    await _expense(test_engine, ctx, "Tea and snacks", "300")
    tea = ctx["cats"]["Tea and snacks"]
    _, pm = await _user(test_engine, ctx["org"], "PROJECT_MANAGER")
    assert (await client.patch(f"/cost/categories/{tea}", json={"cost_centre": "overhead"}, headers=_h(pm))).status_code == 403
    r = await client.patch(f"/cost/categories/{tea}", json={"cost_centre": "overhead"}, headers=_h(ctx["admin"]))
    assert r.status_code == 200 and r.json()["cost_centre"] == "overhead"
    body = (await client.get(f"/cost/centres?project_id={ctx['project']}", headers=_h(ctx["admin"]))).json()
    assert _centre(body, "overhead") == 300 and Decimal(body["not_set"]["amount"]) == 0
    assert (await client.patch(f"/cost/categories/{tea}", json={"cost_centre": "snacks"}, headers=_h(ctx["admin"]))).status_code == 422
    assert (await client.patch(f"/cost/categories/{tea}", json={"cost_centre": None}, headers=_h(ctx["admin"]))).json()["cost_centre"] is None
    # Another company's category is never found.
    other = uuid.uuid4()
    await _run(test_engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
               "VALUES (:id, 'Other', 'local', 'default', 'active', now(), now())", id=other)
    _, stranger = await _user(test_engine, other, "admin")
    assert (await client.patch(f"/cost/categories/{tea}", json={"cost_centre": "other"}, headers=_h(stranger))).status_code == 404


async def test_budget_sets_earned_against_spent_per_kind(client, ctx, test_engine):
    h = _h(ctx["admin"])
    section = (await client.post(f"/projects/{ctx['project']}/boq/sections", json={"name": "Concrete"}, headers=h)).json()
    line = (await client.post(f"/projects/{ctx['project']}/boq/sections/{section['id']}/lines", headers=h, json={
        "work": "M20 concrete", "unit": "cum", "planned_quantity": "100", "labour_rate": "1500", "material_rate": "3500"})).json()
    activity, quantity = uuid.uuid4(), uuid.uuid4()
    await _run(test_engine, "INSERT INTO activities (id, organization_id, project_id, site_id, work_type, activity_date, source) "
               "VALUES (:id, :org, :p, :s, 'M20 slab', current_date, 'dashboard')",
               id=activity, org=ctx["org"], p=ctx["project"], s=ctx["site"])
    await _run(test_engine, "INSERT INTO activity_quantities (id, activity_id, unit_id, quantity, planned_item_id) "
               "VALUES (:id, :a, (SELECT id FROM units_of_measure WHERE code = 'cum'), 8, :pi)",
               id=quantity, a=activity, pi=line["id"])
    await _expense(test_engine, ctx, "Materials", "30000", days_ago=3)
    body = (await client.get(f"/cost/projects/{ctx['project']}/budget", headers=h)).json()
    kinds = {k["kind"]: k for k in body["kinds"]}
    assert kinds["material"]["budget"] == "350000.00" and kinds["material"]["earned"] == "28000.00"
    assert kinds["material"]["actual"] == "30000.00" and kinds["material"]["difference"] == "-2000.00"
    assert kinds["labour"]["earned"] == "12000.00" and kinds["labour"]["actual"] == "0.00"
    assert kinds["subcontract"]["budget"] is None and kinds["subcontract"]["earned"] is None
    assert body["work_not_on_a_line"] == 0


async def test_engineers_do_not_see_cost_control(client, ctx, test_engine):
    _, engineer = await _user(test_engine, ctx["org"], "SITE_ENGINEER")
    for url in ("/cost/centres", "/cost/categories", f"/cost/projects/{ctx['project']}/budget"):
        assert (await client.get(url, headers=_h(engineer))).status_code == 403, url
