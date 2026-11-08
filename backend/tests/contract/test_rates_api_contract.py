"""PRC-14 / PRC-16: the rates API on a real Postgres (run with `pytest -m integration`).

Every delivery with a rate counts once: per stock unit (a rate said per tonne is per kg here), by supplier (a vendor
record, or a name as typed), not a delivery taken back, not a move between sites. Last rate against the one before
(also before the period), each supplier's average, the cheapest, and what was paid above it. A delivery charged a
different rate from its order is flagged. Money roles only; a site engineer is refused; scope follows projects.
"""

from __future__ import annotations

import datetime
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
    "labour_attendance_lines", "labour_attendance_reports", "expense_payments", "money_transactions", "expense_attachments", "expenses",
    "expense_categories", "goods_receipt_lines", "goods_receipts", "purchase_order_events", "purchase_order_lines", "purchase_orders", "material_request_lines", "material_requests", "notifications", "material_movements", "material_receipts",
    "material_usage", "material_invoice_attachments", "material_invoices", "materials_catalog",
    "material_categories", "vendors", "sites", "projects", "users", "organizations",
)


async def _wipe(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(sa.text("UPDATE material_usage SET reverses_movement_id = NULL"))
        await conn.execute(sa.text("UPDATE material_receipts SET reverses_movement_id = NULL"))
        await conn.execute(sa.text("UPDATE material_invoices SET expense_id = NULL"))
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
            "quantity": qty, "movement_reason": "RECEIVED", "occurred_date": str(company_today())}
    if rate:
        body["unit_cost"] = rate
    resp = await client.post("/materials/inflows", json=body, headers=w["admin"]["h"])
    assert resp.status_code == 201, resp.text



TODAY = company_today()


def _day(days_ago: int) -> str:
    return str(TODAY - datetime.timedelta(days=days_ago))


async def _came(client, w, material, qty: str, rate: str | None, *, days_ago: int, supplier: str | None = None,
                vendor_id: str | None = None, site="block_a", project="villa", unit=None, po_line=None) -> dict:
    body = {"project_id": str(w[project]), "site_id": str(w[site]), "material_id": w[material],
            "unit_id": unit or w["units"]["bags" if material == "cement" else "kg"], "quantity": qty,
            "movement_reason": "RECEIVED", "occurred_date": _day(days_ago), "no_order": po_line is None}
    if rate is not None:
        body["unit_cost"] = rate
    if supplier:
        body["supplier"] = supplier
    if vendor_id:
        body["vendor_id"] = vendor_id
    if po_line:
        body["purchase_order_line_id"] = po_line
    resp = await client.post("/materials/inflows", json=body, headers=w["admin"]["h"])
    assert resp.status_code == 201, resp.text
    return resp.json()


def _item(payload: dict, material_id: str) -> dict:
    return next(i for i in payload["items"] if i["material_id"] == material_id)


async def test_rates_by_supplier_trend_cheapest_and_what_was_paid_above(client, world):
    w = world
    await _came(client, w, "cement", "100", "380", days_ago=200, supplier="Malabar Hardware")  # before the period
    await _came(client, w, "cement", "100", "400", days_ago=40, supplier="Malabar Hardware")
    await _came(client, w, "cement", "200", "390", days_ago=30, supplier="KK Traders")
    await _came(client, w, "cement", "100", "420", days_ago=5, supplier="Malabar Hardware", site="yard")
    await _came(client, w, "cement", "50", None, days_ago=3, supplier="Malabar Hardware")  # no rate: not a rate

    resp = await client.get("/procurement/rates", headers=w["admin"]["h"])
    assert resp.status_code == 200, resp.text
    cement = _item(resp.json(), w["cement"])
    assert (cement["purchases"], cement["quantity"], cement["unit"]) == (3, "400", "bags")
    assert (cement["last"]["rate"], cement["last"]["vendor_name"], cement["last"]["site_name"]) == ("420.00", "Malabar Hardware", "Yard")
    assert cement["previous"]["rate"] == "390.00" and cement["previous"]["in_period"] is True
    assert (cement["change_pct"], cement["trend"]) == ("7.7", "up")
    assert (cement["min_rate"], cement["max_rate"], cement["avg_rate"], cement["spend"]) == ("390.00", "420.00", "400.00", "160000.00")
    names = [(v["name"], v["avg_rate"], v["best"]) for v in cement["vendors"]]
    assert names == [("KK Traders", "390.00", True), ("Malabar Hardware", "410.00", False)]
    assert cement["best"]["vendor_name"] == "KK Traders"
    assert cement["above_best"] == "4000.00"  # 160,000 paid - 400 bags x 390
    assert [p["rate"] for p in cement["points"]] == ["400.00", "390.00", "420.00"]
    assert resp.json()["summary"]["rising"] == 1

    # A longer period reaches the purchase before: four purchases, the first at 380.
    year = (await client.get("/procurement/rates", params={"date_from": _day(365)}, headers=w["admin"]["h"])).json()
    assert _item(year, w["cement"])["purchases"] == 4

    # One purchase in the period: the change is measured from the last one before it.
    await _came(client, w, "tmt", "1000", "64", days_ago=150, supplier="Kerala Steels")
    await _came(client, w, "tmt", "500", "60", days_ago=10, supplier="Kerala Steels")
    tmt = _item((await client.get("/procurement/rates", headers=w["admin"]["h"])).json(), w["tmt"])
    assert tmt["purchases"] == 1 and tmt["previous"] == {"rate": "64.00", "date": _day(150), "vendor_name": "Kerala Steels", "in_period": False}
    assert (tmt["trend"], tmt["best"], tmt["above_best"]) == ("down", None, "0.00")


async def test_a_rate_per_tonne_is_per_kg_and_a_taken_back_delivery_and_a_move_do_not_count(client, world):
    w = world
    await _came(client, w, "tmt", "2", "62000", days_ago=4, supplier="Kerala Steels", unit=w["units"]["mt"])
    wrong = await _came(client, w, "tmt", "100", "99", days_ago=3, supplier="Kerala Steels")
    taken_back = await client.post(f"/materials/inflows/{wrong['id']}/reverse", headers=w["admin"]["h"],
                                   json={"reason_note": "wrong rate"})
    assert taken_back.status_code in (200, 201), taken_back.text
    moved = await client.post("/materials/transfers", headers=w["admin"]["h"], json={
        "from_project_id": str(w["villa"]), "from_site_id": str(w["block_a"]), "to_project_id": str(w["villa"]),
        "to_site_id": str(w["yard"]), "material_id": w["tmt"], "unit_id": w["units"]["kg"], "quantity": "100",
        "occurred_date": _day(1)})
    assert moved.status_code == 201, moved.text
    tmt = _item((await client.get("/procurement/rates", headers=w["admin"]["h"])).json(), w["tmt"])
    assert (tmt["purchases"], tmt["quantity"], tmt["last"]["rate"], tmt["unit"]) == (1, "2000", "62.00", "kg")


async def test_a_delivery_charged_differently_from_its_order_is_flagged(client, world):
    w = world
    po = (await client.post("/procurement/orders", headers=w["admin"]["h"], json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]), "supplier": "Malabar Hardware",
        "lines": [{"material_id": w["cement"], "quantity": "200", "unit_id": w["units"]["bags"], "rate": "400"}]})).json()
    line = po["lines"][0]["id"]
    await _came(client, w, "cement", "100", "415", days_ago=1, po_line=line)
    got = (await client.post(f"/procurement/orders/{po['id']}/receive", headers=w["admin"]["h"],
                             json={"lines": [{"line_id": line, "quantity": "100"}], "occurred_date": _day(0)}))
    assert got.status_code in (200, 201), got.text
    purchases = (await client.get(f"/procurement/rates/{w['cement']}", headers=w["admin"]["h"])).json()["purchases"]
    assert [(p["rate"], p["source"], p["order_ref"], p["ordered_rate"], p["differs_from_order"]) for p in purchases] == [
        ("400.00", "order", "PO-0001", "400.00", False),
        ("415.00", "order", "PO-0001", "400.00", True),
    ]


async def test_money_roles_only_scope_and_one_supplier(client, world):
    w = world
    await _came(client, w, "cement", "100", "400", days_ago=2, supplier="Malabar Hardware")
    await _came(client, w, "cement", "10", "450", days_ago=1, supplier="Edappally Stores", site="tower", project="flats")
    assert (await client.get("/procurement/rates", headers=w["arun"]["h"])).status_code == 403
    assert (await client.get(f"/procurement/rates/{w['cement']}", headers=w["arun"]["h"])).status_code == 403
    villa = (await client.get("/procurement/rates", params={"project_id": str(w["villa"])}, headers=w["admin"]["h"])).json()
    assert _item(villa, w["cement"])["purchases"] == 1
    tower = (await client.get("/procurement/rates", params={"project_id": str(w["flats"]), "site_id": str(w["tower"])},
                              headers=w["admin"]["h"])).json()
    assert _item(tower, w["cement"])["last"]["rate"] == "450.00"
    # The supplier page: only items this vendor delivered, still compared with every supplier.
    vendors = (await client.get("/finance/vendors", headers=w["admin"]["h"])).json()
    vendors = vendors.get("items", vendors) if isinstance(vendors, dict) else vendors
    malabar = next(v["id"] for v in vendors if v["name"] == "Malabar Hardware")
    mine = (await client.get("/procurement/rates", params={"vendor_id": malabar}, headers=w["admin"]["h"])).json()
    assert [i["material_name"] for i in mine["items"]] == ["Cement OPC 53"]
    assert _item(mine, w["cement"])["best"]["vendor_name"] == "Malabar Hardware"
    assert (await client.get("/procurement/rates", params={"date_from": _day(1), "date_to": _day(5)},
                             headers=w["admin"]["h"])).status_code == 422


# CC-01 (approved in session by the owner, 7 Nov 2026): the full cost of a period -- expenses, priced deliveries that
# came without a bill (a bill already made an expense), and labour at the wage on each attendance line -- each once.
async def test_full_cost_counts_each_rupee_once(client, world, test_engine):
    w = world
    h = w["admin"]["h"]
    exp = await client.post("/expenses", headers={**h, "Idempotency-Key": str(uuid.uuid4())}, json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]), "amount": "1500", "category_text": "Tea",
        "occurred_date": _day(2)})
    assert exp.status_code == 201, exp.text
    await _came(client, w, "cement", "100", "400", days_ago=3, supplier="Malabar Hardware")             # 40,000
    billed = await _came(client, w, "cement", "10", "410", days_ago=3, supplier="Malabar Hardware")     # has a bill
    await _came(client, w, "cement", "5", None, days_ago=1, supplier="Malabar Hardware", site="yard")   # no price
    await _came(client, w, "cement", "20", "450", days_ago=1, supplier="Edappally Stores", site="tower", project="flats")
    inv = uuid.uuid4()
    await _exec(test_engine, "INSERT INTO material_invoices (id, organization_id, project_id, currency, source, created_by) "
                "VALUES (:id, :org, :p, 'INR', 'web', :u)", id=inv, org=w["org"], p=w["villa"], u=w["admin"]["id"])
    await _exec(test_engine, "UPDATE material_receipts SET invoice_id = :inv WHERE id = :id", inv=inv, id=billed["id"])
    report = uuid.uuid4()
    await _exec(test_engine, "INSERT INTO labour_attendance_reports (id, organization_id, project_id, site_id, occurred_date, "
                "recorded_via, created_at, created_by) VALUES (:id, :org, :p, :s, :d, 'whatsapp_text', now(), :u)",
                id=report, org=w["org"], p=w["villa"], s=w["block_a"], d=TODAY - datetime.timedelta(days=1), u=w["admin"]["id"])
    for trade, n, wage in (("mason", 4, "1000"), ("helper", 2, "700"), ("cleaner", 1, None)):
        await _exec(test_engine, "INSERT INTO labour_attendance_lines (id, report_id, trade, headcount, daily_wage, created_at) "
                    "VALUES (:id, :r, :t, :n, :w, now())", id=uuid.uuid4(), r=report, t=trade, n=n, w=wage)

    # A bill recorded without a price made no expense: its delivery is still owed and costs (8 Nov 2026: hidden before).
    unbilled = (await client.get("/finance/costs", headers=h)).json()
    assert unbilled["materials"]["amount"] == "53100.00"
    bill = (await client.post("/expenses", headers={**h, "Idempotency-Key": str(uuid.uuid4())}, json={
        "project_id": str(w["villa"]), "amount": "4100", "category_text": "Materials", "occurred_date": _day(3)})).json()
    await _exec(test_engine, "UPDATE material_invoices SET expense_id = :e WHERE id = :id", e=bill["id"], id=inv)

    resp = await client.get("/finance/costs", headers=h)
    assert resp.status_code == 200, resp.text
    c = resp.json()
    assert c["expenses"] == {"amount": "5600.00", "count": 2}                      # the bill, once
    assert (c["materials"]["amount"], c["materials"]["deliveries"], c["materials"]["unpriced"]) == ("49000.00", 2, 1)
    assert (c["labour"]["amount"], c["labour"]["man_days"], c["labour"]["priced_man_days"]) == ("5400.00", "7", "6")
    assert c["total"] == "60000.00"
    block_a = next(s for s in c["by_site"] if s["site_name"] == "Block A")
    assert (block_a["expenses"], block_a["materials"], block_a["labour"], block_a["total"]) == ("1500.00", "40000.00", "5400.00", "46900.00")

    villa = (await client.get("/finance/costs", params={"project_id": str(w["villa"])}, headers=h)).json()
    assert villa["total"] == "51000.00"
    assert (await client.get("/finance/costs", headers=w["arun"]["h"])).status_code == 403


async def test_an_expense_from_a_bill_shows_the_bill_its_items_and_gst(client, world):
    """The expense a supplier bill made links back to the bill and what it delivered; the list carries GST."""
    w = world
    h = w["admin"]["h"]
    resp = await client.post("/materials/invoices", headers={**h, "Idempotency-Key": str(uuid.uuid4())}, json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]), "supplier_name": "Malabar Hardware",
        "invoice_number": "MH/2231", "invoice_date": _day(1), "invoice_total": "41300",
        "lines": [{"material_id": w["cement"], "unit_id": w["units"]["bags"], "quantity": "100", "unit_cost": "413"}]})
    assert resp.status_code == 201, resp.text
    expense_id = resp.json()["expense_id"]
    one = (await client.get(f"/expenses/{expense_id}", headers=h)).json()
    inv = one["source_invoice"]
    assert (inv["number"], inv["supplier"]) == ("MH/2231", "Malabar Hardware")
    assert inv["items"] == [{"material": "Cement OPC 53", "quantity": "100", "unit": "bags", "rate": "413.00", "order_id": None, "order_ref": None}]
    row = next(r for r in (await client.get("/expenses", headers=h)).json() if r["id"] == expense_id)
    assert "tax_rate" in row and row["is_tax_inclusive"] is True
