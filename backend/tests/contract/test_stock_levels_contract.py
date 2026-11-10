"""PRC-47: minimum stock and reorder on a real Postgres (run with `pytest -m integration`).

The office sets a minimum per site and material (typed, in another unit, from Excel, suggested from use); the Stock
rows carry it (below minimum, running low); what is below it is listed with the reorder quantity, and not alerted when
an open order, RFQ or request already buys it; the daily note goes once a day to the people who run the project with
the two draft links. Site roles see but cannot set; another company sees nothing.
"""

from __future__ import annotations

import datetime
import io
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
    "stock_levels", "notifications", "rfq_quote_lines", "rfq_vendors", "rfq_lines", "rfqs", "goods_receipt_lines",
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
    pm = await _user(test_engine, org, "project_manager", "Joseph", projects=[villa])
    arun = await _user(test_engine, org, "site_engineer", "Arun", projects=[villa])
    units = {u["code"]: u["id"] for u in (await client.get("/materials/units-of-measure", headers=admin["h"])).json()["items"]}
    cement = (await client.post("/materials", json={"name": "Cement OPC 53", "default_unit_id": units["bags"]},
                                headers=admin["h"])).json()["id"]
    sand = (await client.post("/materials", json={"name": "M-sand", "default_unit_id": units["cft"]},
                              headers=admin["h"])).json()["id"]
    tmt = (await client.post("/materials", json={"name": "TMT bar 12 mm", "default_unit_id": units["kg"]},
                             headers=admin["h"])).json()["id"]
    return {"org": org, "villa": villa, "block_a": block_a, "admin": admin, "pm": pm, "arun": arun, "units": units,
            "cement": cement, "sand": sand, "tmt": tmt}


async def _move(client, w, kind: str, material, unit, qty: str, day: datetime.date | None = None, **extra) -> None:
    body = {"project_id": str(w["villa"]), "site_id": str(w["block_a"]), "material_id": material, "unit_id": unit,
            "quantity": qty, "occurred_date": str(day or company_today()), **extra}
    if kind == "in":
        body.setdefault("movement_reason", "RECEIVED")
        body.setdefault("no_order", True)
    resp = await client.post(f"/materials/{'inflows' if kind == 'in' else 'outflows'}", json=body,
                             headers=w["admin"]["h"])
    assert resp.status_code == 201, resp.text


def _row(rows, material):
    return next(r for r in rows if r["material_id"] == material)


async def test_a_minimum_marks_the_stock_row_and_counts_as_running_low(client, world):
    w = world
    await _move(client, w, "in", w["cement"], w["units"]["bags"], "40")
    resp = await client.put("/materials/stock-levels", headers=w["pm"]["h"], json={
        "site_id": str(w["block_a"]), "material_id": w["cement"], "min_qty": "100", "reorder_qty": "200"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["said"] == "Minimum 100 bags of Cement OPC 53 at Block A, order 200 when below"
    rows = (await client.get("/materials/stock-summary", headers=w["admin"]["h"])).json()
    cement = _row(rows, w["cement"])
    assert (cement["min_qty"], cement["reorder_qty"], cement["below_min"], cement["running_low"]) == (
        "100.000", "200.000", True, True)  # nothing used, so only the minimum makes it low
    inventory = _row((await client.get("/materials/inventory", headers=w["admin"]["h"])).json(), w["cement"])
    assert inventory["below_min"] is True and inventory["min_qty"] == "100.000"
    # Guard: without a minimum nothing changes.
    await _move(client, w, "in", w["sand"], w["units"]["cft"], "300")
    sand = _row((await client.get("/materials/stock-summary", headers=w["admin"]["h"])).json(), w["sand"])
    assert (sand["min_qty"], sand["below_min"], sand["running_low"]) == (None, False, False)
    # Changing it, then 0 removes it.
    await client.put("/materials/stock-levels", headers=w["pm"]["h"],
                     json={"site_id": str(w["block_a"]), "material_id": w["cement"], "min_qty": "30"})
    assert _row((await client.get("/materials/stock-summary", headers=w["admin"]["h"])).json(), w["cement"])[
        "below_min"] is False
    gone = await client.put("/materials/stock-levels", headers=w["pm"]["h"],
                            json={"site_id": str(w["block_a"]), "material_id": w["cement"], "min_qty": "0"})
    assert gone.json()["removed"] is True
    assert (await client.get("/materials/stock-levels", headers=w["admin"]["h"])).json()["total"] == 0


async def test_a_minimum_said_in_another_unit_is_kept_in_the_stock_unit(client, world):
    w = world
    resp = await client.put("/materials/stock-levels", headers=w["admin"]["h"], json={
        "site_id": str(w["block_a"]), "material_id": w["tmt"], "min_qty": "2", "unit_id": w["units"]["tons"]})
    assert resp.status_code == 200, resp.text
    assert (resp.json()["min_qty"], resp.json()["unit"]) == ("2000", "kg")


async def test_below_minimum_lists_what_to_order_and_leaves_out_what_is_being_bought(client, world):
    w = world
    for material, unit, held in ((w["cement"], "bags", "40"), (w["sand"], "cft", "50"), (w["tmt"], "kg", "100")):
        await _move(client, w, "in", material, w["units"][unit], held)
    levels = [{"site_id": str(w["block_a"]), "material_id": w["cement"], "min_qty": "100"},
              {"site_id": str(w["block_a"]), "material_id": w["sand"], "min_qty": "200", "reorder_qty": "400"},
              {"site_id": str(w["block_a"]), "material_id": w["tmt"], "min_qty": "500"}]
    saved = await client.post("/materials/stock-levels/bulk", json={"levels": levels}, headers=w["admin"]["h"])
    assert saved.status_code == 200, saved.text
    # Steel is on an open order that brings it above the minimum.
    order = await client.post("/procurement/orders", headers=w["admin"]["h"], json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]), "supplier": "Kerala Steels",
        "lines": [{"material_id": w["tmt"], "quantity": "600", "unit_id": w["units"]["kg"]}]})
    assert order.status_code == 201, order.text
    # Sand: the site already asked for it.
    asked = await client.post("/procurement/requests", headers=w["arun"]["h"], json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]),
        "lines": [{"material_id": w["sand"], "quantity": "300", "unit_id": w["units"]["cft"]}]})
    assert asked.status_code == 201, asked.text
    got = (await client.get("/materials/stock-levels/below", headers=w["arun"]["h"])).json()
    by = {r["material"]: r for r in got["items"]}
    assert (by["Cement OPC 53"]["closing"], by["Cement OPC 53"]["to_order"], by["Cement OPC 53"]["covered_by"]) == (
        "40", "160", None)  # no reorder qty: back to twice the minimum
    assert by["M-sand"]["covered_by"] == "REQ-0001" and by["TMT bar 12 mm"]["covered_by"] == "on order"
    assert got["not_covered"] == 1
    assert got["sites"] == [{"site_id": str(w["block_a"]), "site_name": "Block A", "project_id": str(w["villa"]),
                             "project_name": "Villa Kakkanad", "items": 3,
                             "to_buy": [{"material_id": w["cement"], "unit_id": w["units"]["bags"], "quantity": "160"}]}]


async def test_suggest_from_use_is_a_week_plus_the_lead_time(client, world):
    w = world
    today = company_today()
    await _move(client, w, "in", w["cement"], w["units"]["bags"], "100", today - datetime.timedelta(days=10))
    for back in range(7):
        await _move(client, w, "out", w["cement"], w["units"]["bags"], "2", today - datetime.timedelta(days=back))
    got = (await client.get(f"/materials/stock-levels/suggest?site_id={w['block_a']}", headers=w["pm"]["h"])).json()
    assert [(i["material"], i["used_last_week"], i["lead_days"], i["min_qty"], i["reorder_qty"]) for i in got["items"]] == [
        ("Cement OPC 53", "14", 2, "18", "28")]  # 2 a day x (7 + 2 days lead); two weeks' use to order


async def test_the_daily_note_goes_once_with_the_draft_links(client, world, test_engine):
    from mesiri.domains.materials.stock_levels import queue_reorder_reminders

    w = world
    await _move(client, w, "in", w["cement"], w["units"]["bags"], "40")
    await client.put("/materials/stock-levels", headers=w["admin"]["h"],
                     json={"site_id": str(w["block_a"]), "material_id": w["cement"], "min_qty": "100"})
    async with test_engine.begin() as conn:
        assert await queue_reorder_reminders(conn, w["org"], company_today()) == 2  # Meera (admin), Joseph (PM)
        assert await queue_reorder_reminders(conn, w["org"], company_today()) == 0  # once a day
        notes = (await conn.execute(sa.text("SELECT recipient_user_id, payload FROM notifications "
                                            "WHERE rule_key = 'stock_below_minimum'"))).all()
    assert {n.recipient_user_id for n in notes} == {w["admin"]["id"], w["pm"]["id"]}  # never the site engineer
    message = notes[0].payload["message"]
    assert "1 item below minimum at Block A" in message and "Cement OPC 53 40 bags (min 100), order 160" in message
    assert f"reorder={w['block_a']}&make=request" in message and f"reorder={w['block_a']}&make=rfq" in message


async def test_the_excel_sheet_sets_minimums_as_the_dashboard_does(client, world):
    from openpyxl import Workbook

    w = world
    book = Workbook()
    page = book.active
    page.title = "Minimum stock"
    page.append(["Project", "Site", "Item", "Minimum", "Reorder qty"])
    page.append(["", "Block A", "Cement OPC 53", 100, 250])
    page.append(["", "Block A", "Cement OPC 99", 10, None])
    page.append(["", "Block A", "M-sand", "lots", None])
    data = io.BytesIO()
    book.save(data)
    import base64

    resp = await client.post("/materials/import", headers=w["admin"]["h"],
                             json={"file_base64": base64.b64encode(data.getvalue()).decode()})
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["counts"]["Minimum stock"] == {"added": 1, "problem": 2}
    levels = (await client.get("/materials/stock-levels", headers=w["admin"]["h"])).json()["items"]
    assert [(x["material"], x["min_qty"], x["reorder_qty"], x["set_how"]) for x in levels] == [
        ("Cement OPC 53", "100", "250", "excel")]


async def test_site_roles_cannot_set_and_another_company_sees_nothing(client, world, test_engine):
    w = world
    body = {"site_id": str(w["block_a"]), "material_id": w["cement"], "min_qty": "100"}
    assert (await client.put("/materials/stock-levels", headers=w["arun"]["h"], json=body)).status_code == 403
    assert (await client.put("/materials/stock-levels", headers=w["admin"]["h"], json=body)).status_code == 200
    other = await _org(test_engine, "Other builder")
    stranger = await _user(test_engine, other, "admin", "Someone")
    assert (await client.get("/materials/stock-levels", headers=stranger["h"])).json()["total"] == 0
    assert (await client.get("/materials/stock-levels/below", headers=stranger["h"])).json()["total"] == 0
    assert (await client.put("/materials/stock-levels", headers=stranger["h"], json=body)).status_code == 404
    assert (await client.get(f"/materials/stock-levels/suggest?site_id={w['block_a']}",
                             headers=stranger["h"])).status_code == 404
