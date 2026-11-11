"""PRC-40..43: quotations on a real Postgres (run with `pytest -m integration`).

Ask three suppliers, record their quotes (with and without GST, one per tonne for steel kept in kg, one declined),
compare as each costs the company (D-CC8), and award: one purchase order per chosen supplier through the order route
(its duplicate check, the site's request told), the reason kept when the cheapest was not chosen. Rates hidden from
site roles; the office only writes; another company's RFQ is not found.
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
    "labour_attendance_lines", "labour_attendance_reports", "expense_payments", "money_transactions", "expense_attachments", "expenses",
    "expense_categories", "rfq_quote_lines", "rfq_vendors", "rfq_lines", "rfqs", "goods_receipt_lines", "goods_receipts", "purchase_order_events", "purchase_order_lines", "purchase_orders", "material_request_lines", "material_requests", "notifications", "material_movements", "material_receipts",
    "material_usage", "material_invoice_attachments", "material_invoices", "materials_catalog",
    "material_categories", "vendors", "sites", "projects", "users", "organizations",
)


async def _wipe(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(sa.text("UPDATE material_usage SET reverses_movement_id = NULL"))
        await conn.execute(sa.text("UPDATE material_receipts SET reverses_movement_id = NULL"))
        await conn.execute(sa.text("UPDATE material_invoices SET expense_id = NULL"))
        await conn.execute(sa.text("UPDATE rfq_lines SET awarded_quote_line_id = NULL"))
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
    for name, gstin in (("Malabar Hardware", "32ABCDE1234F1Z5"), ("KK Traders", None), ("Kerala Steels", "32AAACK9999K1Z2")):
        await client.post("/finance/vendors", json={"name": name, **({"gstin": gstin} if gstin else {})}, headers=admin["h"])
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




def _new(w, **extra) -> dict:
    return {"project_id": str(w["villa"]), "site_id": str(w["block_a"]),
            "lines": [{"material_id": w["cement"], "quantity": "200", "unit_id": w["units"]["bags"]},
                      {"material_id": w["tmt"], "quantity": "2000", "unit_id": w["units"]["kg"]}],
            "suppliers": ["Malabar Hardware", "KK Traders", "Kerala Steels"], "due_date": str(company_today()), **extra}


async def _quote(client, w, rfq, supplier, lines, **extra):
    resp = await client.post(f"/procurement/rfqs/{rfq['id']}/quotes", headers=w["admin"]["h"],
                             json={"supplier": supplier, "lines": lines, **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _quoted(client, w) -> dict:
    rfq = (await client.post("/procurement/rfqs", json=_new(w), headers=w["admin"]["h"]))
    assert rfq.status_code == 201, rfq.text
    rfq = rfq.json()
    assert (rfq["ref"], rfq["status"], rfq["counts"]) == ("RFQ-0001", "open", {"invited": 3, "quoted": 0, "declined": 0})
    # Malabar (GSTIN): cement 472 incl 28% = 368.75 before GST, which it claims back; steel 64 + 18%.
    await _quote(client, w, rfq, "Malabar Hardware", [{"material_id": w["cement"], "rate": "472"},
                                                      {"material_id": w["tmt"], "rate": "64", "rate_includes_gst": False}],
                 gst_percent="28", rates_include_gst=True, delivery_days=2, valid_until=str(company_today()))
    # Oops: the steel GST is 18, not 28 -- a revised quote replaces that line.
    await _quote(client, w, rfq, "Malabar Hardware", [{"material_id": w["tmt"], "rate": "64", "gst_percent": "18",
                                                       "rate_includes_gst": False}], delivery_days=2)
    # KK (no GSTIN): cement 380 + 28% = 486.40 paid; steel per tonne, 60,000 incl. 18% = 60 a kg.
    await _quote(client, w, rfq, "KK Traders", [{"material_id": w["cement"], "rate": "380", "gst_percent": "28",
                                                 "rate_includes_gst": False},
                                                {"material_id": w["tmt"], "rate": "60000", "unit_id": w["units"]["tons"],
                                                 "gst_percent": "18", "rate_includes_gst": True}], delivery_days=1)
    ks = next(s for s in (await client.get(f"/procurement/rfqs/{rfq['id']}", headers=w["admin"]["h"])).json()["suppliers"]
              if s["name"] == "Kerala Steels")
    declined = await client.post(f"/procurement/rfqs/{rfq['id']}/suppliers/{ks['rfq_vendor_id']}/decline",
                                 json={"reason": "No stock of 12 mm"}, headers=w["admin"]["h"])
    assert declined.status_code == 200, declined.text
    return declined.json()


async def test_quotes_compare_as_each_costs_the_company(client, world):
    w = world
    rfq = await _quoted(client, w)
    assert rfq["status"] == "ready" and rfq["counts"] == {"invited": 0, "quoted": 2, "declined": 1}
    cement, tmt = rfq["lines"]
    assert [(q["cost"], q["rate_with_gst"], q["gst_claimable"], q["lowest"]) for q in cement["quotes"]] == [
        ("368.75", "472.00", True, True), ("486.40", "486.40", False, False)]
    assert tmt["quantity"] == "2000" and [(q["cost"], q["lowest"]) for q in tmt["quotes"]] == [
        ("60.00", True), ("64.00", False)]  # KK: 60,000 a tonne = 60 a kg, GST in; Malabar 64 before GST (claimed)
    by = {s["name"]: s for s in rfq["suppliers"]}
    assert (by["Malabar Hardware"]["total"], by["Malabar Hardware"]["complete"], by["Malabar Hardware"]["best_total"]) == (
        "201750.00", True, True)  # 200 x 368.75 + 2000 x 64
    assert by["KK Traders"]["total"] == "217280.00" and by["Kerala Steels"]["decline_reason"] == "No stock of 12 mm"
    assert rfq["lowest_total"]["name"] == "Malabar Hardware"
    assert rfq["lowest_per_line"] == {"total": "193750.00", "suppliers": 2, "complete": True, "saves": "8000.00"}


async def test_award_cheapest_per_line_places_one_order_per_supplier(client, world):
    w = world
    rfq = await _quoted(client, w)
    done = await client.post(f"/procurement/rfqs/{rfq['id']}/award", json={"mode": "lowest_per_line"},
                             headers=w["admin"]["h"])
    assert done.status_code == 201, done.text
    done = done.json()
    assert done["status"] == "awarded" and [o["ref"] for o in done["orders"]] == ["PO-0001", "PO-0002"]
    orders = {o["vendor_name"]: o for o in (await client.get("/procurement/orders", headers=w["admin"]["h"])).json()["items"]}
    mal, kk = orders["Malabar Hardware"]["lines"][0], orders["KK Traders"]["lines"][0]
    assert (mal["material"], mal["rate"], mal["gst_percent"], mal["rate_includes_gst"]) == ("Cement OPC 53", "472.00", "28", True)
    assert (kk["material"], kk["quantity"], kk["rate"], kk["gst_percent"]) == ("TMT bar 12 mm", "2000", "60.00", "18")
    assert orders["KK Traders"]["notes"] == "From RFQ-0001"
    again = await client.post(f"/procurement/rfqs/{rfq['id']}/award", json={"mode": "lowest_total"}, headers=w["admin"]["h"])
    assert again.status_code == 409


async def test_not_the_cheapest_needs_a_reason_and_keeps_it(client, world):
    w = world
    rfq = await _quoted(client, w)
    kk = next(s for s in rfq["suppliers"] if s["name"] == "KK Traders")
    pick = {"mode": "picks", "picks": [{"rfq_line_id": rfq["lines"][0]["id"], "vendor_id": kk["vendor_id"]}]}
    refused = await client.post(f"/procurement/rfqs/{rfq['id']}/award", json=pick, headers=w["admin"]["h"])
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "reason_needed"
    assert (await client.get("/procurement/orders", headers=w["admin"]["h"])).json()["items"] == []
    ok = await client.post(f"/procurement/rfqs/{rfq['id']}/award", json={**pick, "reason": "Delivers tomorrow"},
                           headers=w["admin"]["h"])
    assert ok.status_code == 201, ok.text
    line = ok.json()["lines"][0]
    assert line["award_reason"] == "Delivers tomorrow" and line["awarded_quote_line_id"]


async def test_from_a_request_the_site_is_told_and_a_duplicate_undoes_the_whole_award(client, world, test_engine):
    w = world
    req = await client.post("/procurement/requests", headers=w["arun"]["h"], json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]),
        "lines": [{"material_id": w["cement"], "quantity": "200", "unit_id": w["units"]["bags"]}]})
    assert req.status_code == 201, req.text
    rfq = await client.post("/procurement/rfqs", headers=w["admin"]["h"], json={
        "request_id": req.json()["id"], "suppliers": ["Malabar Hardware", "KK Traders"]})
    assert rfq.status_code == 201, rfq.text
    rfq = rfq.json()
    assert rfq["request"]["ref"] == req.json()["ref"] and rfq["lines"][0]["request_line_id"]
    await _quote(client, w, rfq, "KK Traders", [{"material_id": w["cement"], "rate": "390"}])
    # Someone phones an order for cement meanwhile: the award is a possible duplicate, and saves nothing.
    po = await client.post("/procurement/orders", headers=w["admin"]["h"], json={
        "project_id": str(w["villa"]), "site_id": str(w["yard"]), "supplier": "Malabar Hardware", "confirm_duplicate": True,
        "lines": [{"material_id": w["cement"], "quantity": "50", "unit_id": w["units"]["bags"]}]})
    assert po.status_code == 201, po.text
    dup = await client.post(f"/procurement/rfqs/{rfq['id']}/award", json={"mode": "lowest_per_line"}, headers=w["admin"]["h"])
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "possible_duplicate"
    assert (await client.get(f"/procurement/rfqs/{rfq['id']}", headers=w["admin"]["h"])).json()["status"] == "open"
    ok = await client.post(f"/procurement/rfqs/{rfq['id']}/award", json={"mode": "lowest_per_line", "confirm_duplicate": True},
                           headers=w["admin"]["h"])
    assert ok.status_code == 201, ok.text
    asked = (await client.get(f"/procurement/requests/{req.json()['id']}", headers=w["admin"]["h"])).json()
    assert asked["status"] == "ordered"


async def test_site_roles_see_who_quoted_not_rates_and_cannot_write_and_other_companies_see_nothing(client, world, test_engine):
    w = world
    rfq = await _quoted(client, w)
    seen = await client.get(f"/procurement/rfqs/{rfq['id']}", headers=w["arun"]["h"])
    assert seen.status_code == 200
    body = seen.json()
    assert body["lowest_total"] is None and all(set(q) == {"rfq_vendor_id", "lowest"} for q in body["lines"][0]["quotes"])
    assert all(s["total"] is None for s in body["suppliers"])
    assert (await client.post("/procurement/rfqs", json=_new(w), headers=w["arun"]["h"])).status_code == 403
    assert (await client.get(f"/procurement/rfqs/{rfq['id']}", headers=w["ravi"]["h"])).status_code == 404  # other project
    other = uuid.uuid4()
    await _exec(test_engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, "
                "updated_at) VALUES (:id, 'Other', 'local', 'default', 'active', now(), now())", id=other)
    stranger = await _user(test_engine, other, "admin", "Stranger")
    assert (await client.get(f"/procurement/rfqs/{rfq['id']}", headers=stranger["h"])).status_code == 404
    assert (await client.get("/procurement/rfqs", headers=stranger["h"])).json()["items"] == []


# PRC-51: the supplier's price list -- newest quote per material (live or expired) and its last paid rate (Rates rule).

async def _vendor_id(client, w, name: str) -> str:
    items = (await client.get("/finance/vendors", headers=w["admin"]["h"])).json()
    items = items["items"] if isinstance(items, dict) else items
    return next(v["id"] for v in items if v["name"] == name)


async def test_price_list_shows_live_and_expired_quotes_and_the_last_paid_rate(client, world, test_engine):
    w = world
    await _quoted(client, w)
    malabar, kk = await _vendor_id(client, w, "Malabar Hardware"), await _vendor_id(client, w, "KK Traders")
    resp = await client.post("/materials/inflows", headers=w["admin"]["h"], json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]), "material_id": w["cement"],
        "unit_id": w["units"]["bags"], "quantity": "50", "movement_reason": "RECEIVED", "occurred_date": str(company_today()),
        "unit_cost": "400", "vendor_id": malabar})
    assert resp.status_code == 201, resp.text
    # KK's quote had no "valid until": live 30 days after it was recorded; once it is older, expired.
    await _exec(test_engine, "UPDATE rfq_vendors SET quoted_at = now() - interval '40 days' WHERE vendor_id = :v", v=uuid.UUID(kk))
    await _exec(test_engine, "UPDATE rfq_vendors SET valid_until = :d WHERE vendor_id = :v", v=uuid.UUID(malabar),
                d=company_today())

    mine = await client.get(f"/procurement/rates/suppliers/{malabar}", headers=w["admin"]["h"])
    assert mine.status_code == 200, mine.text
    rows = {r["material_name"]: r for r in mine.json()["items"]}
    cement = rows["Cement OPC 53"]
    assert (cement["quoted"]["rate_entered"], cement["quoted"]["rate"], cement["quoted"]["live"], cement["quoted"]["rfq_ref"]) == (
        "472.00", "368.75", True, "RFQ-0001")  # valid until today (still live); costs 368.75 before GST, claimed back
    assert cement["quoted"]["valid_until"] == str(company_today()) and cement["quoted"]["gst_percent"] == "28"
    assert (cement["paid"]["rate"], cement["paid"]["date"]) == ("400.00", str(company_today()))
    assert rows["TMT bar 12 mm"]["paid"] is None and rows["TMT bar 12 mm"]["quoted"]["gst_percent"] == "18"

    theirs = {r["material_name"]: r for r in (await client.get(f"/procurement/rates/suppliers/{kk}", headers=w["admin"]["h"])).json()["items"]}
    assert theirs["Cement OPC 53"]["quoted"]["live"] is False and theirs["Cement OPC 53"]["paid"] is None


async def test_price_list_without_quotes_rates_hidden_and_other_companies_not_found(client, world, test_engine):
    w = world
    steels = await _vendor_id(client, w, "Kerala Steels")
    empty = await client.get(f"/procurement/rates/suppliers/{steels}", headers=w["admin"]["h"])
    assert empty.status_code == 200 and empty.json()["items"] == []
    assert (await client.get(f"/procurement/rates/suppliers/{steels}", headers=w["arun"]["h"])).status_code == 403
    other = uuid.uuid4()
    await _exec(test_engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, "
                "updated_at) VALUES (:id, 'Other', 'local', 'default', 'active', now(), now())", id=other)
    stranger = await _user(test_engine, other, "admin", "Stranger")
    assert (await client.get(f"/procurement/rates/suppliers/{steels}", headers=stranger["h"])).status_code == 404
