"""Contract tests for the approvals inbox (NXT-08): GET /approvals/waiting on Postgres.

Requires a live Postgres reachable via Settings().postgres.dsn() -- run with `pytest -m integration`.

The rule under test: a row is in a person's inbox exactly when the module's own page would show it to them and they
may act on it. So per role: the site engineer sees their site's report and their own task; the project manager (one
project) the requests there; finance the RA bill draft; the admin everything; another company nothing; a module
switched off takes its rows away.
"""

from __future__ import annotations

import datetime
import json
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mesiri.application.dpr.project_day import company_today
from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import create_access_token
from mesiri.http.app import create_app
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


def _app(test_engine: AsyncEngine, monkeypatch, modules: list[str] | None):
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    if modules is not None:
        async def enabled(request, organization_id):
            return modules

        monkeypatch.setattr("mesiri.domains.approvals.router.read_enabled_modules", enabled)
    app = create_app()

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    return app


@pytest.fixture
async def client(test_engine, monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=_app(test_engine, monkeypatch, None)),
                           base_url="http://testserver") as c:
        yield c
    async with test_engine.begin() as conn:  # RA bills hold their BOQ lines (RESTRICT), as in the billing suite
        await conn.execute(sa.text("DELETE FROM client_receipts"))
        await conn.execute(sa.text("DELETE FROM ra_bills"))


async def _exec(engine, sql: str, **params):
    async with engine.begin() as conn:
        return await conn.execute(sa.text(sql), params)


async def _user(engine, org, role: str, name: str, projects: list | None = None) -> dict:
    user_id = uuid.uuid4()
    policy = {"mode": "selected_projects", "projects": [str(p) for p in projects]} if projects \
        else {"mode": "all_projects", "projects": []}
    await _exec(engine, "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, "
                        "access_policy, whatsapp_number, created_at, updated_at) VALUES (:id, :org, :email, 'hash', "
                        ":name, :role, 'active', CAST(:policy AS jsonb), :wa, now(), now())",
                id=user_id, org=org, email=f"{uuid.uuid4().hex[:8]}@example.com", role=role, name=name,
                policy=json.dumps(policy), wa=f"+9190{uuid.uuid4().int % 10**8:08d}")
    for p in projects or []:
        await _exec(engine, "INSERT INTO project_members (id, project_id, user_id, role, site_access_mode) "
                            "VALUES (gen_random_uuid(), :p, :u, :r, 'all_sites')", p=p, u=user_id, r=role)
    token = create_access_token(data={"sub": str(user_id), "org": str(org), "role": role})
    return {"id": user_id, "h": {"Authorization": f"Bearer {token}"}}


async def _org(engine, name: str) -> uuid.UUID:
    org = uuid.uuid4()
    await _exec(engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, "
                        "updated_at) VALUES (:id, :n, 'local', 'default', 'active', now(), now())", id=org, n=name)
    return org


async def _project(engine, org, name: str) -> tuple[uuid.UUID, uuid.UUID]:
    project, site = uuid.uuid4(), uuid.uuid4()
    await _exec(engine, "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                        "VALUES (:id, :org, :n, now(), now())", id=project, org=org, n=name)
    await _exec(engine, "INSERT INTO sites (id, project_id, organization_id, name, status, created_at, updated_at) "
                        "VALUES (:id, :p, :org, :n, 'active', now(), now())", id=site, p=project, org=org,
                n=f"{name} site")
    return project, site


async def _drafts(engine, org, project, site, day: datetime.date, n: int) -> None:
    for _ in range(n):
        await _exec(engine, "INSERT INTO fact_reviews (id, organization_id, fact_type, fact_id, project_id, site_id, "
                            "fact_date, state, created_at) VALUES (gen_random_uuid(), :org, 'activity', "
                            "gen_random_uuid(), :p, :s, :d, 'draft', now())", org=org, p=project, s=site, d=day)


@pytest.fixture
async def world(test_engine, client):
    org = await _org(test_engine, "Inbox Builders")
    villa, villa_site = await _project(test_engine, org, "Villa Kakkanad")
    flats, flats_site = await _project(test_engine, org, "Edappally Flats")
    admin = await _user(test_engine, org, "admin", "Meera")
    pm = await _user(test_engine, org, "project_manager", "Joseph", projects=[villa])
    arun = await _user(test_engine, org, "site_engineer", "Arun", projects=[villa])
    finance = await _user(test_engine, org, "finance", "Asha")
    async with test_engine.begin() as conn:
        today = await company_today(conn, org)

    # Site reports: 2 to confirm today at the villa; 1 left from yesterday at the flats (urgent).
    await _drafts(test_engine, org, villa, villa_site, today, 2)
    await _drafts(test_engine, org, flats, flats_site, today - datetime.timedelta(days=1), 1)

    # A material request from Arun at the villa, waiting for the office.
    units = {u["code"]: u["id"] for u in (await client.get("/materials/units-of-measure", headers=admin["h"])).json()["items"]}
    cement = (await client.post("/materials", json={"name": "Cement OPC 53", "default_unit_id": units["bags"]},
                                headers=admin["h"])).json()["id"]
    r = await client.post("/procurement/requests", headers=arun["h"], json={
        "project_id": str(villa), "site_id": str(villa_site),
        "lines": [{"material_id": cement, "quantity": "200", "unit_id": units["bags"]}]})
    assert r.status_code == 201, r.text
    request_ref = r.json()["ref"]

    # An RA bill left in draft at the villa.
    h, base = admin["h"], f"/projects/{villa}/boq"
    sec = (await client.post(f"{base}/sections", json={"name": "Structure"}, headers=h)).json()
    line = (await client.post(f"{base}/sections/{sec['id']}/lines", json={
        "work": "M20 in slab", "unit": "cum", "planned_quantity": "300", "client_rate": "6500"}, headers=h)).json()
    await client.put(f"/projects/{villa}/contract", json={"contract_value": "8500000", "new_client": {"name": "Mr. Thomas"}},
                     headers=h)
    activity = uuid.uuid4()
    async with test_engine.begin() as conn:
        unit_id = (await conn.execute(sa.text("SELECT id FROM units_of_measure WHERE code = 'cum'"))).scalar_one()
        await conn.execute(sa.text("INSERT INTO activities (id, organization_id, project_id, site_id, work_type, "
                                   "activity_date, source) VALUES (:id, :o, :p, :s, 'work', current_date, 'dashboard')"),
                           {"id": activity, "o": org, "p": villa, "s": villa_site})
        await conn.execute(sa.text("INSERT INTO activity_quantities (id, activity_id, unit_id, quantity, planned_item_id) "
                                   "VALUES (gen_random_uuid(), :a, :u, :q, :l)"),
                           {"a": activity, "u": unit_id, "q": Decimal("40"), "l": line["id"]})
    bill = await client.post(f"/projects/{villa}/ra-bills", json={}, headers=h)
    assert bill.status_code == 201, bill.text

    # Tasks: Arun's due today; the admin's overdue; one for nobody in particular.
    for who, due, title in ((arun, today, "Tie steel for grid B"), (admin, today - datetime.timedelta(days=2),
                                                                    "Call the steel supplier")):
        t = await client.post("/tasks", headers=admin["h"], json={
            "project_id": str(villa), "title": title, "due_date": due.isoformat(), "assignee_user_id": str(who["id"])})
        assert t.status_code in (200, 201), t.text

    return {"org": org, "villa": villa, "flats": flats, "villa_site": villa_site, "flats_site": flats_site,
            "admin": admin, "pm": pm, "arun": arun, "finance": finance, "today": today, "request_ref": request_ref,
            "bill_ref": bill.json()["ref"]}


async def _inbox(client, who: dict, **params) -> dict:
    r = await client.get("/approvals/waiting", headers=who["h"], params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _kinds(inbox: dict) -> list[str]:
    return [i["kind"] for i in inbox["items"]]


async def test_admin_sees_everything_urgent_first(client, world):
    w = world
    box = await _inbox(client, w["admin"])
    assert box["counts"] == {"site_report": 2, "material_request": 1, "subcontract_bill": 0, "measurement": 0, "ra_bill": 1,
                             "wage_sheet": 0, "size_request": 0, "task": 1}
    assert box["total"] == 5 and box["unavailable"] == []
    urgent = [i for i in box["items"] if i["urgent"]]
    assert box["items"][:len(urgent)] == urgent  # urgent first
    assert {i["kind"] for i in urgent} == {"site_report", "task"}  # yesterday's report, the overdue task
    report = next(i for i in box["items"] if i["kind"] == "site_report" and not i["urgent"])
    assert (report["site_id"], report["date"], report["count"]) == (str(w["villa_site"]), w["today"].isoformat(), 2)
    req = next(i for i in box["items"] if i["kind"] == "material_request")
    assert req["ref"] == w["request_ref"] and "Cement" in req["title"] and "Arun" in req["detail"]
    ra = next(i for i in box["items"] if i["kind"] == "ra_bill")
    assert ra["ref"] == w["bill_ref"] and "Mr. Thomas" in ra["title"]
    task = next(i for i in box["items"] if i["kind"] == "task")
    assert "Call the steel supplier" in task["title"] and task["urgent"]  # only the admin's own task


async def test_each_role_sees_only_what_it_may_act_on(client, world):
    w = world
    arun = await _inbox(client, w["arun"])  # site engineer at the villa
    assert sorted(_kinds(arun)) == ["site_report", "task"]
    assert all(i["project_id"] == str(w["villa"]) for i in arun["items"])  # never the flats' report
    assert "Tie steel" in next(i for i in arun["items"] if i["kind"] == "task")["title"]

    pm = await _inbox(client, w["pm"])  # project manager of the villa only
    assert sorted(_kinds(pm)) == ["material_request", "site_report"]
    assert all(i["project_id"] == str(w["villa"]) for i in pm["items"])

    finance = await _inbox(client, w["finance"])
    assert "ra_bill" in _kinds(finance) and "material_request" not in _kinds(finance)


async def test_another_company_sees_nothing(client, world, test_engine):
    rival = await _user(test_engine, await _org(test_engine, "Rival"), "admin", "Rival admin")
    box = await _inbox(client, rival)
    assert box["total"] == 0 and box["items"] == []


async def test_kind_filter_and_limit(client, world):
    box = await _inbox(client, world["admin"], kind="site_report,task", limit=1)
    assert set(box["counts"]) == {"site_report", "task"} and box["total"] == 3 and len(box["items"]) == 1


async def test_a_module_switched_off_takes_its_rows_away(test_engine, monkeypatch, world):
    app = _app(test_engine, monkeypatch, ["dpr", "finance"])  # no materials, no tasks
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        box = await _inbox(c, world["admin"])
    assert sorted(set(_kinds(box))) == ["ra_bill", "site_report"]
