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
    yield {"org": org, "project": project, "site": site, "admin": admin, "admin_id": admin_id, "cats": cats}
    # Leave nothing behind for the suites after this one (CI runs the money paths in one database, in order).
    await _cleanup(test_engine, org)


async def _cleanup(engine, org) -> None:
    async with engine.begin() as conn:
        for sql in (
            "DELETE FROM progress_updates WHERE activity_id IN (SELECT id FROM activities WHERE organization_id = :org)",
            "DELETE FROM activity_quantities WHERE activity_id IN (SELECT id FROM activities WHERE organization_id = :org)",
            "DELETE FROM activities WHERE organization_id = :org",
            "DELETE FROM material_movements WHERE organization_id = :org",
            "DELETE FROM material_usage WHERE organization_id = :org",
            "DELETE FROM material_receipts WHERE organization_id = :org",
            "DELETE FROM purchase_orders WHERE organization_id = :org",
            "DELETE FROM boq_material_norms WHERE planned_item_id IN (SELECT id FROM work_package_planned_items "
            "WHERE organization_id = :org)",
            "DELETE FROM materials_catalog WHERE organization_id = :org",
            "DELETE FROM expense_payments WHERE organization_id = :org",
            "DELETE FROM expenses WHERE organization_id = :org",
            "DELETE FROM labour_attendance_reports WHERE organization_id = :org",
            "DELETE FROM work_packages WHERE organization_id = :org",
            "DELETE FROM notifications WHERE organization_id = :org",
            "DELETE FROM site_members WHERE site_id IN (SELECT id FROM sites WHERE organization_id = :org)",
            "DELETE FROM project_members WHERE project_id IN (SELECT id FROM projects WHERE organization_id = :org)",
            "DELETE FROM organizations WHERE id = :org",
        ):
            await conn.execute(sa.text(sql), {"org": org})


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
    # D-CC4: an engineer on two sites says which; never a page of money.
    _, engineer = await _user(test_engine, ctx["org"], "SITE_ENGINEER")
    assert (await client.get(f"/cost/projects/{p}/variance", headers=_h(engineer))).status_code == 422
    seen = (await client.get(f"/cost/projects/{p}/variance?site_id={other}", headers=_h(engineer))).json()
    assert seen["money_hidden"] is True and seen["lines"][0]["reason"] == "no_labour"


# -- CC-11: the evening cost card -----------------------------------------------------------------------------------


async def test_the_evening_card_goes_once_after_the_cut_off_to_who_runs_the_project(client, ctx, test_engine):
    import datetime as dt

    from mesiri.domains.costing.reminders import RULE, queue_cost_cards

    h, p = _h(ctx["admin"]), ctx["project"]
    plaster, _ = await _boq_lines(client, ctx)
    await _attendance(test_engine, ctx, [("mason", 4, "1100", None)], days_ago=0)
    await _work(test_engine, ctx, plaster["id"], "sqft", "300", 0)
    day = (await client.get(f"/cost/projects/{p}/labour", headers=h)).json()["groups"][0]["date"]
    await client.put(f"/cost/projects/{p}/labour", headers=h, json={
        "site_id": str(ctx["site"]), "date": day, "trade": "mason", "lines": [{"line_id": plaster["id"], "man_days": "4"}]})
    await _run(test_engine, "UPDATE users SET whatsapp_number = :n WHERE id = :u", n=f"+91{uuid.uuid4().int % 10**10:010d}",
               u=ctx["admin_id"])
    engineer_id, _ = await _user(test_engine, ctx["org"], "SITE_ENGINEER")
    await _run(test_engine, "UPDATE users SET whatsapp_number = :n WHERE id = :u", n=f"+91{uuid.uuid4().int % 10**10:010d}",
               u=engineer_id)
    today = dt.date.fromisoformat(day)
    now = dt.datetime.now(tz=dt.UTC)

    async def queue() -> int:
        async with test_engine.begin() as conn:
            return await queue_cost_cards(conn, ctx["org"], today, now)

    async def sent() -> list:
        return (await _run(test_engine, "SELECT recipient_user_id, payload FROM notifications WHERE organization_id = :o "
                           "AND rule_key = :r", o=ctx["org"], r=RULE)).mappings().all()

    # Before the cut-off: nothing.
    await _run(test_engine, "UPDATE projects SET reporting_cutoff_time = '23:59', reporting_timezone = 'Pacific/Kiritimati' "
               "WHERE id = :p", p=p)
    late = (now.astimezone(dt.timezone(dt.timedelta(hours=14))).time() >= dt.time(23, 59))
    if not late:
        assert await queue() == 0 and await sent() == []
    # After it: one card, to the admin only (an engineer does not see rates, D-CC4), and never twice that day.
    await _run(test_engine, "UPDATE projects SET reporting_cutoff_time = '00:00' WHERE id = :p", p=p)
    assert await queue() == 1
    assert await queue() == 0
    rows = await sent()
    assert [r["recipient_user_id"] for r in rows] == [ctx["admin_id"]]
    message = rows[0]["payload"]["message"]
    # 300 sq ft x 14 = 4,200 earned for 4,400 of masons: amber.
    assert "🟠 *Amber*: ₹4,200 of work earned for ₹4,400 of labour, ₹200 over." in message
    assert "Internal plastering 12mm: ₹4,400 of labour for 300 sqft" in message


async def test_no_card_when_the_company_has_cost_control_off(client, ctx, test_engine):
    import datetime as dt
    import json

    from mesiri.domains.costing.reminders import queue_cost_cards

    plaster, _ = await _boq_lines(client, ctx)
    await _work(test_engine, ctx, plaster["id"], "sqft", "300", 0)
    await _run(test_engine, "UPDATE projects SET reporting_cutoff_time = '00:00' WHERE id = :p", p=ctx["project"])
    await _run(test_engine, "INSERT INTO organization_settings (id, organization_id, key, value) VALUES (gen_random_uuid(), :o, 'enabled_modules', "
               "CAST(:v AS jsonb))", o=ctx["org"], v=json.dumps(["dpr", "finance"]))
    async with test_engine.begin() as conn:
        assert await queue_cost_cards(conn, ctx["org"], dt.date.today(), dt.datetime.now(tz=dt.UTC)) == 0


# -- CC-18 / CC-19: committed, forecast, portfolio ------------------------------------------------------------------


async def test_budget_says_what_is_committed_and_the_forecast_and_the_portfolio_agrees(client, ctx, test_engine):
    h, p = _h(ctx["admin"]), ctx["project"]
    plaster, _ = await _boq_lines(client, ctx)
    # Labour: 640 sq ft earned 8,960 for 8,800 of masons (CC-05). The labour budget is plastering 2,52,000 +
    # brickwork 1,00,000: forecast 8,800 + 3,43,040 x 8,800 / 8,960 = 3,45,714.29, 6,285.71 under.
    await _attendance(test_engine, ctx, [("mason", 8, "1100", None)], days_ago=1)
    await _work(test_engine, ctx, plaster["id"], "sqft", "640", 1)
    day = (await client.get(f"/cost/projects/{p}/labour", headers=h)).json()["groups"][0]["date"]
    await client.put(f"/cost/projects/{p}/labour", headers=h, json={
        "site_id": str(ctx["site"]), "date": day, "trade": "mason", "lines": [{"line_id": plaster["id"], "man_days": "8"}]})
    # Materials: an open order for 100 bags at 410, 40 delivered -> 24,600 still to come.
    vendor, material, order = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await _run(test_engine, "INSERT INTO vendors (id, organization_id, name, created_by) VALUES (:id, :org, 'Malabar', :u)",
               id=vendor, org=ctx["org"], u=ctx["admin_id"])
    await _run(test_engine, "INSERT INTO materials_catalog (id, organization_id, name, default_unit_id, is_active, created_by) "
               "VALUES (:id, :org, 'Cement', (SELECT id FROM units_of_measure WHERE code = 'bags'), true, :u)",
               id=material, org=ctx["org"], u=ctx["admin_id"])
    await _run(test_engine, "INSERT INTO purchase_orders (id, organization_id, number, project_id, site_id, vendor_id) "
               "VALUES (:id, :org, 99001, :p, :s, :v)", id=order, org=ctx["org"], p=p, s=ctx["site"], v=vendor)
    line = uuid.uuid4()
    await _run(test_engine, "INSERT INTO purchase_order_lines (id, organization_id, purchase_order_id, material_id, unit_id, "
               "quantity, rate) VALUES (:id, :org, :o, :m, (SELECT id FROM units_of_measure WHERE code = 'bags'), 100, 410)",
               id=line, org=ctx["org"], o=order, m=material)
    await _run(test_engine, "INSERT INTO material_receipts (id, organization_id, project_id, site_id, material_id, unit_id, "
               "material_name, unit, quantity, occurred_date, purchase_order_line_id, created_by) VALUES (gen_random_uuid(), "
               ":org, :p, :s, :m, (SELECT id FROM units_of_measure WHERE code = 'bags'), 'Cement', 'bags', 40, current_date, "
               ":l, :u)",
               org=ctx["org"], p=p, s=ctx["site"], m=material, l=line, u=ctx["admin_id"])

    kinds = {k["kind"]: k for k in (await client.get(f"/cost/projects/{p}/budget", headers=h)).json()["kinds"]}
    assert kinds["material"]["committed"] == "24600.00"
    assert kinds["subcontract"]["committed"] == "0.00" and kinds["labour"]["committed"] is None
    assert (kinds["labour"]["forecast"], kinds["labour"]["forecast_difference"]) == ("345714.29", "6285.71")
    assert kinds["material"]["forecast_basis"] == "no_budget"  # these lines have no material rate

    rows = (await client.get("/cost/portfolio", headers=h)).json()["projects"]
    row = next(r for r in rows if r["project_id"] == str(p))
    assert row["forecast"] == "345714.29" and row["forecast_kinds"] == ["labour"] and row["colour"] == "green"
    assert row["committed"] == "24600.00" and row["week"]["colour"] == "green"
    _, engineer = await _user(test_engine, ctx["org"], "SITE_ENGINEER")
    assert (await client.get("/cost/portfolio", headers=_h(engineer))).status_code == 403


# -- CC-08: material reconciliation ---------------------------------------------------------------------------------


async def test_materials_used_are_set_against_what_the_work_needed(client, ctx, test_engine):
    h, p = _h(ctx["admin"]), ctx["project"]
    plaster, _ = await _boq_lines(client, ctx)
    cement = uuid.uuid4()
    await _run(test_engine, "INSERT INTO materials_catalog (id, organization_id, name, default_unit_id, is_active, created_by) "
               "VALUES (:id, :org, 'Cement', (SELECT id FROM units_of_measure WHERE code = 'bags'), true, :u)",
               id=cement, org=ctx["org"], u=ctx["admin_id"])
    r = await client.put(f"/projects/{p}/boq/lines/{plaster['id']}/norms", headers=h, json={
        "norms": [{"material_id": str(cement), "quantity_per_unit": "0.0045", "wastage_pct": "5"}]})
    assert r.status_code == 200, r.text
    await _work(test_engine, ctx, plaster["id"], "sqft", "640", 1)
    bags = str((await _run(test_engine, "SELECT id FROM units_of_measure WHERE code = 'bags'")).scalar())
    day = str((await _run(test_engine, "SELECT current_date - 1")).scalar())
    for route, qty, reason in (("/materials/inflows", "60", "RECEIVED"), ("/materials/outflows", "4", "CONSUMED")):
        r = await client.post(route, headers={**h, "Idempotency-Key": str(uuid.uuid4())}, json={
            "project_id": str(p), "site_id": str(ctx["site"]), "material_id": str(cement), "unit_id": bags,
            "quantity": qty, "movement_reason": reason, "occurred_date": day})
        assert r.status_code == 201, r.text
    body = (await client.get(f"/cost/projects/{p}/materials", headers=h)).json()
    [row] = body["materials"]
    assert (row["material"], row["required_total"], row["should_have_used"]) == ("Cement", "85.05", "3.02")
    assert (row["received"], row["used"], row["on_hand"]) == ("60.00", "4.00", "56.00")
    assert (row["colour"], row["used_over_work"], row["short_by"]) == ("red", "0.98", "26.03")
    assert body["lines_without_norms"] == 1 and body["short_at_completion"] == 1


# -- CC-21: Excel export --------------------------------------------------------------------------------------------


async def test_the_excel_export_has_the_same_figures_as_the_pages(client, ctx, test_engine):
    import io

    from openpyxl import load_workbook

    h, p = _h(ctx["admin"]), ctx["project"]
    plaster, _ = await _boq_lines(client, ctx)
    await _attendance(test_engine, ctx, [("mason", 4, "1100", None)], days_ago=1)
    await _work(test_engine, ctx, plaster["id"], "sqft", "300", 1)
    day = (await client.get(f"/cost/projects/{p}/labour", headers=h)).json()["groups"][0]["date"]
    await client.put(f"/cost/projects/{p}/labour", headers=h, json={
        "site_id": str(ctx["site"]), "date": day, "trade": "mason", "lines": [{"line_id": plaster["id"], "man_days": "4"}]})
    r = await client.get(f"/cost/projects/{p}/export", headers=h)
    assert r.status_code == 200 and r.headers["content-disposition"].startswith('attachment; filename="mesiri-cost-Villa-')
    book = load_workbook(io.BytesIO(r.content))
    assert book.sheetnames == ["Summary", "BOQ lines", "Green-red", "Materials"]
    labour = next(row for row in book["Summary"].iter_rows(values_only=True) if row[0] == "Labour")
    assert (labour[2], labour[3]) == (4200, 4400)  # earned, spent: numbers Excel can add
    first = next(book["Green-red"].iter_rows(min_row=2, values_only=True))
    assert first[:3] == ("amber", "near budget", "Internal plastering 12mm")
    _, engineer = await _user(test_engine, ctx["org"], "SITE_ENGINEER")
    assert (await client.get(f"/cost/projects/{p}/export", headers=_h(engineer))).status_code == 403


# -- SEC-04: who may add or rename an expense category --------------------------------------------------------------


async def test_only_money_roles_add_or_rename_expense_categories(client, ctx, test_engine):
    tea = ctx["cats"]["Tea and snacks"]
    for role in ("SITE_ENGINEER", "PROJECT_MANAGER", "SUPERVISOR"):
        _, token = await _user(test_engine, ctx["org"], role)
        h = _h(token)
        assert (await client.post("/expenses/categories", json={"name": f"Diesel {role}"}, headers=h)).status_code == 403
        assert (await client.patch(f"/expenses/categories/{tea}", json={"name": "Food"}, headers=h)).status_code == 403
        assert (await client.get("/expenses/categories", headers=h)).status_code == 200  # reading stays open
    _, finance = await _user(test_engine, ctx["org"], "FINANCE")
    r = await client.post("/expenses/categories", json={"name": "Diesel"}, headers=_h(finance))
    assert r.status_code == 201
    assert (await client.patch(f"/expenses/categories/{tea}", json={"name": "Tea"}, headers=_h(ctx["admin"]))).status_code == 200


# -- D-CC8: cost before claimable GST -------------------------------------------------------------------------------


async def test_cost_is_before_claimable_gst_and_gst_that_stays_in_cost_is_said(client, ctx, test_engine):
    registered, unregistered = uuid.uuid4(), uuid.uuid4()
    for vid, name, gstin in ((registered, "Malabar", "32ABCDE1234F1Z5"), (unregistered, "Local shop", None)):
        await _run(test_engine, "INSERT INTO vendors (id, organization_id, name, gstin, created_by) VALUES (:id, :org, :n, :g, :u)",
                   id=vid, org=ctx["org"], n=name, g=gstin, u=ctx["admin_id"])
    for vendor, inclusive in ((registered, True), (unregistered, True), (registered, False)):
        await _run(test_engine, "INSERT INTO expenses (id, organization_id, project_id, site_id, amount, occurred_date, "
                   "created_by, category_id, workflow_status, vendor_id, tax_amount, is_tax_inclusive) VALUES "
                   "(gen_random_uuid(), :org, :p, :s, 11800, current_date - 1, :u, :c, 'confirmed', :v, 1800, :inc)",
                   org=ctx["org"], p=ctx["project"], s=ctx["site"], u=ctx["admin_id"], c=ctx["cats"]["Materials"],
                   v=vendor, inc=inclusive)
    h = _h(ctx["admin"])
    full = (await client.get(f"/finance/costs?project_id={ctx['project']}", headers=h)).json()
    # 10,000 (GSTIN, GST included: 1,800 claimed back) + 11,800 (no GSTIN) + 11,800 (GST said as not included).
    assert full["expenses"]["amount"] == "33600.00"
    assert full["gst"] == {"claimable": "1800.00", "in_cost": "3600.00", "in_cost_count": 2}
    centres = (await client.get(f"/cost/centres?project_id={ctx['project']}", headers=h)).json()
    assert Decimal(centres["total"]) == Decimal(full["total"]) and _centre(centres, "materials") == 33600
    assert centres["gst"]["claimable"] == "1800.00"



# -- D-CC4: a site engineer sees their site's colours, never money --------------------------------------------------


async def test_a_site_engineer_sees_their_sites_colours_and_quantities_never_rupees(client, ctx, test_engine):
    import json

    h, p = _h(ctx["admin"]), ctx["project"]
    plaster, _ = await _boq_lines(client, ctx)
    await _attendance(test_engine, ctx, [("mason", 4, "1100", None)], days_ago=1)
    await _work(test_engine, ctx, plaster["id"], "sqft", "300", 1)
    day = (await client.get(f"/cost/projects/{p}/labour", headers=h)).json()["groups"][0]["date"]
    await client.put(f"/cost/projects/{p}/labour", headers=h, json={
        "site_id": str(ctx["site"]), "date": day, "trade": "mason", "lines": [{"line_id": plaster["id"], "man_days": "4"}]})
    other = uuid.uuid4()
    await _run(test_engine, "INSERT INTO sites (id, project_id, organization_id, name, status, created_at, updated_at) "
               "VALUES (:id, :p, :org, 'Block B', 'active', now(), now())", id=other, p=p, org=ctx["org"])
    engineer_id = uuid.uuid4()
    policy = {"mode": "custom_projects", "projects": [
        {"projectId": str(p), "siteAccess": {"mode": "custom_sites", "siteIds": [str(ctx["site"])]}}]}
    await _run(test_engine,
               "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, access_policy, "
               "created_at, updated_at) VALUES (:id, :org, :e, 'hash', 'Eng', 'SITE_ENGINEER', 'active', CAST(:pol AS jsonb), "
               "now(), now())", id=engineer_id, org=ctx["org"], e=f"{uuid.uuid4().hex[:8]}@example.com", pol=json.dumps(policy))
    await _run(test_engine, "INSERT INTO project_members (id, project_id, user_id, role, site_access_mode) "
               "VALUES (gen_random_uuid(), :p, :u, 'SITE_ENGINEER', 'custom_sites')", p=p, u=engineer_id)
    await _run(test_engine, "INSERT INTO site_members (id, site_id, user_id) VALUES (gen_random_uuid(), :s, :u)",
               s=ctx["site"], u=engineer_id)
    eh = _h(create_access_token(data={"sub": str(engineer_id), "org": str(ctx["org"]), "role": "SITE_ENGINEER"}))

    r = await client.get(f"/cost/projects/{p}/variance", headers=eh)  # their only site, found for them
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["money_hidden"] is True and body["site_id"] == str(ctx["site"])
    [line] = body["lines"]
    assert (line["colour"], line["reason"], line["done_quantity"], line["labour_man_days"]) == ("amber", "near_budget", "300", "4")
    text = json.dumps(body)
    for money in ("earned", "cost", "rate", "difference", "ratio", "materials", "4200", "4400"):
        assert money not in text, money
    assert (await client.get(f"/cost/projects/{p}/variance?site_id={other}", headers=eh)).status_code == 403
    for url in (f"/cost/projects/{p}/budget", f"/cost/projects/{p}/labour", f"/cost/projects/{p}/materials", "/cost/portfolio"):
        assert (await client.get(url, headers=eh)).status_code == 403, url
