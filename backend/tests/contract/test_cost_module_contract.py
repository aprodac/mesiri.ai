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


# -- CC-05: labour put on BOQ lines ----------------------------------------------------------------------------------


async def _attendance(engine, ctx, lines: list[tuple], days_ago: int = 1, site=None) -> uuid.UUID:
    report = uuid.uuid4()
    await _run(engine, "INSERT INTO labour_attendance_reports (id, organization_id, project_id, site_id, occurred_date, "
               "recorded_via, created_at, created_by) VALUES (:id, :org, :p, :s, current_date - CAST(:d AS integer), "
               "'whatsapp_text', clock_timestamp(), :u)",
               id=report, org=ctx["org"], p=ctx["project"], s=site or ctx["site"], d=days_ago, u=ctx["admin_id"])
    for trade, n, wage, activity in lines:
        await _run(engine, "INSERT INTO labour_attendance_lines (id, report_id, trade, headcount, daily_wage, activity, "
                   "created_at) VALUES (:id, :r, :t, :n, :w, :a, now())",
                   id=uuid.uuid4(), r=report, t=trade, n=n, w=wage, a=activity)
    return report


async def _boq_lines(client, ctx) -> tuple[dict, dict]:
    h = _h(ctx["admin"])
    section = (await client.post(f"/projects/{ctx['project']}/boq/sections", json={"name": "Finishes"}, headers=h)).json()
    url = f"/projects/{ctx['project']}/boq/sections/{section['id']}/lines"
    plaster = (await client.post(url, headers=h, json={
        "work": "Internal plastering 12mm", "unit": "sqft", "planned_quantity": "18000", "labour_rate": "14"})).json()
    brick = (await client.post(url, headers=h, json={
        "work": "Brickwork 230mm", "unit": "cum", "planned_quantity": "50", "labour_rate": "2000"})).json()
    return plaster, brick


async def test_labour_is_put_on_boq_lines_by_man_days_and_set_against_earned(client, ctx, test_engine):
    h, p = _h(ctx["admin"]), ctx["project"]
    plaster, brick = await _boq_lines(client, ctx)
    # The GM's day: 4 masons at 1,100 plastering, 2 helpers at 1,000 = 6,400.
    await _attendance(test_engine, ctx, [("Mason", 4, "1100", "plastering first floor"), ("Helper", 2, "1000", None)])
    body = (await client.get(f"/cost/projects/{p}/labour", headers=h)).json()
    assert body["total"] == {"man_days": "6", "cost": "6400.00"}
    groups = {g["trade_key"]: g for g in body["groups"]}
    assert groups["mason"]["suggested_line_id"] == plaster["id"]  # from what the line said they did
    assert groups["helper"]["suggested_line_id"] is None  # nothing to go on: never guessed
    day = groups["mason"]["date"]

    r = await client.put(f"/cost/projects/{p}/labour", headers=h, json={
        "site_id": str(ctx["site"]), "date": day, "trade": "mason",
        "lines": [{"line_id": plaster["id"], "man_days": "3"}, {"line_id": brick["id"], "man_days": "1"}]})
    assert r.status_code == 200, r.text
    assert [(x["line_id"], x["cost"]) for x in r.json()["on_lines"]] == [(plaster["id"], "3300.00"), (brick["id"], "1100.00")]
    assert r.json()["suggested_line_id"] is None

    left = (await client.get(f"/cost/projects/{p}/labour?unallocated=true", headers=h)).json()
    assert [g["trade_key"] for g in left["groups"]] == ["helper"]
    assert left["not_on_a_line"] == {"man_days": "2", "cost": "2000.00"}

    # 600 sq ft plastered earns 600 x 14 = 8,400 of labour against the 3,300 put on the line.
    activity = uuid.uuid4()
    await _run(test_engine, "INSERT INTO activities (id, organization_id, project_id, site_id, work_type, activity_date, "
               "source) VALUES (:id, :org, :p, :s, 'Plastering', current_date - 1, 'dashboard')",
               id=activity, org=ctx["org"], p=p, s=ctx["site"])
    await _run(test_engine, "INSERT INTO activity_quantities (id, activity_id, unit_id, quantity, planned_item_id) "
               "VALUES (:id, :a, (SELECT id FROM units_of_measure WHERE code = 'sqft'), 600, :pi)",
               id=uuid.uuid4(), a=activity, pi=plaster["id"])
    budget = (await client.get(f"/cost/projects/{p}/budget", headers=h)).json()
    lines = {ln["id"]: ln for s in budget["boq"]["sections"] for ln in s["lines"]}
    assert lines[plaster["id"]]["labour_cost"] == "3300.00" and lines[plaster["id"]]["labour_man_days"] == "3"
    assert lines[plaster["id"]]["labour_difference"] == "5100.00"
    # Labour on brickwork and no brickwork measured yet: all of it is over (what the green / red will show).
    assert lines[brick["id"]]["labour_cost"] == "1100.00" and lines[brick["id"]]["labour_difference"] == "-1100.00"
    assert budget["labour_on_lines"] == {"man_days": "4", "cost": "4400.00"}
    assert budget["labour_not_on_a_line"]["cost"] == "2000.00"

    # Taken off every line: the day is back to "not on a line".
    r = await client.put(f"/cost/projects/{p}/labour", headers=h, json={
        "site_id": str(ctx["site"]), "date": day, "trade": "Mason", "lines": []})
    assert r.json()["on_lines"] == [] and r.json()["not_on_a_line"]["cost"] == "4400.00"


async def test_a_resent_attendance_list_keeps_the_split(client, ctx, test_engine):
    h, p = _h(ctx["admin"]), ctx["project"]
    plaster, _ = await _boq_lines(client, ctx)
    await _attendance(test_engine, ctx, [("mason", 4, "1000", None)])
    day = (await client.get(f"/cost/projects/{p}/labour", headers=h)).json()["groups"][0]["date"]
    await client.put(f"/cost/projects/{p}/labour", headers=h, json={
        "site_id": str(ctx["site"]), "date": day, "trade": "mason", "lines": [{"line_id": plaster["id"], "man_days": "4"}]})
    # The supervisor re-sends the day as 5 masons (BE-10: the later figure replaces the earlier one).
    await _attendance(test_engine, ctx, [("Mason", 5, "1000", None)])
    g = (await client.get(f"/cost/projects/{p}/labour", headers=h)).json()["groups"][0]
    assert g["man_days"] == "5" and g["on_lines"][0]["cost"] == "4000.00"
    assert g["not_on_a_line"] == {"man_days": "1", "cost": "1000.00"}


async def test_labour_on_lines_is_refused_when_it_does_not_fit(client, ctx, test_engine):
    h, p = _h(ctx["admin"]), ctx["project"]
    plaster, brick = await _boq_lines(client, ctx)
    await _attendance(test_engine, ctx, [("mason", 4, "1000", None)])
    day = (await client.get(f"/cost/projects/{p}/labour", headers=h)).json()["groups"][0]["date"]
    put = {"site_id": str(ctx["site"]), "date": day, "trade": "mason"}

    async def status(lines, **extra):
        return (await client.put(f"/cost/projects/{p}/labour", headers=h, json={**put, **extra, "lines": lines})).status_code

    assert await status([{"line_id": plaster["id"], "man_days": "5"}]) == 422  # more than attendance has
    assert await status([{"line_id": plaster["id"], "man_days": "1"}, {"line_id": plaster["id"], "man_days": "1"}]) == 422
    assert await status([{"line_id": str(uuid.uuid4()), "man_days": "1"}]) == 422  # not a line of this project
    assert await status([{"line_id": plaster["id"], "man_days": "0"}]) == 422
    assert await status([{"line_id": brick["id"], "man_days": "1"}], trade="carpenter") == 404  # no such attendance
    _, engineer = await _user(test_engine, ctx["org"], "SITE_ENGINEER")
    assert (await client.get(f"/cost/projects/{p}/labour", headers=_h(engineer))).status_code == 403
    r = await client.put(f"/cost/projects/{p}/labour", headers=_h(engineer),
                         json={**put, "lines": [{"line_id": plaster["id"], "man_days": "1"}]})
    assert r.status_code == 403


# -- CC-07: green / amber / red per BOQ line -------------------------------------------------------------------------


async def _work(engine, ctx, line_id: str, unit: str, qty: str, days_ago: int, site=None) -> None:
    activity = uuid.uuid4()
    await _run(engine, "INSERT INTO activities (id, organization_id, project_id, site_id, work_type, activity_date, "
               "source) VALUES (:id, :org, :p, :s, 'Work', current_date - CAST(:d AS integer), 'dashboard')",
               id=activity, org=ctx["org"], p=ctx["project"], s=site or ctx["site"], d=days_ago)
    await _run(engine, "INSERT INTO activity_quantities (id, activity_id, unit_id, quantity, planned_item_id) "
               "VALUES (:id, :a, (SELECT id FROM units_of_measure WHERE code = :u), :q, :pi)",
               id=uuid.uuid4(), a=activity, u=unit, q=Decimal(qty), pi=line_id)


async def test_variance_colours_each_line_and_each_day(client, ctx, test_engine):
    h, p = _h(ctx["admin"]), ctx["project"]
    plaster, brick = await _boq_lines(client, ctx)
    for days_ago, sqft in ((1, "300"), (2, "400")):
        await _attendance(test_engine, ctx, [("mason", 4, "1100", None), ("helper", 2, "1000", None)], days_ago=days_ago)
        await _work(test_engine, ctx, plaster["id"], "sqft", sqft, days_ago)
    groups = (await client.get(f"/cost/projects/{p}/labour", headers=h)).json()["groups"]
    for g in groups:
        line = plaster if g["trade_key"] == "mason" else brick
        if g["trade_key"] == "helper" and g["date"] != groups[0]["date"]:
            continue  # one day of helpers stays off every line
        await client.put(f"/cost/projects/{p}/labour", headers=h, json={
            "site_id": g["site_id"], "date": g["date"], "trade": g["trade_key"],
            "lines": [{"line_id": line["id"], "man_days": g["man_days"]}]})

    body = (await client.get(f"/cost/projects/{p}/variance", headers=h)).json()
    lines = {ln["line_id"]: ln for ln in body["lines"]}
    # Plastering: 700 sq ft x 14 = 9,800 earned for 8,800 of masons: green.
    assert (lines[plaster["id"]]["colour"], lines[plaster["id"]]["earned_labour"], lines[plaster["id"]]["labour_cost"]) == (
        "green", "9800.00", "8800.00")
    # Helpers on brickwork and no brickwork measured: red, said why.
    assert (lines[brick["id"]]["colour"], lines[brick["id"]]["reason"]) == ("red", "labour_no_work")
    assert body["lines"][0]["line_id"] == brick["id"]  # worst first
    assert body["labour"]["not_on_a_line"]["cost"] == "2000.00"
    assert body["labour"]["attendance_cost"] == "12800.00"
    days = {d["date"]: d for d in body["days"]}
    yesterday, before = sorted(days)[-1], sorted(days)[0]
    # Yesterday: 300 x 14 = 4,200 for 4,400 of masons (amber) and 2,000 of helpers on brickwork, nothing measured.
    assert days[yesterday]["colour"] == "red" and days[yesterday]["lines"]["red"] == 1
    assert days[before]["earned_labour"] == "5600.00" and days[before]["colour"] == "green"

    one_day = (await client.get(f"/cost/projects/{p}/variance?date_from={yesterday}&date_to={yesterday}", headers=h)).json()
    plaster_day = next(ln for ln in one_day["lines"] if ln["line_id"] == plaster["id"])
    assert (plaster_day["colour"], plaster_day["cost_per_unit"], plaster_day["labour_rate"]) == ("amber", "14.67", "14.00")
    # The BOQ's own done-to-date is unchanged by the per-day count (one rule).
    boq = (await client.get(f"/projects/{p}/boq", headers=h)).json()
    assert next(ln for s in boq["sections"] for ln in s["lines"] if ln["id"] == plaster["id"])["done_quantity"] == "700.000"


async def test_variance_for_one_site_and_who_sees_it(client, ctx, test_engine):
    h, p = _h(ctx["admin"]), ctx["project"]
    plaster, _ = await _boq_lines(client, ctx)
    other = uuid.uuid4()
    await _run(test_engine, "INSERT INTO sites (id, project_id, organization_id, name, status, created_at, updated_at) "
               "VALUES (:id, :p, :org, 'Block B', 'active', now(), now())", id=other, p=p, org=ctx["org"])
    await _work(test_engine, ctx, plaster["id"], "sqft", "100", 1)
    await _work(test_engine, ctx, plaster["id"], "sqft", "250", 1, site=other)
    body = (await client.get(f"/cost/projects/{p}/variance?site_id={other}", headers=h)).json()
    assert [(ln["done_quantity"], ln["reason"]) for ln in body["lines"]] == [("250", "no_labour")]
    assert (await client.get(f"/cost/projects/{p}/variance?site_id={uuid.uuid4()}", headers=h)).status_code == 422
    assert (await client.get(f"/cost/projects/{p}/variance?date_from=2026-02-01&date_to=2026-01-01", headers=h)).status_code == 422
    _, engineer = await _user(test_engine, ctx["org"], "SITE_ENGINEER")
    assert (await client.get(f"/cost/projects/{p}/variance", headers=_h(engineer))).status_code == 403
