"""PRC-22: material requests API on a real Postgres (run with `pytest -m integration`).

What a site asks for, what each line shows (stock here, ordered, to buy, stock elsewhere, rate), the duplicate
warning, the office's decisions and who may make them, and project/site scope.
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

_TABLES = (
    "material_request_lines", "material_requests", "notifications", "material_movements", "material_receipts",
    "material_usage", "material_invoice_attachments", "material_invoices", "materials_catalog",
    "material_categories", "vendors", "sites", "projects", "users", "organizations",
)


async def _wipe(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(sa.text("UPDATE material_usage SET reverses_movement_id = NULL"))
        await conn.execute(sa.text("UPDATE material_receipts SET reverses_movement_id = NULL"))
        for table in _TABLES:
            await conn.execute(sa.text(f"DELETE FROM {table}"))  # noqa: S608 -- fixed names


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    await _wipe(engine)
    yield engine
    # Leave nothing that would block another file's clean-up of materials or projects.
    await _wipe(engine)
    await engine.dispose()


@pytest.fixture
async def client(test_engine: AsyncEngine, monkeypatch):
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    app = create_app()

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as test_client:
        yield test_client


async def _exec(engine, sql: str, **params) -> None:
    async with engine.begin() as conn:
        await conn.execute(sa.text(sql), params)


async def _user(engine, org, role: str, name: str, projects: list[uuid.UUID] | None = None) -> dict:
    user_id = uuid.uuid4()
    policy = {"mode": "all_projects", "projects": []} if projects is None else {
        "mode": "custom_projects",
        "projects": [{"projectId": str(p), "siteAccess": {"mode": "all_sites", "siteIds": []}} for p in projects]}
    await _exec(engine, "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, "
                "access_policy, created_at, updated_at) VALUES (:id, :org, :email, 'hash', :name, :role, 'active', "
                "CAST(:policy AS jsonb), now(), now())", id=user_id, org=org, email=f"{uuid.uuid4().hex[:8]}@x.com",
                name=name, role=role, policy=json.dumps(policy))
    for project in projects or []:
        await _exec(engine, "INSERT INTO project_members (id, project_id, user_id) VALUES (:id, :p, :u)",
                    id=uuid.uuid4(), p=project, u=user_id)
    token = create_access_token(data={"sub": str(user_id), "org": str(org), "role": role})
    return {"id": user_id, "h": {"Authorization": f"Bearer {token}"}}


async def _project(engine, org, name: str) -> uuid.UUID:
    pid = uuid.uuid4()
    await _exec(engine, "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                "VALUES (:id, :org, :name, now(), now())", id=pid, org=org, name=name)
    return pid


async def _site(engine, org, project, name: str) -> uuid.UUID:
    sid = uuid.uuid4()
    await _exec(engine, "INSERT INTO sites (id, project_id, organization_id, name, status, created_at, updated_at) "
                "VALUES (:id, :p, :org, :name, 'active', now(), now())", id=sid, p=project, org=org, name=name)
    return sid


@pytest.fixture
async def world(test_engine, client):
    org = uuid.uuid4()
    await _exec(test_engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, "
                "updated_at) VALUES (:id, 'Builder', 'local', 'default', 'active', now(), now())", id=org)
    villa = await _project(test_engine, org, "Villa Kakkanad")
    flats = await _project(test_engine, org, "Edappally Apartments")
    block_a = await _site(test_engine, org, villa, "Block A")
    yard = await _site(test_engine, org, villa, "Yard")
    tower = await _site(test_engine, org, flats, "Tower B")
    admin = await _user(test_engine, org, "admin", "Meera")
    arun = await _user(test_engine, org, "site_engineer", "Arun", projects=[villa])
    ravi = await _user(test_engine, org, "site_engineer", "Ravi", projects=[flats])
    units = {u["code"]: u["id"] for u in (await client.get("/materials/units-of-measure", headers=admin["h"])).json()["items"]}
    cement = (await client.post("/materials", json={"name": "Cement OPC 53", "default_unit_id": units["bags"]},
                                headers=admin["h"])).json()["id"]
    tmt = (await client.post("/materials", json={"name": "TMT bar 12 mm", "default_unit_id": units["kg"]},
                             headers=admin["h"])).json()["id"]
    return {"org": org, "villa": villa, "flats": flats, "block_a": block_a, "yard": yard, "tower": tower,
            "admin": admin, "arun": arun, "ravi": ravi, "units": units, "cement": cement, "tmt": tmt}


async def _deliver(client, w, site, project, material, unit, qty: str, rate: str | None = None) -> None:
    body = {"project_id": str(project), "site_id": str(site), "material_id": material, "unit_id": unit,
            "quantity": qty, "movement_reason": "RECEIVED", "occurred_date": str(datetime.date.today())}
    if rate:
        body["unit_cost"] = rate
    resp = await client.post("/materials/inflows", json=body, headers=w["admin"]["h"])
    assert resp.status_code == 201, resp.text


def _ask(w, material, qty: str, unit: str = "bags", *, site="block_a", project="villa", **extra) -> dict:
    return {"project_id": str(w[project]), "site_id": str(w[site]),
            "lines": [{"material_id": material, "quantity": qty, "unit_id": w["units"][unit]}], **extra}


async def test_a_request_shows_what_is_here_and_what_to_buy(client, world):
    w = world
    await _deliver(client, w, w["block_a"], w["villa"], w["cement"], w["units"]["bags"], "40", rate="400")
    await _deliver(client, w, w["yard"], w["villa"], w["cement"], w["units"]["bags"], "30")
    tomorrow = str(datetime.date.today() + datetime.timedelta(days=1))
    resp = await client.post("/procurement/requests", json=_ask(w, w["cement"], "200", needed_by=tomorrow,
                                                              purpose="First-floor slab"), headers=w["arun"]["h"])
    assert resp.status_code == 201, resp.text
    item = resp.json()
    assert item["ref"] == "REQ-0001" and item["status"] == "waiting" and item["urgency"] == "soon"
    assert item["requested_by_name"] == "Arun" and item["source"] == "dashboard"
    line = item["lines"][0]
    assert (line["quantity"], line["at_site"], line["on_order"], line["to_buy"]) == ("200", "40", "0", "160")
    assert [(e["site_name"], e["quantity"]) for e in line["elsewhere"]] == [("Yard", "30")]
    # An engineer does not see the company's rates (SEC-01); the office does.
    assert line["last_rate"] is None
    assert item["may_act"] is False and item["may_cancel"] is True
    as_admin = (await client.get(f"/procurement/requests/{item['id']}", headers=w["admin"]["h"])).json()
    assert as_admin["lines"][0]["last_rate"]["unit_cost"] == "400"
    assert as_admin["may_act"] is True

    listing = (await client.get("/procurement/requests", headers=w["admin"]["h"])).json()
    assert [i["ref"] for i in listing["items"]] == ["REQ-0001"]
    assert listing["counts"]["waiting"] == 1 and listing["counts"]["soon"] == 1


async def test_same_material_in_the_project_is_flagged_before_saving(client, world):
    w = world
    first = await client.post("/procurement/requests", json=_ask(w, w["cement"], "150"), headers=w["admin"]["h"])
    assert first.status_code == 201
    again = await client.post("/procurement/requests", json=_ask(w, w["cement"], "200", site="yard"),
                              headers=w["arun"]["h"])
    assert again.status_code == 409
    detail = again.json()["detail"]
    assert detail["code"] == "possible_duplicate" and detail["duplicates"][0]["ref"] == "REQ-0001"
    assert "Meera already asked for 150 bags Cement OPC 53" in detail["message"]
    # Nothing was saved by the refused one.
    assert (await client.get("/procurement/requests", headers=w["admin"]["h"])).json()["counts"]["all"] == 1

    kept = await client.post("/procurement/requests", json=_ask(w, w["cement"], "200", site="yard",
                                                              confirm_duplicate=True), headers=w["arun"]["h"])
    assert kept.status_code == 201
    assert kept.json()["raised_over_duplicate"] is True
    assert [d["ref"] for d in kept.json()["duplicates"]] == ["REQ-0001"]
    # Guard: another project's cement is not a duplicate.
    other = await client.post("/procurement/requests", json=_ask(w, w["cement"], "10", site="tower", project="flats"),
                              headers=w["admin"]["h"])
    assert other.status_code == 201 and other.json()["duplicates"] == []


async def test_office_decides_and_the_engineer_is_told(client, world, test_engine):
    w = world
    rid = (await client.post("/procurement/requests", json=_ask(w, w["cement"], "100"), headers=w["arun"]["h"])).json()["id"]
    url = f"/procurement/requests/{rid}/decide"
    assert (await client.post(url, json={"action": "ordered"}, headers=w["arun"]["h"])).status_code == 403
    assert (await client.post(url, json={"action": "rejected"}, headers=w["admin"]["h"])).status_code == 422
    assert (await client.post(url, json={"action": "done"}, headers=w["admin"]["h"])).status_code == 409

    ordered = await client.post(url, json={"action": "ordered", "note": "Malabar Hardware"}, headers=w["admin"]["h"])
    assert ordered.status_code == 200, ordered.text
    assert ordered.json()["status"] == "ordered" and ordered.json()["decided_by_name"] == "Meera"
    # Once ordered, the request itself is on its way: nothing left to buy for it.
    assert (ordered.json()["lines"][0]["on_order"], ordered.json()["lines"][0]["to_buy"]) == ("100", "0")
    assert (await client.post(f"/procurement/requests/{rid}/cancel", headers=w["arun"]["h"])).status_code == 409

    # The new request for the same site now counts it as already ordered.
    second = (await client.post("/procurement/requests", json=_ask(w, w["cement"], "150", confirm_duplicate=True),
                                headers=w["arun"]["h"])).json()
    assert (second["lines"][0]["on_order"], second["lines"][0]["to_buy"]) == ("100", "50")

    done = await client.post(url, json={"action": "done"}, headers=w["admin"]["h"])
    assert done.json()["status"] == "done" and done.json()["urgency"] == "closed"
    async with test_engine.begin() as conn:
        notes = (await conn.execute(sa.text(
            "SELECT recipient_user_id, payload->>'message' FROM notifications WHERE rule_key = "
            "'material_request_update' ORDER BY created_at"))).all()
    assert [n[0] for n in notes] == [w["arun"]["id"], w["arun"]["id"]]
    assert notes[0][1].startswith("🛒 Ordered by Meera: 100 bags Cement OPC 53 (Malabar Hardware)")
    assert notes[1][1].startswith("✅ Marked received")


async def test_engineer_cancels_own_waiting_request_but_not_someone_elses(client, world):
    w = world
    mine = (await client.post("/procurement/requests", json=_ask(w, w["cement"], "5"), headers=w["arun"]["h"])).json()
    theirs = (await client.post("/procurement/requests", json=_ask(w, w["tmt"], "50", unit="kg"),
                                headers=w["admin"]["h"])).json()
    assert (await client.post(f"/procurement/requests/{theirs['id']}/cancel", headers=w["arun"]["h"])).status_code == 403
    cancelled = await client.post(f"/procurement/requests/{mine['id']}/cancel", headers=w["arun"]["h"])
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"


async def test_scope_an_engineer_sees_and_asks_only_in_their_projects(client, world):
    w = world
    villa = (await client.post("/procurement/requests", json=_ask(w, w["cement"], "5"), headers=w["arun"]["h"])).json()
    refused = await client.post("/procurement/requests", json=_ask(w, w["cement"], "5", site="tower", project="flats"),
                                headers=w["arun"]["h"])
    assert refused.status_code == 403
    ravi_list = (await client.get("/procurement/requests?status=all", headers=w["ravi"]["h"])).json()
    assert ravi_list["items"] == []
    assert (await client.get(f"/procurement/requests/{villa['id']}", headers=w["ravi"]["h"])).status_code == 404
    assert (await client.post(f"/procurement/requests/{villa['id']}/cancel",
                              headers=w["ravi"]["h"])).status_code == 404


async def test_other_units_are_converted_and_filters_work(client, world):
    w = world
    resp = await client.post("/procurement/requests", json=_ask(w, w["tmt"], "1.2", unit="tons"),
                             headers=w["admin"]["h"])
    assert resp.status_code == 201, resp.text
    line = resp.json()["lines"][0]
    assert (line["quantity"], line["unit"], line["said"]) == ("1200", "kg", "1.2 Tons")
    mixed = await client.post("/procurement/requests", json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]),
        "lines": [{"material_id": w["cement"], "quantity": "1", "unit_id": w["units"]["bags"]},
                  {"material_id": w["cement"], "quantity": "2", "unit_id": w["units"]["bags"]}]},
        headers=w["admin"]["h"])
    assert mixed.status_code == 422
    await client.post("/procurement/requests", json=_ask(w, w["cement"], "3"), headers=w["arun"]["h"])
    by_arun = (await client.get(f"/procurement/requests?requested_by={w['arun']['id']}",
                                headers=w["admin"]["h"])).json()["items"]
    assert [i["requested_by_name"] for i in by_arun] == ["Arun"]
    mine = (await client.get("/procurement/requests?mine=true", headers=w["arun"]["h"])).json()["items"]
    assert len(mine) == 1
    assert (await client.get("/procurement/requests?status=bogus", headers=w["admin"]["h"])).status_code == 422


async def test_a_requested_material_cannot_be_deleted(client, world):
    w = world
    await client.post("/procurement/requests", json=_ask(w, w["cement"], "3"), headers=w["admin"]["h"])
    resp = await client.delete(f"/materials/{w['cement']}", headers=w["admin"]["h"])
    assert resp.status_code == 409


async def test_one_item_at_the_top_level_is_the_whatsapp_form(client, world):
    """The assistant's write: one material per request, as flat fields, checked and converted like lines."""
    w = world
    body = {"project_id": str(w["villa"]), "site_id": str(w["block_a"]), "material_id": w["tmt"], "quantity": "0.5",
            "unit_id": w["units"]["tons"], "source": "whatsapp", "needed_by": str(datetime.date.today())}
    resp = await client.post("/procurement/requests", json=body, headers=w["arun"]["h"])
    assert resp.status_code == 201, resp.text
    item = resp.json()
    assert item["source"] == "whatsapp" and item["urgency"] == "soon"
    assert (item["lines"][0]["quantity"], item["lines"][0]["unit"]) == ("500", "kg")
    both = {**body, "lines": [{"material_id": w["cement"], "quantity": "1", "unit_id": w["units"]["bags"]}]}
    assert (await client.post("/procurement/requests", json=both, headers=w["arun"]["h"])).status_code == 422
    nothing = {"project_id": str(w["villa"]), "site_id": str(w["block_a"])}
    assert (await client.post("/procurement/requests", json=nothing, headers=w["arun"]["h"])).status_code == 422
