"""PRC-06/07/08: purchase orders API on a real Postgres (run with `pytest -m integration`).

Placing an order (supplier in words or from the list), the duplicate warning, the request it came from following it
(ordered, then received, the engineer told each time), receiving in parts (stock goes up, from the order's supplier
at its rate), cancel and close rules, who may do what, rates hidden from site roles, a delivery taken back no longer
counting, and a delivery refused on another site's order line.
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

from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import create_access_token
from mesiri.http.app import create_app
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration

_TABLES = (
    "purchase_order_lines", "purchase_orders", "material_request_lines", "material_requests", "notifications", "material_movements", "material_receipts",
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



def _order(w, material, qty: str, unit: str = "bags", *, site="block_a", project="villa", rate=None, **extra) -> dict:
    line = {"material_id": material, "quantity": qty, "unit_id": w["units"][unit]}
    if rate is not None:
        line["rate"] = rate
    return {"project_id": str(w[project]), "site_id": str(w[site]), "supplier": "Malabar Hardware",
            "lines": [line], **extra}


async def _stock(client, w, site="block_a", material="cement") -> str:
    rows = (await client.get("/materials/inventory", params={"site_id": str(w[site]), "material_id": w[material]},
                             headers=w["admin"]["h"])).json()
    return f"{Decimal(rows[0]['current_stock']).normalize():f}" if rows else "0"


async def test_placing_an_order_with_a_supplier_in_words(client, world):
    w = world
    resp = await client.post("/procurement/orders", json=_order(w, w["cement"], "200", rate="400",
                                                               expected_date=str(datetime.date.today())),
                             headers=w["admin"]["h"])
    assert resp.status_code == 201, resp.text
    po = resp.json()
    assert (po["ref"], po["status"], po["urgency"], po["vendor_name"]) == ("PO-0001", "open", "soon", "Malabar Hardware")
    assert (po["value"], po["lines"][0]["rate"], po["lines"][0]["pending"]) == ("80000.00", "400.00", "200")
    assert po["may_cancel"] and po["may_receive"] and not po["may_close"]
    # A site engineer sees the order, not its money (SEC-01), and cannot place one.
    as_arun = (await client.get(f"/procurement/orders/{po['id']}", headers=w["arun"]["h"])).json()
    assert as_arun["value"] is None and as_arun["lines"][0]["rate"] is None and not as_arun["may_cancel"]
    refused = await client.post("/procurement/orders", json=_order(w, w["tmt"], "5", unit="kg"), headers=w["arun"]["h"])
    assert refused.status_code == 403
    listing = (await client.get("/procurement/orders", headers=w["admin"]["h"])).json()
    assert [i["ref"] for i in listing["items"]] == ["PO-0001"] and listing["counts"]["open"] == 1


async def test_the_same_material_on_an_open_order_is_flagged(client, world):
    w = world
    assert (await client.post("/procurement/orders", json=_order(w, w["cement"], "100"), headers=w["admin"]["h"])).status_code == 201
    again = await client.post("/procurement/orders", json=_order(w, w["cement"], "50", site="yard"), headers=w["admin"]["h"])
    assert again.status_code == 409
    detail = again.json()["detail"]
    assert detail["code"] == "possible_duplicate" and "PO-0001" in detail["message"]
    assert "100 bags Cement OPC 53 (100 still to come)" in detail["message"]
    kept = await client.post("/procurement/orders", json=_order(w, w["cement"], "50", site="yard", confirm_duplicate=True),
                             headers=w["admin"]["h"])
    assert kept.status_code == 201 and kept.json()["raised_over_duplicate"] is True
    other = await client.post("/procurement/orders", json=_order(w, w["cement"], "10", site="tower", project="flats"),
                              headers=w["admin"]["h"])
    assert other.status_code == 201 and other.json()["duplicates"] == []  # guard: another project


async def test_request_to_order_to_delivery_closes_the_loop(client, world, test_engine):
    w = world
    req = (await client.post("/procurement/requests", json=_ask(w, w["cement"], "200"), headers=w["arun"]["h"])).json()
    body = _order(w, w["cement"], "200", rate="400")
    body["lines"][0]["request_line_id"] = req["lines"][0]["id"]
    po = (await client.post("/procurement/orders", json=body, headers=w["admin"]["h"])).json()
    assert po["lines"][0]["request"]["ref"] == "REQ-0001"
    after = (await client.get(f"/procurement/requests/{req['id']}", headers=w["admin"]["h"])).json()
    assert after["status"] == "ordered" and after["decision_note"] == "PO-0001, Malabar Hardware"

    # Arun receives part of it at his site: stock goes up, from the order's supplier at its rate.
    part = await client.post(f"/procurement/orders/{po['id']}/receive", headers=w["arun"]["h"], json={
        "occurred_date": str(datetime.date.today()), "lines": [{"line_id": po["lines"][0]["id"], "quantity": "150"}]})
    assert part.status_code == 201, part.text
    assert (part.json()["status"], part.json()["lines"][0]["received"], part.json()["lines"][0]["pending"]) == ("part", "150", "50")
    assert await _stock(client, w) == "150"
    inflows = (await client.get("/materials/inflows", headers=w["admin"]["h"])).json()["items"]
    assert (inflows[0]["supplier"], Decimal(inflows[0]["unit_cost"])) == ("Malabar Hardware", Decimal("400"))
    assert (await client.get(f"/procurement/requests/{req['id']}", headers=w["admin"]["h"])).json()["status"] == "ordered"
    assert not part.json()["may_close"]  # Arun receives; closing is the office's
    as_office = (await client.get(f"/procurement/orders/{po['id']}", headers=w["admin"]["h"])).json()
    assert not as_office["may_cancel"] and as_office["may_close"]

    rest = (await client.post(f"/procurement/orders/{po['id']}/receive", headers=w["admin"]["h"], json={
        "occurred_date": str(datetime.date.today()), "lines": [{"line_id": po["lines"][0]["id"], "quantity": "50"}]})).json()
    assert rest["status"] == "received" and rest["urgency"] == "closed" and len(rest["deliveries"]) == 2
    assert (await client.get(f"/procurement/requests/{req['id']}", headers=w["admin"]["h"])).json()["status"] == "done"
    async with test_engine.begin() as conn:
        told = [r[0] for r in (await conn.execute(sa.text(
            "SELECT payload->>'message' FROM notifications WHERE rule_key = 'material_request_update' ORDER BY created_at"))).all()]
    assert told[0].startswith("🛒 Ordered by Meera: 200 bags Cement OPC 53 (PO-0001, Malabar Hardware)")
    assert told[1].startswith("✅ Marked received")
    more = await client.post(f"/procurement/orders/{po['id']}/receive", headers=w["admin"]["h"], json={
        "occurred_date": str(datetime.date.today()), "lines": [{"line_id": po["lines"][0]["id"], "quantity": "1"}]})
    assert more.status_code == 409


async def test_cancel_and_close_rules(client, world):
    w = world
    req = (await client.post("/procurement/requests", json=_ask(w, w["cement"], "20"), headers=w["arun"]["h"])).json()
    body = _order(w, w["cement"], "20")
    body["lines"][0]["request_line_id"] = req["lines"][0]["id"]
    po = (await client.post("/procurement/orders", json=body, headers=w["admin"]["h"])).json()
    assert (await client.post(f"/procurement/orders/{po['id']}/cancel", json={}, headers=w["admin"]["h"])).status_code == 422
    cancelled = (await client.post(f"/procurement/orders/{po['id']}/cancel", json={"reason": "Shop closed"},
                                   headers=w["admin"]["h"])).json()
    assert cancelled["status"] == "cancelled" and cancelled["status_note"] == "Shop closed"
    back = (await client.get(f"/procurement/requests/{req['id']}", headers=w["admin"]["h"])).json()
    assert back["status"] == "waiting"  # the site still needs it

    po2 = (await client.post("/procurement/orders", json=_order(w, w["tmt"], "500", unit="kg"), headers=w["admin"]["h"])).json()
    line = po2["lines"][0]["id"]
    assert (await client.post(f"/procurement/orders/{po2['id']}/close", json={"reason": "x"}, headers=w["admin"]["h"])).status_code == 409
    await client.post(f"/procurement/orders/{po2['id']}/receive", headers=w["admin"]["h"],
                      json={"occurred_date": str(datetime.date.today()), "lines": [{"line_id": line, "quantity": "300"}]})
    assert (await client.post(f"/procurement/orders/{po2['id']}/cancel", json={"reason": "x"}, headers=w["admin"]["h"])).status_code == 409
    edit = await client.patch(f"/procurement/orders/{po2['id']}", headers=w["admin"]["h"], json={
        "lines": [{"material_id": w["tmt"], "quantity": "400", "unit_id": w["units"]["kg"]}]})
    assert edit.status_code == 409
    moved = await client.patch(f"/procurement/orders/{po2['id']}", headers=w["admin"]["h"],
                               json={"expected_date": str(datetime.date.today() - datetime.timedelta(days=1))})
    assert moved.json()["urgency"] == "late"
    closed = (await client.post(f"/procurement/orders/{po2['id']}/close", json={"reason": "Rest out of stock"},
                                headers=w["admin"]["h"])).json()
    assert closed["status"] == "closed" and closed["lines"][0]["received"] == "300"


async def test_a_delivery_taken_back_no_longer_counts(client, world):
    w = world
    po = (await client.post("/procurement/orders", json=_order(w, w["cement"], "100"), headers=w["admin"]["h"])).json()
    await client.post(f"/procurement/orders/{po['id']}/receive", headers=w["admin"]["h"], json={
        "occurred_date": str(datetime.date.today()), "lines": [{"line_id": po["lines"][0]["id"], "quantity": "100"}]})
    receipt = (await client.get("/materials/inflows", headers=w["admin"]["h"])).json()["items"][0]["id"]
    undo = await client.post(f"/materials/inflows/{receipt}/reverse", json={"reason_note": "wrong order"}, headers=w["admin"]["h"])
    assert undo.status_code == 201, undo.text
    again = (await client.get(f"/procurement/orders/{po['id']}", headers=w["admin"]["h"])).json()
    assert (again["status"], again["lines"][0]["received"], again["deliveries"]) == ("open", "0", [])


async def test_a_delivery_cannot_fill_another_sites_order_line(client, world):
    w = world
    po = (await client.post("/procurement/orders", json=_order(w, w["cement"], "100"), headers=w["admin"]["h"])).json()
    body = {"project_id": str(w["villa"]), "site_id": str(w["yard"]), "material_id": w["cement"],
            "unit_id": w["units"]["bags"], "quantity": "5", "movement_reason": "RECEIVED",
            "occurred_date": str(datetime.date.today()), "purchase_order_line_id": po["lines"][0]["id"]}
    resp = await client.post("/materials/inflows", json=body, headers=w["admin"]["h"])
    assert resp.status_code == 422 and "another site" in resp.text
    ok = await client.post("/materials/inflows", json={**body, "site_id": str(w["block_a"])}, headers=w["admin"]["h"])
    assert ok.status_code == 201
    assert (await client.get(f"/procurement/orders/{po['id']}", headers=w["admin"]["h"])).json()["lines"][0]["received"] == "5"


async def test_scope_an_engineer_of_another_project_cannot_see_or_receive(client, world):
    w = world
    po = (await client.post("/procurement/orders", json=_order(w, w["cement"], "10"), headers=w["admin"]["h"])).json()
    assert (await client.get(f"/procurement/orders/{po['id']}", headers=w["ravi"]["h"])).status_code == 404
    assert (await client.get("/procurement/orders?status=all", headers=w["ravi"]["h"])).json()["items"] == []
    resp = await client.post(f"/procurement/orders/{po['id']}/receive", headers=w["ravi"]["h"], json={
        "occurred_date": str(datetime.date.today()), "lines": [{"line_id": po["lines"][0]["id"], "quantity": "1"}]})
    assert resp.status_code == 404


# --- PRC-23: requests and orders agree -------------------------------------------------------------------------------


async def _req_with_order(client, w, qty: str = "160", ordered: str | None = None, supplier: str = "Malabar Hardware"):
    req = (await client.post("/procurement/requests", json=_ask(w, w["cement"], qty), headers=w["arun"]["h"])).json()
    body = _order(w, w["cement"], ordered or qty, supplier=supplier)
    body["lines"][0]["request_line_id"] = req["lines"][0]["id"]
    resp = await client.post("/procurement/orders", json=body, headers=w["admin"]["h"])
    assert resp.status_code == 201, resp.text
    return req, resp.json()


def _inflow(w, qty: str, *, site="block_a", **extra) -> dict:
    return {"project_id": str(w["villa"]), "site_id": str(w[site]), "material_id": w["cement"],
            "unit_id": w["units"]["bags"], "quantity": qty, "movement_reason": "RECEIVED",
            "occurred_date": str(datetime.date.today()), **extra}


async def _told(engine) -> list[str]:
    async with engine.begin() as conn:
        return [r[0] for r in (await conn.execute(sa.text(
            "SELECT payload->>'message' FROM notifications WHERE rule_key = 'material_request_update' "
            "ORDER BY created_at"))).all()]


async def test_on_order_comes_from_open_order_lines_even_without_a_request(client, world):
    w = world
    po = (await client.post("/procurement/orders", json=_order(w, w["cement"], "100"), headers=w["admin"]["h"])).json()
    asked = await client.post("/procurement/requests", json=_ask(w, w["cement"], "120"), headers=w["arun"]["h"])
    assert asked.status_code == 409  # the request's duplicate check sees the order
    detail = asked.json()["detail"]
    assert detail["code"] == "possible_duplicate" and detail["orders"][0]["ref"] == "PO-0001"
    assert "100 bags Cement OPC 53 still to come on PO-0001 from Malabar Hardware" in detail["message"]
    req = (await client.post("/procurement/requests", json=_ask(w, w["cement"], "120", confirm_duplicate=True),
                             headers=w["arun"]["h"])).json()
    assert (req["lines"][0]["on_order"], req["lines"][0]["to_buy"]) == ("100", "20")
    # 40 came: 60 still on order, 40 here, 20 to buy. Closed: nothing on order any more.
    await client.post(f"/procurement/orders/{po['id']}/receive", headers=w["admin"]["h"], json={
        "occurred_date": str(datetime.date.today()), "lines": [{"line_id": po["lines"][0]["id"], "quantity": "40"}]})
    line = (await client.get(f"/procurement/requests/{req['id']}", headers=w["admin"]["h"])).json()["lines"][0]
    assert (line["at_site"], line["on_order"], line["to_buy"]) == ("40", "60", "20")
    await client.post(f"/procurement/orders/{po['id']}/close", json={"reason": "Rest not needed"}, headers=w["admin"]["h"])
    line = (await client.get(f"/procurement/requests/{req['id']}", headers=w["admin"]["h"])).json()["lines"][0]
    assert (line["on_order"], line["to_buy"]) == ("0", "80")
    # Guard: an order at another site is not on order here.
    other = (await client.post("/procurement/orders", json=_order(w, w["tmt"], "50", unit="kg", site="yard"),
                               headers=w["admin"]["h"])).json()
    assert other["status"] == "open"


async def test_a_delivery_recorded_in_materials_fills_the_one_open_order(client, world, test_engine):
    w = world
    req, po = await _req_with_order(client, w, "160")
    resp = await client.post("/materials/inflows", json=_inflow(w, "150"), headers=w["arun"]["h"])
    assert resp.status_code == 201, resp.text
    order = resp.json()["order"]
    assert (order["ref"], order["received"], order["pending"], order["status"]) == ("PO-0001", "150", "10", "part")
    inflows = (await client.get("/materials/inflows", headers=w["admin"]["h"])).json()["items"]
    assert inflows[0]["supplier"] == "Malabar Hardware"  # the order's supplier when none was said
    after = (await client.get(f"/procurement/requests/{req['id']}", headers=w["admin"]["h"])).json()
    assert after["status"] == "ordered" and after["orders"][0]["lines"][0]["received"] == "150"
    assert after["follows_order"] and not after["may_decide"]
    done = (await client.post("/materials/inflows", json=_inflow(w, "10"), headers=w["arun"]["h"])).json()
    assert done["order"]["status"] == "received"
    assert (await client.get(f"/procurement/requests/{req['id']}", headers=w["admin"]["h"])).json()["status"] == "done"
    assert not (await _told(test_engine))[-1].startswith("✅")  # Arun recorded it himself: not messaged about it
    # Guard: with no open order left, a delivery is plain (nothing linked, nothing offered).
    plain = (await client.post("/materials/inflows", json=_inflow(w, "5"), headers=w["arun"]["h"])).json()
    assert "order" not in plain and "open_orders" not in plain


async def test_a_delivery_is_offered_not_filled_when_it_is_not_plain(client, world):
    w = world
    _, po = await _req_with_order(client, w, "100")
    # More than still to come, another shop, or "not against an order": never filled silently.
    more = (await client.post("/materials/inflows", json=_inflow(w, "120"), headers=w["admin"]["h"])).json()
    assert "order" not in more and more["open_orders"][0]["ref"] == "PO-0001"
    shop = (await client.post("/materials/inflows", json=_inflow(w, "5", supplier="KK Traders"),
                              headers=w["admin"]["h"])).json()
    assert "order" not in shop and shop["open_orders"][0]["pending"] == "100"
    none = (await client.post("/materials/inflows", json=_inflow(w, "5", no_order=True), headers=w["admin"]["h"])).json()
    assert "order" not in none and "open_orders" not in none
    # Two open orders for the same material and site: offered both.
    second = (await client.post("/procurement/orders", json=_order(w, w["cement"], "50", supplier="KK Traders",
                                                                   confirm_duplicate=True),
                                headers=w["admin"]["h"])).json()
    both = (await client.post("/materials/inflows", json=_inflow(w, "5"), headers=w["admin"]["h"])).json()
    assert [o["ref"] for o in both["open_orders"]] == ["PO-0001", "PO-0002"]
    # The office puts the KK delivery on PO-0002 from the order's page; it lists it until then.
    detail = (await client.get(f"/procurement/orders/{second['id']}", headers=w["admin"]["h"])).json()
    assert shop["id"] in [d["id"] for d in detail["unlinked_deliveries"]]
    wrong = await client.post(f"/procurement/orders/deliveries/{shop['id']}/order", json={"order": "PO-0009"},
                              headers=w["admin"]["h"])
    assert wrong.status_code == 422
    put = await client.post(f"/procurement/orders/deliveries/{shop['id']}/order",
                            json={"order": "PO-0002"}, headers=w["admin"]["h"])  # as said on WhatsApp
    assert put.status_code == 200, put.text
    assert put.json()["orders"][0]["lines"][0]["received"] == "5"
    # "Not this order": off again; stock never changes.
    stock = await _stock(client, w)
    off = await client.post(f"/procurement/orders/deliveries/{shop['id']}/order", json={"line_id": None},
                            headers=w["admin"]["h"])
    assert off.status_code == 200 and off.json()["orders"][0]["lines"][0]["received"] == "0"
    assert await _stock(client, w) == stock
    # More than the line has to come is asked here too.
    big = await client.post(f"/procurement/orders/deliveries/{more['id']}/order",
                            json={"line_id": po["lines"][0]["id"]}, headers=w["admin"]["h"])
    assert big.status_code == 409 and big.json()["detail"]["code"] == "more_than_ordered"
    # Another project's engineer cannot touch the delivery.
    assert (await client.post(f"/procurement/orders/deliveries/{shop['id']}/order", json={"line_id": None},
                              headers=w["ravi"]["h"])).status_code == 404


async def test_more_than_ordered_is_asked(client, world):
    w = world
    _, po = await _req_with_order(client, w, "160")
    line = po["lines"][0]["id"]
    receive = {"occurred_date": str(datetime.date.today()), "lines": [{"line_id": line, "quantity": "170"}]}
    asked = await client.post(f"/procurement/orders/{po['id']}/receive", json=receive, headers=w["admin"]["h"])
    assert asked.status_code == 409
    detail = asked.json()["detail"]
    assert detail["code"] == "more_than_ordered" and "160 bags Cement OPC 53 still to come" in detail["message"]
    assert await _stock(client, w) == "0"  # nothing saved
    ok = await client.post(f"/procurement/orders/{po['id']}/receive", json={**receive, "confirm_extra": True},
                           headers=w["admin"]["h"])
    assert ok.status_code == 201 and ok.json()["lines"][0]["extra"] == "10"
    # The same rule for a delivery recorded in Materials against a line.
    _, po2 = await _req_with_order(client, w, "20", supplier="KK Traders")
    body = _inflow(w, "25", purchase_order_line_id=po2["lines"][0]["id"])
    assert (await client.post("/materials/inflows", json=body, headers=w["admin"]["h"])).status_code == 409
    assert (await client.post("/materials/inflows", json={**body, "confirm_extra": True},
                              headers=w["admin"]["h"])).status_code == 201


async def test_close_short_and_cancel_move_the_request_on_and_tell_the_engineer(client, world, test_engine):
    w = world
    req, po = await _req_with_order(client, w, "160")
    await client.post(f"/procurement/orders/{po['id']}/receive", headers=w["admin"]["h"], json={
        "occurred_date": str(datetime.date.today()), "lines": [{"line_id": po["lines"][0]["id"], "quantity": "150"}]})
    await client.post(f"/procurement/orders/{po['id']}/close", json={"reason": "Shop out of stock"},
                      headers=w["admin"]["h"])
    back = (await client.get(f"/procurement/requests/{req['id']}", headers=w["admin"]["h"])).json()
    assert back["status"] == "waiting"
    assert back["decision_note"] == "PO-0001 closed short: Shop out of stock; still to order: 10 bags Cement OPC 53"
    assert (back["lines"][0]["on_order"], back["lines"][0]["to_buy"]) == ("0", "10")
    assert (await _told(test_engine))[-1].startswith("↩️ Not coming yet")
    assert not back["follows_order"] and back["may_decide"]  # the office may now say no to the rest, or send it
    # The office orders the rest from the request: ordered again, then received in full -> done.
    body = _order(w, w["cement"], "10", supplier="KK Traders")
    body["lines"][0]["request_line_id"] = req["lines"][0]["id"]
    po2 = (await client.post("/procurement/orders", json=body, headers=w["admin"]["h"])).json()
    assert (await client.get(f"/procurement/requests/{req['id']}", headers=w["admin"]["h"])).json()["status"] == "ordered"
    await client.post(f"/procurement/orders/{po2['id']}/receive", headers=w["admin"]["h"], json={
        "occurred_date": str(datetime.date.today()), "lines": [{"line_id": po2["lines"][0]["id"], "quantity": "10"}]})
    # One order closed short, the other brought the rest: 150 + 10 is what was asked, so it is received.
    final = (await client.get(f"/procurement/requests/{req['id']}", headers=w["admin"]["h"])).json()
    assert final["status"] == "done", final
    assert [o["ref"] for o in final["orders"]] == ["PO-0001", "PO-0002"]

    # Cancel: back to waiting, the engineer told.
    req2, po3 = await _req_with_order(client, w, "500", supplier="KK Traders")
    await client.post(f"/procurement/orders/{po3['id']}/cancel", json={"reason": "Price too high"}, headers=w["admin"]["h"])
    back2 = (await client.get(f"/procurement/requests/{req2['id']}", headers=w["admin"]["h"])).json()
    assert back2["status"] == "waiting" and back2["decision_note"].startswith("PO-0003 cancelled: Price too high")
    assert not back2["follows_order"] and back2["may_decide"]  # a cancelled order no longer holds it
    assert "Price too high" in (await _told(test_engine))[-1]


async def test_mark_received_by_hand_is_refused_while_an_order_covers_the_request(client, world):
    w = world
    req, _ = await _req_with_order(client, w, "20")
    resp = await client.post(f"/procurement/requests/{req['id']}/decide", json={"action": "done"}, headers=w["admin"]["h"])
    assert resp.status_code == 409 and "follows PO-0001" in resp.text
    # Guard: a request with no order is still decided by hand.
    other = (await client.post("/procurement/requests", json=_ask(w, w["tmt"], "5", unit="kg"), headers=w["arun"]["h"])).json()
    assert (await client.get(f"/procurement/requests/{other['id']}", headers=w["admin"]["h"])).json()["may_decide"]
    assert (await client.post(f"/procurement/requests/{other['id']}/decide", json={"action": "ordered"},
                              headers=w["admin"]["h"])).status_code == 200


async def test_a_new_order_names_the_waiting_request_for_the_same_material(client, world):
    w = world
    req = (await client.post("/procurement/requests", json=_ask(w, w["cement"], "100"), headers=w["arun"]["h"])).json()
    resp = await client.post("/procurement/orders", json=_order(w, w["cement"], "100"), headers=w["admin"]["h"])
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["requests"][0]["ref"] == "REQ-0001"
    assert detail["message"].startswith("Arun asked for 100 bags Cement OPC 53 for Block A (REQ-0001, waiting)")
    # Guard: ordered from the request itself, no warning.
    body = _order(w, w["cement"], "100")
    body["lines"][0]["request_line_id"] = req["lines"][0]["id"]
    assert (await client.post("/procurement/orders", json=body, headers=w["admin"]["h"])).status_code == 201
