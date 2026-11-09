"""Contract tests for the company activity log (ADM-01, ADM-02) and handing over open work (ADM-03), on Postgres.

Requires a live Postgres reachable via Settings().postgres.dsn() -- run with `pytest -m integration`.

Guards: a change is recorded with its person, action and record; a refused change, a read and a call without a login
are not; no request body is ever stored; only the owner and admins read the log, each company only its own. Handing
over moves only what the new person can reach, through the tasks module's own reassign (its history says so).
"""

from __future__ import annotations

import datetime
import json
import uuid

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

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


async def _exec(engine, sql: str, **params):
    async with engine.begin() as conn:
        return await conn.execute(sa.text(sql), params)


async def _org(engine, name: str) -> uuid.UUID:
    org = uuid.uuid4()
    await _exec(engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, "
                        "updated_at) VALUES (:id, :n, 'local', 'default', 'active', now(), now())", id=org, n=name)
    return org


async def _user(engine, org, role: str, name: str, projects: list | None = None, status: str = "active") -> dict:
    user_id = uuid.uuid4()
    policy = {"mode": "selected_projects", "projects": [str(p) for p in projects]} if projects \
        else {"mode": "all_projects", "projects": []}
    await _exec(engine, "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, "
                        "access_policy, whatsapp_number, created_at, updated_at) VALUES (:id, :org, :email, 'hash', "
                        ":name, :role, :st, CAST(:policy AS jsonb), :wa, now(), now())",
                id=user_id, org=org, email=f"{uuid.uuid4().hex[:8]}@example.com", role=role, name=name, st=status,
                policy=json.dumps(policy), wa=f"+9190{uuid.uuid4().int % 10**8:08d}")
    for p in projects or []:
        await _exec(engine, "INSERT INTO project_members (id, project_id, user_id, role, site_access_mode) "
                            "VALUES (gen_random_uuid(), :p, :u, :r, 'all_sites')", p=p, u=user_id, r=role)
    token = create_access_token(data={"sub": str(user_id), "org": str(org), "role": role})
    return {"id": user_id, "name": name, "h": {"Authorization": f"Bearer {token}"}}


async def _project(engine, org, name: str) -> uuid.UUID:
    project = uuid.uuid4()
    await _exec(engine, "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                        "VALUES (:id, :org, :n, now(), now())", id=project, org=org, n=name)
    await _exec(engine, "INSERT INTO sites (id, project_id, organization_id, name, status, created_at, updated_at) "
                        "VALUES (gen_random_uuid(), :p, :org, :n, 'active', now(), now())", p=project, org=org,
                n=f"{name} site")
    return project


@pytest.fixture
async def co(test_engine):
    org = await _org(test_engine, "Log Builders")
    villa = await _project(test_engine, org, "Villa Kakkanad")
    flats = await _project(test_engine, org, "Edappally Flats")
    return {"org": org, "villa": villa, "flats": flats,
            "admin": await _user(test_engine, org, "admin", "Meera"),
            "pm": await _user(test_engine, org, "project_manager", "Joseph", projects=[villa]),
            "arun": await _user(test_engine, org, "site_engineer", "Arun", projects=[villa, flats])}


async def _task(client, co, title: str, project="villa", who="arun", notes=None) -> dict:
    body = {"project_id": str(co[project]), "title": title, "assignee_user_id": str(co[who]["id"])}
    if notes:
        body["notes"] = notes
    r = await client.post("/tasks", headers=co["admin"]["h"], json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


async def _log(client, who: dict, **params) -> dict:
    r = await client.get("/activity", headers=who["h"], params=params)
    assert r.status_code == 200, r.text
    return r.json()


# -- ADM-01 / ADM-02: the activity log ---------------------------------------------------------------------------

async def test_a_change_is_recorded_with_who_what_and_which_record(client, co):
    task = await _task(client, co, "Tie steel for grid B")
    r = await client.post(f"/tasks/{task['id']}/status", headers=co["admin"]["h"], json={"status": "doing"})
    assert r.status_code == 200, r.text
    items = (await _log(client, co["admin"]))["items"]
    assert [(i["action"], i["record_kind"], i["record_id"], i["record_label"]) for i in items[:2]] == [
        ("Move task", "task", task["id"], task["ref"]),
        ("Create task", "task", task["id"], task["ref"])]
    assert items[0]["actor_name"] == "Meera" and items[0]["source"] == "web" and items[0]["route"] == "/tasks/{task_id}/status"


async def test_refused_changes_reads_and_calls_without_a_login_are_not_recorded(client, co):
    await client.get("/tasks", headers=co["admin"]["h"])  # a read
    bad = await client.post("/tasks", headers=co["admin"]["h"], json={"project_id": str(co["villa"])})  # no title
    assert bad.status_code == 422
    refused = await client.post("/tasks/" + str(uuid.uuid4()) + "/status", headers=co["arun"]["h"], json={"status": "done"})
    assert refused.status_code in (403, 404)
    assert (await client.post("/tasks", json={"project_id": str(co["villa"]), "title": "x"})).status_code == 401
    assert (await _log(client, co["admin"]))["items"] == []


async def test_a_preview_is_not_a_change(client, co):
    h = co["admin"]["h"]
    act = (await client.post(f"/projects/{co['villa']}/schedule/activities", headers=h,
                             json={"name": "Handover", "start": "2027-04-08", "milestone": True})).json()["focus"]
    before = len((await _log(client, co["admin"]))["items"])
    r = await client.patch(f"/projects/{co['villa']}/schedule/activities/{act}", headers=h,
                           json={"start": "2027-04-20", "preview": True})
    assert r.status_code == 200 and r.json()["saved"] is False, r.text
    assert len((await _log(client, co["admin"]))["items"]) == before
    await client.patch(f"/projects/{co['villa']}/schedule/activities/{act}", headers=h, json={"start": "2027-04-20"})
    assert (await _log(client, co["admin"]))["items"][0]["action"] == "Update activity"


async def test_no_request_body_is_stored(client, co, test_engine):
    await _task(client, co, "Call the supplier", notes="Rate 410 a bag, number 98470 12345")
    async with test_engine.begin() as conn:
        rows = (await conn.execute(sa.text("SELECT to_jsonb(a) FROM activity_log a WHERE organization_id = :o"),
                                   {"o": co["org"]})).scalars().all()
    assert len(rows) == 1
    stored = json.dumps(rows[0])
    assert "98470" not in stored and "410" not in stored and "Rate" not in stored


async def test_only_the_owner_and_admins_read_it_and_only_their_company(client, co, test_engine):
    await _task(client, co, "Something")
    for who in ("pm", "arun"):
        assert (await client.get("/activity", headers=co[who]["h"])).status_code == 403
    rival = await _user(test_engine, await _org(test_engine, "Rival"), "admin", "Rival admin")
    assert (await _log(client, rival))["items"] == []
    assert len((await _log(client, co["admin"]))["items"]) == 1


async def test_filters_and_pages(client, co):
    for n in range(3):
        await _task(client, co, f"Task {n}")
    await client.post(f"/projects/{co['villa']}/client-links", headers=co["admin"]["h"], json={"label": "Mr. Thomas"})
    everything = await _log(client, co["admin"])
    assert len(everything["items"]) == 4 and [p["name"] for p in everything["people"]] == ["Meera"]
    assert {i["record_kind"] for i in (await _log(client, co["admin"], kind="task"))["items"]} == {"task"}
    links = (await _log(client, co["admin"], q="client link"))["items"]
    assert [i["record_kind"] for i in links] == ["client_link"] and links[0]["record_label"] == "Mr. Thomas"
    page1 = await _log(client, co["admin"], limit=3)
    page2 = await _log(client, co["admin"], limit=3, before=page1["next"])
    assert len(page1["items"]) == 3 and len(page2["items"]) == 1 and page2["next"] is None
    assert not {i["id"] for i in page1["items"]} & {i["id"] for i in page2["items"]}
    today = datetime.date.today()
    assert (await _log(client, co["admin"], date_from=(today + datetime.timedelta(days=2)).isoformat()))["items"] == []
    assert (await _log(client, co["admin"], user_id=str(co["pm"]["id"])))["items"] == []
    assert (await _log(client, co["admin"], source="whatsapp"))["items"] == []


# -- ADM-03: hand over open work -----------------------------------------------------------------------------------

async def test_hand_over_moves_what_the_new_person_reaches(client, co, test_engine):
    villa_task = await _task(client, co, "Tie steel for grid B")
    flats_task = await _task(client, co, "Check tower crane", project="flats")
    done = await _task(client, co, "Old one")
    await client.post(f"/tasks/{done['id']}/status", headers=co["admin"]["h"], json={"status": "done"})
    section = (await client.post(f"/projects/{co['villa']}/boq/sections", headers=co["admin"]["h"],
                                 json={"name": "Structure"})).json()
    await _exec(test_engine, "UPDATE work_packages SET assigned_user_id = :u WHERE id = :w",
                u=co["arun"]["id"], w=section["id"])
    url = f"/users/{co['arun']['id']}/handover"

    preview = await client.post(url, headers=co["admin"]["h"], json={"to_user_id": str(co["pm"]["id"]), "preview": True})
    assert preview.status_code == 200, preview.text
    p = preview.json()
    assert [t["title"] for t in p["tasks"]] == ["Tie steel for grid B"] and p["moved"] is None
    assert [t["title"] for t in p["left"]["tasks"]] == ["Check tower crane"]  # Joseph is not on the flats
    assert [a["name"] for a in p["activities"]] == ["Structure"]
    tasks_now = (await client.get(f"/tasks/{villa_task['id']}", headers=co["admin"]["h"])).json()
    assert tasks_now["assignee_user_id"] == str(co["arun"]["id"])  # a preview saves nothing

    r = await client.post(url, headers=co["admin"]["h"], json={"to_user_id": str(co["pm"]["id"])})
    assert r.status_code == 200, r.text
    assert r.json()["moved"] == {"tasks": 1, "activities": 1}
    moved = (await client.get(f"/tasks/{villa_task['id']}", headers=co["admin"]["h"])).json()
    assert moved["assignee_user_id"] == str(co["pm"]["id"])
    history = json.dumps(moved.get("events") or moved.get("history") or [])
    assert str(co["pm"]["id"]) in history  # the task's own history records the reassign
    stayed = (await client.get(f"/tasks/{flats_task['id']}", headers=co["admin"]["h"])).json()
    assert stayed["assignee_user_id"] == str(co["arun"]["id"])
    async with test_engine.begin() as conn:
        owner = (await conn.execute(sa.text("SELECT assigned_user_id FROM work_packages WHERE id = :w"),
                                    {"w": section["id"]})).scalar()
    assert owner == co["pm"]["id"]
    log = (await _log(client, co["admin"], kind="user"))["items"]
    assert [i["action"] for i in log] == ["Hand over work"] and log[0]["record_id"] == str(co["arun"]["id"])


async def test_hand_over_refusals(client, co, test_engine):
    url = f"/users/{co['arun']['id']}/handover"
    gone = await _user(test_engine, co["org"], "site_engineer", "Left", status="inactive")
    rival = await _user(test_engine, await _org(test_engine, "Rival"), "admin", "Rival")
    cases = [(co["pm"]["h"], co["admin"]["id"], 403), (co["admin"]["h"], co["arun"]["id"], 422),
             (co["admin"]["h"], gone["id"], 422), (co["admin"]["h"], rival["id"], 404)]
    for headers, to, code in cases:
        r = await client.post(url, headers=headers, json={"to_user_id": str(to)})
        assert r.status_code == code, (to, r.text)
