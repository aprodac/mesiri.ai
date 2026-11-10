"""PRC-46: returns to the supplier and debit notes on a real Postgres (run with `pytest -m integration`).

A GRN's rejected quantity goes back without touching stock (it never came in); a delivery goes back out of stock
(RETURN_TO_VENDOR, the one posting path); either way the debit note lowers what is owed to the supplier at once
(D-P2-3) and stays when settled. Nothing goes back twice; a return waiting for pickup can be cancelled (stock and
ledger back as they were); the office records, site roles see without money; another company sees nothing.
"""

from __future__ import annotations

import json
import uuid

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contract.company_day import company_today
from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import create_access_token
from mesiri.http.app import create_app
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration

_TABLES = (
    "material_return_lines", "material_returns", "stock_levels", "notifications", "expense_payments", "expenses", "rfq_quote_lines", "rfq_vendors", "rfq_lines", "rfqs", "goods_receipt_lines",
    "goods_receipts", "purchase_order_events", "purchase_order_lines", "purchase_orders", "material_request_lines",
    "material_requests", "material_movements", "material_receipts", "material_usage", "material_invoice_attachments",
    "material_invoices", "material_unit_conversions", "material_aliases", "materials_catalog", "material_categories",
    "vendors", "project_members", "sites", "projects", "users", "organizations",
)


async def _wipe(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(sa.text("UPDATE material_usage SET reverses_movement_id = NULL"))
        await conn.execute(sa.text("UPDATE material_receipts SET reverses_movement_id = NULL"))
        await conn.execute(sa.text("UPDATE rfq_lines SET awarded_quote_line_id = NULL"))
        for table in _TABLES:
            await conn.execute(sa.text(f"DELETE FROM {table}"))  # noqa: S608 -- fixed names


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    await _wipe(engine)
    yield engine
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
                "access_policy, whatsapp_number, created_at, updated_at) VALUES (:id, :org, :email, 'hash', :name, "
                ":role, 'active', CAST(:policy AS jsonb), :wa, now(), now())", id=user_id, org=org,
                email=f"{uuid.uuid4().hex[:8]}@x.com", name=name, role=role, policy=json.dumps(policy),
                wa=f"9198{uuid.uuid4().int % 10**8:08d}")
    for project in projects or []:
        await _exec(engine, "INSERT INTO project_members (id, project_id, user_id) VALUES (:id, :p, :u)",
                    id=uuid.uuid4(), p=project, u=user_id)
    token = create_access_token(data={"sub": str(user_id), "org": str(org), "role": role})
    return {"id": user_id, "h": {"Authorization": f"Bearer {token}"}}


async def _org(engine, name: str) -> uuid.UUID:
    org = uuid.uuid4()
    await _exec(engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, "
                "updated_at) VALUES (:id, :name, 'local', 'default', 'active', now(), now())", id=org, name=name)
    return org


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
    org = await _org(test_engine, "Builder")
    villa = await _project(test_engine, org, "Villa Kakkanad")
    block_a = await _site(test_engine, org, villa, "Block A")
    admin = await _user(test_engine, org, "admin", "Meera")
    arun = await _user(test_engine, org, "site_engineer", "Arun", projects=[villa])
    units = {u["code"]: u["id"] for u in (await client.get("/materials/units-of-measure", headers=admin["h"])).json()["items"]}
    cement = (await client.post("/materials", json={"name": "Cement OPC 53", "default_unit_id": units["bags"]},
                                headers=admin["h"])).json()["id"]
    tmt = (await client.post("/materials", json={"name": "TMT bar 12 mm", "default_unit_id": units["kg"]},
                             headers=admin["h"])).json()["id"]
    vendors = {}
    for name in ("Malabar Hardware", "KK Traders"):
        vendors[name] = (await client.post("/finance/vendors", json={"name": name}, headers=admin["h"])).json()["id"]
    return {"org": org, "villa": villa, "block_a": block_a, "admin": admin, "arun": arun, "units": units,
            "cement": cement, "tmt": tmt, "malabar": vendors["Malabar Hardware"], "kk": vendors["KK Traders"]}


async def _stock(client, w, material) -> str:
    got = (await client.get(f"/materials/stock-check?material_id={material}&site_id={w['block_a']}",
                            headers=w["admin"]["h"])).json()
    return f"{float(got['available']):g}"


async def _balance(client, w, vendor) -> tuple[str, list[str]]:
    led = (await client.get(f"/finance/vendors/{vendor}/ledger", headers=w["admin"]["h"])).json()
    return led["closing"], [x["kind"] for x in led["lines"]]


async def _grn_with_rejects(client, w) -> dict:
    po = await client.post("/procurement/orders", headers=w["admin"]["h"], json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]), "vendor_id": w["malabar"],
        "lines": [{"material_id": w["cement"], "quantity": "200", "unit_id": w["units"]["bags"], "rate": "400"}]})
    assert po.status_code == 201, po.text
    po = po.json()
    got = await client.post(f"/procurement/orders/{po['id']}/receive", headers=w["admin"]["h"], json={
        "occurred_date": str(company_today()),
        "lines": [{"line_id": po["lines"][0]["id"], "quantity": "188", "rejected": "12", "rejected_reason": "torn bags"}]})
    assert got.status_code == 201, got.text
    return (await client.get("/procurement/grns", headers=w["admin"]["h"])).json()["items"][0]


async def test_a_grns_rejected_quantity_goes_back_without_touching_stock(client, world):
    w = world
    grn = await _grn_with_rejects(client, w)
    assert await _stock(client, w, w["cement"]) == "188"
    src = (await client.get(f"/procurement/returns/sources?grn_id={grn['id']}", headers=w["admin"]["h"])).json()["items"]
    assert [(s["material"], s["left"], s["rate"], s["in_stock"], s["said_reason"]) for s in src] == [
        ("Cement OPC 53", "12", "400.00", False, "torn bags")]
    made = await client.post("/procurement/returns", headers=w["admin"]["h"], json={
        "lines": [{"grn_line_id": src[0]["grn_line_id"], "quantity": "12", "reason": "damaged"}]})
    assert made.status_code == 201, made.text
    dn = made.json()
    assert (dn["ref"], dn["status"], dn["vendor_name"], dn["grn_ref"], dn["order_ref"], dn["total"]) == (
        "DN-0001", "waiting", "Malabar Hardware", grn["ref"], "PO-0001", "4800.00")
    assert dn["lines"][0]["from_stock"] is False and dn["what"] == "12 bags Cement OPC 53 (damaged)"
    assert await _stock(client, w, w["cement"]) == "188"  # never came in, so nothing leaves
    balance, kinds = await _balance(client, w, w["malabar"])
    assert (balance, kinds) == ("70400.00", ["delivery", "debit_note"])  # 188 x 400 - 4,800 at once (D-P2-3)
    again = await client.post("/procurement/returns", headers=w["admin"]["h"], json={
        "lines": [{"grn_line_id": src[0]["grn_line_id"], "quantity": "1", "reason": "damaged"}]})
    assert again.status_code == 409  # all 12 are on DN-0001 already
    # Settled by credit: the note stays, and the order is said to still wait for them.
    settled = await client.post(f"/procurement/returns/{dn['id']}/settle", headers=w["admin"]["h"],
                                json={"how": "credit", "note": "less on the next bill"})
    assert settled.status_code == 200, settled.text
    assert settled.json()["status"] == "settled" and "PO-0001 still expects" in settled.json()["hint"]
    assert (await _balance(client, w, w["malabar"]))[0] == "70400.00"


async def test_a_delivery_goes_back_out_of_stock_and_a_cancel_puts_it_back(client, world):
    w = world
    came = await client.post("/materials/inflows", headers=w["admin"]["h"], json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]), "material_id": w["tmt"], "unit_id": w["units"]["kg"],
        "quantity": "1000", "unit_cost": "60", "gst_percent": "18", "rate_includes_gst": False, "vendor_id": w["kk"],
        "occurred_date": str(company_today()), "movement_reason": "RECEIVED", "no_order": True})
    assert came.status_code == 201, came.text
    # Said as on WhatsApp: the supplier in words and the material only; it goes against KK's last delivery of it.
    made = await client.post("/procurement/returns", headers=w["admin"]["h"], json={
        "supplier": "KK Traders", "site_id": str(w["block_a"]), "source": "whatsapp",
        "lines": [{"material_id": w["tmt"], "quantity": "0.1", "unit_id": w["units"]["tons"], "reason": "wrong_size"}]})
    assert made.status_code == 201, made.text
    dn = made.json()
    assert dn["lines"][0]["receipt_id"] == came.json()["id"] and dn["lines"][0]["quantity"] == "100"  # 0.1 t = 100 kg
    assert (dn["before_gst"], dn["gst"], dn["total"]) == ("6000.00", "1080.00", "7080.00")  # 100 x 60 + 18%
    assert await _stock(client, w, w["tmt"]) == "900"
    summary = (await client.get("/materials/stock-summary", headers=w["admin"]["h"])).json()
    assert next(r for r in summary if r["material_id"] == w["tmt"])["used"] in ("100.00", "100.000")  # RETURN_TO_VENDOR
    # 60,000 delivered (an unbilled delivery is owed at its rate as entered) - 7,080 debit note (what the supplier
    # charges for it, GST in): the GST evens out when their bill (70,800) replaces the delivery.
    assert (await _balance(client, w, w["kk"]))[0] == "52920.00"
    too_much = await client.post("/procurement/returns", headers=w["admin"]["h"], json={
        "lines": [{"receipt_id": came.json()["id"], "quantity": "901", "reason": "excess"}]})
    assert too_much.status_code == 409
    gone = await client.post(f"/procurement/returns/{dn['id']}/cancel", headers=w["admin"]["h"],
                             json={"reason": "they will exchange it at the site"})
    assert gone.status_code == 200 and gone.json()["status"] == "cancelled"
    assert await _stock(client, w, w["tmt"]) == "1000"
    assert await _balance(client, w, w["kk"]) == ("60000.00", ["delivery"])


async def test_sent_then_settled_by_the_replacement_delivery(client, world):
    w = world
    came = (await client.post("/materials/inflows", headers=w["admin"]["h"], json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]), "material_id": w["cement"],
        "unit_id": w["units"]["bags"], "quantity": "50", "unit_cost": "410", "vendor_id": w["kk"],
        "occurred_date": str(company_today()), "movement_reason": "RECEIVED", "no_order": True})).json()
    dn = (await client.post("/procurement/returns", headers=w["admin"]["h"], json={
        "lines": [{"receipt_id": came["id"], "quantity": "5", "reason": "quality_failed"}]})).json()
    sent = await client.post(f"/procurement/returns/{dn['id']}/sent", headers=w["admin"]["h"], json={"collected_by": "KK driver"})
    assert sent.json()["status"] == "sent" and sent.json()["timeline"][-1]["what"] == "Sent back, collected by KK driver"
    assert (await client.post(f"/procurement/returns/{dn['id']}/cancel", headers=w["admin"]["h"],
                              json={"reason": "x"})).status_code == 409  # it has gone back
    fresh = (await client.post("/materials/inflows", headers=w["admin"]["h"], json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]), "material_id": w["cement"],
        "unit_id": w["units"]["bags"], "quantity": "5", "unit_cost": "410", "vendor_id": w["kk"],
        "occurred_date": str(company_today()), "movement_reason": "RECEIVED", "no_order": True})).json()
    wrong = await client.post(f"/procurement/returns/{dn['id']}/settle", headers=w["admin"]["h"],
                              json={"how": "replacement", "expense_id": str(uuid.uuid4())})
    assert wrong.status_code == 422
    done = await client.post(f"/procurement/returns/{dn['id']}/settle", headers=w["admin"]["h"],
                             json={"how": "replacement", "receipt_id": fresh["id"]})
    assert done.status_code == 200 and done.json()["settled_receipt_id"] == fresh["id"]
    # 50 + 5 delivered, 5 went back: paid for 50 good bags.
    assert (await _balance(client, w, w["kk"]))[0] == "20500.00"
    listed = (await client.get("/procurement/returns", headers=w["admin"]["h"])).json()
    assert listed["counts"] == {"waiting": 0, "sent": 0, "this_month": 1, "owed_to_you": "0.00"}


async def test_site_roles_see_without_money_and_another_company_sees_nothing(client, world, test_engine):
    w = world
    grn = await _grn_with_rejects(client, w)
    src = (await client.get(f"/procurement/returns/sources?grn_id={grn['id']}", headers=w["admin"]["h"])).json()["items"]
    body = {"lines": [{"grn_line_id": src[0]["grn_line_id"], "quantity": "12", "reason": "damaged"}]}
    assert (await client.post("/procurement/returns", headers=w["arun"]["h"], json=body)).status_code == 403
    dn = (await client.post("/procurement/returns", headers=w["admin"]["h"], json=body)).json()
    seen = (await client.get("/procurement/returns", headers=w["arun"]["h"])).json()
    assert seen["total"] == 1 and "total" not in seen["items"][0] and "owed_to_you" not in seen["counts"]
    assert "rate" not in seen["items"][0]["lines"][0] and not seen["items"][0]["may_settle"]
    other = await _org(test_engine, "Other builder")
    stranger = await _user(test_engine, other, "admin", "Someone")
    assert (await client.get("/procurement/returns", headers=stranger["h"])).json()["total"] == 0
    assert (await client.get(f"/procurement/returns/{dn['id']}", headers=stranger["h"])).status_code == 404
    assert (await client.post(f"/procurement/returns/{dn['id']}/settle", headers=stranger["h"],
                              json={"how": "credit"})).status_code == 404
    assert (await client.get(f"/procurement/returns/sources?grn_id={grn['id']}", headers=stranger["h"])).json()["items"] == []
