"""PRC-48 stock count and PRC-49 stock value on a real Postgres (run with `pytest -m integration`).

Count: the book is frozen at the start, the site fills it (another unit converted, "not counted" allowed), each
difference needs a reason, the owner / admin approves and the differences post as ADJUSTMENT_IN / OUT so book equals
counted; an approved count takes no change; a site manager cannot approve. Value: on hand x the weighted average rate
(GST per D-CC8), slow-moving flagged, money roles only, the period report's section; another company sees nothing.
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
    "stock_count_lines", "stock_counts", "material_return_lines", "material_returns", "stock_levels", "notifications", "expense_payments", "expenses", "rfq_quote_lines", "rfq_vendors", "rfq_lines", "rfqs", "goods_receipt_lines",
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
    pm = await _user(test_engine, org, "project_manager", "Joseph", projects=[villa])
    units = {u["code"]: u["id"] for u in (await client.get("/materials/units-of-measure", headers=admin["h"])).json()["items"]}
    cement = (await client.post("/materials", json={"name": "Cement OPC 53", "default_unit_id": units["bags"]},
                                headers=admin["h"])).json()["id"]
    tmt = (await client.post("/materials", json={"name": "TMT bar 12 mm", "default_unit_id": units["kg"]},
                             headers=admin["h"])).json()["id"]
    vendors = {}
    for name in ("Malabar Hardware", "KK Traders"):
        vendors[name] = (await client.post("/finance/vendors", json={"name": name}, headers=admin["h"])).json()["id"]
    return {"org": org, "villa": villa, "block_a": block_a, "admin": admin, "arun": arun, "pm": pm, "units": units,
            "cement": cement, "tmt": tmt, "malabar": vendors["Malabar Hardware"], "kk": vendors["KK Traders"]}


async def _came(client, w, material, unit, qty, rate=None, vendor=None, **extra):
    body = {"project_id": str(w["villa"]), "site_id": str(w["block_a"]), "material_id": material, "unit_id": w["units"][unit],
            "quantity": qty, "occurred_date": str(company_today()), "movement_reason": "RECEIVED", "no_order": True, **extra}
    if rate:
        body.update(unit_cost=rate, vendor_id=vendor)
    resp = await client.post("/materials/inflows", headers=w["admin"]["h"], json=body)
    assert resp.status_code == 201, resp.text


async def _stock(client, w, material) -> str:
    got = (await client.get(f"/materials/stock-check?material_id={material}&site_id={w['block_a']}",
                            headers=w["admin"]["h"])).json()
    return f"{float(got['available']):g}"


async def test_a_count_approved_leaves_book_equal_to_counted(client, world):
    w = world
    await _came(client, w, w["cement"], "bags", "100", "400", w["malabar"])
    await _came(client, w, w["tmt"], "kg", "2000", "60", w["kk"])
    started = await client.post("/materials/stock-counts", headers=w["arun"]["h"], json={"site_id": str(w["block_a"])})
    assert started.status_code == 201, started.text
    sc = started.json()
    assert (sc["ref"], sc["counts"]["lines"], sc["counts"]["not_counted"]) == ("SC-0001", 2, 2)
    again = await client.post("/materials/stock-counts", headers=w["arun"]["h"], json={"site_id": str(w["block_a"])})
    assert again.status_code == 409  # one open count per site
    # Something is used after the start: the book stays frozen at 100.
    used = await client.post("/materials/outflows", headers=w["admin"]["h"], json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]), "material_id": w["cement"],
        "unit_id": w["units"]["bags"], "quantity": "5", "occurred_date": str(company_today())})
    assert used.status_code == 201
    # The site counts: cement 92 bags (8 short of the book), steel 2.1 tonnes (100 kg more), said in tonnes.
    filled = await client.put(f"/materials/stock-counts/{sc['id']}/lines", headers=w["arun"]["h"], json={"lines": [
        {"material_id": w["cement"], "counted": "92"},
        {"material_id": w["tmt"], "counted": "2.1", "unit_id": w["units"]["tons"], "reason": "wrong_entry"}]})
    assert filled.status_code == 200, filled.text
    by = {x["material"]: x for x in filled.json()["lines"]}
    assert (by["Cement OPC 53"]["difference"], by["TMT bar 12 mm"]["counted"], by["TMT bar 12 mm"]["difference"]) == (
        "-8", "2100", "100")
    # Site roles see no rupees; the office sees them, the largest first.
    assert "difference_value" not in by["Cement OPC 53"]
    office = (await client.get(f"/materials/stock-counts/{sc['id']}", headers=w["admin"]["h"])).json()
    assert [(x["material"], x["difference_value"]) for x in office["lines"]] == [
        ("TMT bar 12 mm", "6000.00"), ("Cement OPC 53", "-3200.00")]
    assert (office["net_value"], office["gross_value"]) == ("2800.00", "9200.00")
    assert (await client.post(f"/materials/stock-counts/{sc['id']}/approve", headers=w["pm"]["h"])).status_code == 403
    no_reason = await client.post(f"/materials/stock-counts/{sc['id']}/approve", headers=w["admin"]["h"])
    assert no_reason.status_code == 422 and "Cement OPC 53" in no_reason.json()["detail"]
    await client.put(f"/materials/stock-counts/{sc['id']}/lines", headers=w["arun"]["h"], json={
        "lines": [{"material_id": w["cement"], "counted": "92", "reason": "wastage"}]})
    done = await client.post(f"/materials/stock-counts/{sc['id']}/approve", headers=w["admin"]["h"])
    assert done.status_code == 200, done.text and done.json()["status"] == "approved"
    # Book = counted (minus the 5 used after the count started).
    assert (await _stock(client, w, w["cement"]), await _stock(client, w, w["tmt"])) == ("87", "2100")
    late = await client.put(f"/materials/stock-counts/{sc['id']}/lines", headers=w["arun"]["h"],
                            json={"lines": [{"material_id": w["cement"], "counted": "90"}]})
    assert late.status_code == 409  # never edited after approval: a new count corrects it
    listed = (await client.get("/materials/stock-counts", headers=w["admin"]["h"])).json()
    assert listed["last_counted"] == {str(w["block_a"]): str(company_today())} and listed["due"] == []


async def test_stock_value_is_on_hand_at_the_weighted_average_rate(client, world, test_engine):
    w = world
    # Malabar has a GSTIN: 18% is claimed back, so its 100 bags cost 400. KK has none: 50 at 400 + 18% = 472.
    await client.patch(f"/finance/vendors/{w['malabar']}", headers=w["admin"]["h"], json={"gstin": "32ABCDE1234F1Z5"})
    await _came(client, w, w["cement"], "bags", "100", "400", w["malabar"], gst_percent="18", rate_includes_gst=False)
    await _came(client, w, w["cement"], "bags", "50", "400", w["kk"], gst_percent="18", rate_includes_gst=False)
    await _came(client, w, w["tmt"], "kg", "500", "60", w["kk"])
    await client.post("/materials/outflows", headers=w["admin"]["h"], json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]), "material_id": w["cement"],
        "unit_id": w["units"]["bags"], "quantity": "30", "occurred_date": str(company_today())})
    v = (await client.get("/materials/stock-value", headers=w["admin"]["h"])).json()
    by = {r["material"]: r for r in v["rows"]}
    # (100 x 400 + 50 x 472) / 150 = 424 a bag; 120 on hand.
    assert (by["Cement OPC 53"]["rate"], by["Cement OPC 53"]["value"], by["Cement OPC 53"]["slow_moving"]) == (
        "424.00", "50880.00", False)
    assert (by["TMT bar 12 mm"]["value"], by["TMT bar 12 mm"]["slow_moving"]) == ("30000.00", True)  # not used in 30 days
    assert (v["total"], v["slow_moving"], v["top"][0]["material"]) == ("80880.00", 1, "Cement OPC 53")
    assert (await client.get("/materials/stock-value", headers=w["arun"]["h"])).status_code == 403
    report = await client.get(f"/reports/period?project_id={w['villa']}&period=week&date={company_today()}", headers=w["admin"]["h"])
    assert report.status_code == 200, report.text
    assert report.json()["sections"]["stock_value"]["total"] == "80880.00"
    other = await _org(test_engine, "Other builder")
    stranger = await _user(test_engine, other, "admin", "Someone")
    assert (await client.get("/materials/stock-value", headers=stranger["h"])).json()["items"] == 0
    assert (await client.get("/materials/stock-counts", headers=stranger["h"])).json()["total"] == 0
