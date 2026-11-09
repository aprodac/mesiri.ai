"""Contract tests for tasks (TSK-01): the `tasks` module's API on Postgres.

Requires a live Postgres reachable via Settings().postgres.dsn() -- run with `pytest -m integration`.
Fixtures mirror test_schedule_contract.py.
"""

from __future__ import annotations

import asyncio
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
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.objectstorage.fake import FakeObjectStorage
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration
D = datetime.timedelta(days=1)


class _Store(FakeObjectStorage):
    async def generate_presigned_url(self, key, *, expires_in_seconds=900, method="GET"):
        return f"https://files.test/{key}"


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


def _app(test_engine: AsyncEngine, monkeypatch, modules=None):
    if modules is None:
        monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    else:
        async def enabled(request, organization_id):
            return modules

        monkeypatch.setattr("mesiri.domains.shared.modules.read_enabled_modules", enabled)
    app = create_app()

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    app.dependency_overrides[get_object_storage] = _Store
    return app


@pytest.fixture
async def client(test_engine: AsyncEngine, monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=_app(test_engine, monkeypatch)), base_url="http://testserver") as c:
        yield c


async def _exec(engine, sql: str, **params):
    async with engine.begin() as conn:
        return await conn.execute(sa.text(sql), params)


async def _org(engine) -> uuid.UUID:
    org_id = uuid.uuid4()
    await _exec(engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
                        "VALUES (:id, 'Tasks Org', 'local', 'default', 'active', now(), now())", id=org_id)
    return org_id


async def _user(engine, org_id, role: str, name: str, policy: dict | None = None) -> tuple[uuid.UUID, dict]:
    user_id = uuid.uuid4()
    await _exec(engine, "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, "
                        "access_policy, whatsapp_number, created_at, updated_at) VALUES (:id, :org, :email, 'hash', "
                        ":name, :role, 'active', CAST(:policy AS jsonb), :wa, now(), now())",
                id=user_id, org=org_id, email=f"{uuid.uuid4().hex[:8]}@example.com", role=role, name=name,
                policy=json.dumps(policy or {"mode": "all_projects", "projects": []}),
                wa=f"+9190{uuid.uuid4().int % 10**8:08d}")
    token = create_access_token(data={"sub": str(user_id), "org": str(org_id), "role": role})
    return user_id, {"Authorization": f"Bearer {token}"}


async def _member(engine, project_id, user_id, role: str, site_id=None) -> None:
    await _exec(engine, "INSERT INTO project_members (id, project_id, user_id, role, site_access_mode) "
                        "VALUES (gen_random_uuid(), :p, :u, :r, :mode)",
                p=project_id, u=user_id, r=role, mode="custom_sites" if site_id else "all_sites")
    if site_id:
        await _exec(engine, "INSERT INTO site_members (id, site_id, user_id) VALUES (gen_random_uuid(), :s, :u)",
                    s=site_id, u=user_id)


async def _site(engine, org_id, project_id, name: str) -> uuid.UUID:
    site_id = uuid.uuid4()
    await _exec(engine, "INSERT INTO sites (id, project_id, organization_id, name, status, created_at, updated_at) "
                        "VALUES (:id, :p, :org, :name, 'active', now(), now())", id=site_id, p=project_id, org=org_id,
                name=name)
    return site_id


@pytest.fixture
async def co(test_engine):
    """A company with one project and two sites; an admin, a PM, an engineer (Arun) and finance on it."""
    org = await _org(test_engine)
    project = uuid.uuid4()
    await _exec(test_engine, "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                             "VALUES (:id, :org, 'Villa Kakkanad', now(), now())", id=project, org=org)
    main = await _site(test_engine, org, project, "Main building")
    annex = await _site(test_engine, org, project, "Annex")
    admin, admin_h = await _user(test_engine, org, "ADMIN", "Owner Admin")
    pm, pm_h = await _user(test_engine, org, "PROJECT_MANAGER", "Priya PM")
    arun, arun_h = await _user(test_engine, org, "SITE_ENGINEER", "Arun Kumar")
    fin, fin_h = await _user(test_engine, org, "FINANCE", "Fathima Finance")
    for uid, role in ((pm, "PROJECT_MANAGER"), (arun, "SITE_ENGINEER"), (fin, "FINANCE")):
        await _member(test_engine, project, uid, role)
    return {"org": org, "project": project, "main": main, "annex": annex, "admin": admin_h, "pm": pm_h,
            "pm_id": pm, "arun": arun_h, "arun_id": arun, "fin": fin_h}


async def _give(client, co, headers=None, **body):
    resp = await client.post("/tasks", json={"project_id": str(co["project"]), "title": "Tie steel for grid B",
                                             **body}, headers=headers or co["pm"])
    return resp


async def test_give_a_task_in_words_and_find_it(client, co):
    due = (datetime.date.today() + 3 * D).isoformat()
    resp = await _give(client, co, assignee="arun", site="main", due_date=due, priority="high")
    assert resp.status_code == 201, resp.text
    task = resp.json()
    assert task["ref"] == "T-1" and task["status"] == "open"
    assert task["assignee_user_id"] == str(co["arun_id"]) and task["assigned_to"] == "Arun Kumar"
    assert task["site_name"] == "Main building" and task["priority"] == "high"

    mine = (await client.get("/tasks", params={"assignee": "me"}, headers=co["arun"])).json()["items"]
    assert [t["ref"] for t in mine] == ["T-1"]
    assert (await client.get("/tasks/summary", headers=co["arun"])).json() == {
        "mine_open": 1, "mine_overdue": 0, "overdue": 0}


async def test_numbers_count_per_project_and_never_clash(client, co):
    results = await asyncio.gather(*[_give(client, co, title=f"Job {i}") for i in range(5)])
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    assert sorted(r.json()["number"] for r in results) == [1, 2, 3, 4, 5]


async def test_words_that_fit_several_or_none_return_the_choices(client, co, test_engine):
    await _user(test_engine, co["org"], "ADMIN", "Arun Das")  # org-wide admin: on every project
    several = await _give(client, co, assignee="arun")
    assert several.status_code == 422
    assert set(several.json()["detail"]["options"]) == {"Arun Kumar", "Arun Das"}
    none = await _give(client, co, site="Block Z")
    assert none.status_code == 422 and "Annex" in none.json()["detail"]["options"]


async def test_finance_cannot_give_tasks_and_links_must_be_of_the_project(client, co, test_engine):
    assert (await _give(client, co, headers=co["fin"])).status_code == 403
    other_org = await _org(test_engine)
    stranger, _ = await _user(test_engine, other_org, "SITE_ENGINEER", "Stranger")
    assert (await _give(client, co, assignee_user_id=str(stranger))).status_code == 422
    assert (await _give(client, co, site_id=str(uuid.uuid4()))).status_code == 422
    assert (await _give(client, co, expected_quantity="20")).status_code == 422  # no BOQ line


async def test_status_moves_and_history(client, co):
    task = (await _give(client, co, assignee="arun")).json()
    tid = task["id"]
    blocked = await client.post(f"/tasks/{tid}/status", json={"status": "blocked"}, headers=co["arun"])
    assert blocked.status_code == 409 and "blocking" in blocked.json()["detail"]
    assert (await client.post(f"/tasks/{tid}/status", json={"status": "blocked", "note": "no shuttering"},
                              headers=co["arun"])).json()["blocked_reason"] == "no shuttering"
    assert (await client.post(f"/tasks/{tid}/status", json={"status": "doing"}, headers=co["arun"])).status_code == 200
    done = (await client.post(f"/tasks/{tid}/status", json={"status": "done"}, headers=co["arun"])).json()
    assert done["status"] == "done" and done["done_at"] and done["blocked_reason"] is None
    again = await client.post(f"/tasks/{tid}/status", json={"status": "doing"}, headers=co["arun"])
    assert again.status_code == 409  # done -> only reopen
    # the doer never cancels; the giver does
    reopened = await client.post(f"/tasks/{tid}/status", json={"status": "open"}, headers=co["arun"])
    assert reopened.json()["done_at"] is None
    assert (await client.post(f"/tasks/{tid}/status", json={"status": "cancelled"},
                              headers=co["arun"])).status_code == 403
    assert (await client.post(f"/tasks/{tid}/status", json={"status": "cancelled"},
                              headers=co["pm"])).status_code == 200

    one = (await client.get(f"/tasks/{tid}", headers=co["pm"])).json()
    moves = [(e["from_status"], e["to_status"]) for e in one["history"] if e["kind"] == "status"]
    assert moves == [("open", "blocked"), ("blocked", "doing"), ("doing", "done"), ("done", "open"),
                     ("open", "cancelled")]
    assert one["history"][0]["kind"] == "created" and one["may"]["cancel"] is True


async def test_only_the_giver_or_a_manager_changes_details(client, co):
    tid = (await _give(client, co, assignee="arun")).json()["id"]
    assert (await client.patch(f"/tasks/{tid}", json={"title": "x"}, headers=co["arun"])).status_code == 403
    changed = await client.patch(f"/tasks/{tid}", json={"due_date": "2026-12-01", "notes": "use 12 mm"},
                                 headers=co["pm"])
    assert changed.status_code == 200 and changed.json()["due_date"] == "2026-12-01"
    history = (await client.get(f"/tasks/{tid}", headers=co["pm"])).json()["history"]
    assert history[-1]["kind"] == "changed" and history[-1]["changes"]["due_date"] == [None, "2026-12-01"]
    assert (await client.patch(f"/tasks/{tid}", json={"title": None}, headers=co["pm"])).status_code == 422


async def test_overdue_and_due_filters(client, co):
    late = (await _give(client, co, assignee="arun", due_date=(datetime.date.today() - 2 * D).isoformat())).json()
    await _give(client, co, assignee="arun", due_date=(datetime.date.today() + 20 * D).isoformat())
    overdue = (await client.get("/tasks", params={"due": "overdue", "project_id": str(co["project"])},
                                headers=co["pm"])).json()["items"]
    assert [t["id"] for t in overdue] == [late["id"]] and overdue[0]["days_late"] >= 1
    summary = (await client.get("/tasks/summary", headers=co["arun"])).json()
    assert summary["mine_open"] == 2 and summary["mine_overdue"] == 1


async def test_a_site_limited_engineer_sees_only_their_sites_and_their_own(client, co, test_engine):
    biju, biju_h = await _user(test_engine, co["org"], "SITE_ENGINEER", "Biju", policy={
        "mode": "custom_projects", "projects": [{"projectId": str(co["project"]),
                                                 "siteAccess": {"mode": "custom_sites", "siteIds": [str(co["main"])]}}]})
    await _member(test_engine, co["project"], biju, "SITE_ENGINEER", site_id=co["main"])
    on_main = (await _give(client, co, title="Main job", site_id=str(co["main"]))).json()
    on_annex = (await _give(client, co, title="Annex job", site_id=str(co["annex"]))).json()
    his_on_annex = (await _give(client, co, title="Biju at annex", site_id=str(co["annex"]),
                                assignee_user_id=str(biju))).json()
    seen = {t["id"] for t in (await client.get("/tasks", headers=biju_h)).json()["items"]}
    assert seen == {on_main["id"], his_on_annex["id"]}
    assert (await client.get(f"/tasks/{on_annex['id']}", headers=biju_h)).status_code == 403
    assert (await _give(client, co, headers=biju_h, site_id=str(co["annex"]))).status_code == 403


async def test_another_company_never_sees_a_task(client, co, test_engine):
    tid = (await _give(client, co)).json()["id"]
    other = await _org(test_engine)
    _, other_h = await _user(test_engine, other, "ADMIN", "Other admin")
    assert (await client.get(f"/tasks/{tid}", headers=other_h)).status_code == 404
    assert (await client.get("/tasks", headers=other_h)).json()["items"] == []


async def _inbound_photo(test_engine, org_id, key: str) -> None:
    await _exec(test_engine,
                "INSERT INTO inbound_messages (id, correlation_id, sender_wa_id, message_type, raw_payload, "
                "normalized_message, dedup_key, raw_payload_captured, processing_status, organization_id, "
                "received_at, media_object_key) VALUES (:id, :c, '15555550199', 'image', '{}', '{}', :d, true, "
                "'completed', :org, now(), :key)",
                id=uuid.uuid4(), c=f"c-{uuid.uuid4().hex}", d=f"d-{uuid.uuid4().hex}", org=org_id, key=key)


async def test_done_with_a_whatsapp_photo_only_our_own(client, co, test_engine):
    tid = (await _give(client, co, assignee="arun")).json()["id"]
    ours, theirs = f"wa/{uuid.uuid4().hex}.jpg", f"wa/{uuid.uuid4().hex}.jpg"
    await _inbound_photo(test_engine, co["org"], ours)
    await _inbound_photo(test_engine, await _org(test_engine), theirs)
    refused = await client.post(f"/tasks/{tid}/status", json={"status": "done", "media_object_key": theirs,
                                                               "source": "whatsapp"}, headers=co["arun"])
    assert refused.status_code == 404
    done = await client.post(f"/tasks/{tid}/status", json={"status": "done", "media_object_key": ours,
                                                            "source": "whatsapp"}, headers=co["arun"])
    assert done.status_code == 200
    comment = await client.post(f"/tasks/{tid}/comments", json={"text": "cover blocks checked"}, headers=co["pm"])
    assert comment.status_code == 201
    history = (await client.get(f"/tasks/{tid}", headers=co["pm"])).json()["history"]
    photo = [e for e in history if e["kind"] == "status"][-1]
    assert photo["photo_url"] == f"https://files.test/{ours}" and photo["source"] == "whatsapp"
    assert history[-1]["text"] == "cover blocks checked"
    assert (await client.post(f"/tasks/{tid}/comments", json={}, headers=co["pm"])).status_code == 422


async def test_switched_off_the_module_refuses(test_engine, co, monkeypatch):
    app = _app(test_engine, monkeypatch, modules=["dpr", "finance"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as off:
        resp = await off.get("/tasks", headers=co["pm"])
        assert resp.status_code == 403 and resp.json()["detail"]["code"] == "MODULE_DISABLED"
        assert (await _give(off, co)).status_code == 403
