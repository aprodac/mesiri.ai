"""Contract tests for client billing (NXT-01 clients and contracts, NXT-02 RA bills).

Requires a live Postgres reachable via Settings().postgres.dsn() -- run with
`pytest -m integration`. Fixtures mirror test_materials_api_contract.py.
"""

from __future__ import annotations

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


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def clean_db(test_engine: AsyncEngine):
    yield
    # Bills hold their BOQ lines (RESTRICT): other suites delete every BOQ row when they start.
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM client_receipts"))  # NXT-03: they hold their bill (RESTRICT)
        await conn.execute(sa.text("DELETE FROM ra_bills"))


@pytest.fixture
async def client(test_engine: AsyncEngine, monkeypatch, clean_db):
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    app = create_app()

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


async def _org(engine) -> uuid.UUID:
    org_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
                "VALUES (:id, 'Billing Org', 'local', 'default', 'active', now(), now())"
            ),
            {"id": org_id},
        )
    return org_id


async def _user(engine, org_id, role: str, policy: str = '{"mode": "all_projects", "projects": []}') -> str:
    user_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, "
                "access_policy, created_at, updated_at) VALUES (:id, :org, :email, 'hash', 'T', :role, "
                "'active', CAST(:policy AS jsonb), now(), now())"
            ),
            {"id": user_id, "org": org_id, "email": f"{uuid.uuid4().hex[:8]}@example.com", "role": role, "policy": policy},
        )
    return create_access_token(data={"sub": str(user_id), "org": str(org_id), "role": role})


async def _project(engine, org_id) -> uuid.UUID:
    project_id, site_id = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                "VALUES (:id, :org, 'Villa Kakkanad', now(), now())"
            ),
            {"id": project_id, "org": org_id},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO sites (id, project_id, organization_id, name, status, created_at, updated_at) "
                "VALUES (:id, :p, :org, 'Main building', 'active', now(), now())"
            ),
            {"id": site_id, "p": project_id, "org": org_id},
        )
    return project_id


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def ctx(test_engine):
    org = await _org(test_engine)
    return {"org": org, "project": await _project(test_engine, org), "admin": await _user(test_engine, org, "admin")}


async def _section(client, ctx, name="Plastering", **extra) -> dict:
    r = await client.post(f"/projects/{ctx['project']}/boq/sections", json={"name": name, **extra}, headers=_h(ctx["admin"]))
    assert r.status_code == 201, r.text
    return r.json()


async def _add_line(client, ctx, section_id, **body) -> dict:
    r = await client.post(
        f"/projects/{ctx['project']}/boq/sections/{section_id}/lines", json=body, headers=_h(ctx["admin"])
    )
    assert r.status_code == 201, r.text


async def test_contract_terms_with_a_new_client_then_an_existing_one(client, ctx, test_engine):
    url, h = f"/projects/{ctx['project']}/contract", _h(ctx["admin"])
    r = (await client.get(url, headers=h)).json()
    assert r["contract"] is None and r["project"]["name"] == "Villa Kakkanad"

    terms = {"contract_value": "8500000", "retention_pct": "5", "mobilisation_advance": "850000",
             "advance_recovery_pct": "10", "gst_pct": "18", "tds_pct": "2", "defect_liability_months": 12,
             "signed_on": "2026-11-01", "contract_no": "KV/2026/14"}
    r = await client.put(url, json={**terms, "new_client": {"name": "Mr. Thomas", "gstin": "32abcde1234f1z5"}}, headers=h)
    assert r.status_code == 200, r.text
    c = r.json()["contract"]
    assert c["client_name"] == "Mr. Thomas" and c["contract_value"] == "8500000.00" and c["retention_pct"] == "5.00"
    async with test_engine.begin() as conn:
        shown = (await conn.execute(sa.text("SELECT client FROM projects WHERE id = :p"), {"p": ctx["project"]})).scalar()
    assert shown == "Mr. Thomas"  # the name shown across the app follows the contract's client

    clients = (await client.get("/billing/clients", headers=h)).json()
    assert [(x["name"], x["gstin"], [p["contract_value"] for p in x["projects"]]) for x in clients] == [
        ("Mr. Thomas", "32ABCDE1234F1Z5", ["8500000.00"])]
    # The same name again is refused; picking the saved client works; terms not sent become empty.
    again = await client.put(url, json={"new_client": {"name": "mr. thomas"}}, headers=h)
    assert again.status_code == 409
    r = (await client.put(url, json={"client_id": clients[0]["id"], "contract_value": "9000000"}, headers=h)).json()
    assert r["contract"]["contract_value"] == "9000000.00" and r["contract"]["retention_pct"] is None


async def test_contract_validation_and_who_may_see_it(client, ctx, test_engine):
    url, h = f"/projects/{ctx['project']}/contract", _h(ctx["admin"])
    for body in ({"retention_pct": "101"}, {"contract_value": "-1"}, {"new_client": {"name": "X", "gstin": "123"}},
                 {"contract_value": "100", "mobilisation_advance": "200"}, {"client_id": str(uuid.uuid4())}):
        assert (await client.put(url, json=body, headers=h)).status_code == 422, body
    for role, code in (("finance", 200), ("project_manager", 403), ("site_engineer", 403)):
        token = await _user(test_engine, ctx["org"], role)
        assert (await client.get(url, headers=_h(token))).status_code == code, role
        assert (await client.get("/billing/clients", headers=_h(token))).status_code == code, role
    assert (await client.get(f"/projects/{uuid.uuid4()}/contract", headers=h)).status_code == 404


async def test_client_details_change_and_names_stay_unique(client, ctx):
    h = _h(ctx["admin"])
    a = (await client.post("/billing/clients", json={"name": "Abdullakutty", "phone": "98470 00000"}, headers=h)).json()
    await client.post("/billing/clients", json={"name": "Kaleido"}, headers=h)
    r = await client.patch(f"/billing/clients/{a['id']}", json={"name": "Kaleido"}, headers=h)
    assert r.status_code == 409
    r = await client.patch(f"/billing/clients/{a['id']}", json={"address": "Kondotty"}, headers=h)
    assert r.json()["address"] == "Kondotty" and r.json()["phone"] == "98470 00000"


async def test_project_start_lists_the_contract_step_without_money(client, ctx):
    h = _h(ctx["admin"])
    steps = (await client.get(f"/projects/{ctx['project']}/start", headers=h)).json()["steps"]
    step = next(s for s in steps if s["key"] == "contract")
    assert step["done"] is False and [s["key"] for s in steps][:2] == ["dates", "contract"]
    await client.put(f"/projects/{ctx['project']}/contract", json={"contract_value": "100"}, headers=h)
    step = next(s for s in (await client.get(f"/projects/{ctx['project']}/start", headers=h)).json()["steps"]
                if s["key"] == "contract")
    assert step["done"] is True and "100" not in step["detail"]


# -- NXT-02: RA bills -----------------------------------------------------------------------------------------------

async def _measured(client, ctx, engine, line_id: str, quantity: str, unit: str) -> None:
    """Site work on a BOQ line (a work update with a quantity, put on the line as the BOQ page does)."""
    activity_id, quantity_id = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        site = (await conn.execute(sa.text("SELECT id FROM sites WHERE project_id = :p"), {"p": ctx["project"]})).scalar_one()
        unit_id = (await conn.execute(sa.text("SELECT id FROM units_of_measure WHERE code = :u"), {"u": unit})).scalar_one()
        await conn.execute(sa.text(
            "INSERT INTO activities (id, organization_id, project_id, site_id, work_type, activity_date, source) "
            "VALUES (:id, :org, :p, :s, 'work', current_date, 'dashboard')"),
            {"id": activity_id, "org": ctx["org"], "p": ctx["project"], "s": site})
        await conn.execute(sa.text(
            "INSERT INTO activity_quantities (id, activity_id, unit_id, quantity, planned_item_id) "
            "VALUES (:id, :a, :u, :q, :line)"),
            {"id": quantity_id, "a": activity_id, "u": unit_id, "q": Decimal(quantity), "line": line_id})


async def _boq(client, ctx) -> tuple[dict, dict]:
    h, base = _h(ctx["admin"]), f"/projects/{ctx['project']}/boq"
    sec = (await client.post(f"{base}/sections", json={"name": "Structure"}, headers=h)).json()
    m20 = (await client.post(f"{base}/sections/{sec['id']}/lines", json={
        "work": "M20 in slab", "unit": "cum", "planned_quantity": "300", "client_rate": "6500"}, headers=h)).json()
    plaster = (await client.post(f"{base}/sections/{sec['id']}/lines", json={
        "work": "Plaster 12 mm", "unit": "sqm", "planned_quantity": "4000", "client_rate": "420"}, headers=h)).json()
    await client.post(f"{base}/sections/{sec['id']}/lines", json={
        "work": "Not priced yet", "unit": "nos", "planned_quantity": "5"}, headers=h)
    await client.put(f"/projects/{ctx['project']}/contract", json={
        "contract_value": "25000000", "retention_pct": "5", "mobilisation_advance": "850000",
        "advance_recovery_pct": "10", "gst_pct": "18", "tds_pct": "2"}, headers=h)
    return m20, plaster


async def test_ra_bill_from_measured_work_with_the_contracts_deductions(client, ctx, test_engine):
    h = _h(ctx["admin"])
    m20, plaster = await _boq(client, ctx)
    nothing = await client.post(f"/projects/{ctx['project']}/ra-bills", json={}, headers=h)
    assert nothing.status_code == 422  # no measured work yet
    await _measured(client, ctx, test_engine, m20["id"], "120", "cum")
    await _measured(client, ctx, test_engine, plaster["id"], "800", "sqm")

    r = await client.post(f"/projects/{ctx['project']}/ra-bills", json={"bill_date": "2026-11-08"}, headers=h)
    assert r.status_code == 201, r.text
    bill = r.json()
    assert bill["ref"] == "RA-01" and bill["status"] == "draft"
    assert [(ln["work"], ln["quantity"], ln["amount"]) for ln in bill["lines"]] == [
        ("M20 in slab", "120.000", "780000.00"), ("Plaster 12 mm", "800.000", "336000.00")]
    assert (bill["gross"], bill["retention"], bill["advance_recovery"], bill["gst"], bill["tds"], bill["net"]) == (
        "1116000.00", "55800.00", "111600.00", "200880.00", "22320.00", "1127160.00")
    again = await client.post(f"/projects/{ctx['project']}/ra-bills", json={}, headers=h)
    assert again.status_code == 409  # one draft at a time

    # The office changes a quantity before submitting; the suggested one stays visible.
    plaster_line = bill["lines"][1]["id"]
    r = await client.put(f"/billing/ra-bills/{bill['id']}/lines/{plaster_line}", json={"quantity": "700"}, headers=h)
    line = r.json()["lines"][1]
    assert line["edited"] is True and line["suggested_quantity"] == "800.000" and r.json()["gross"] == "1074000.00"
    r = await client.post(f"/billing/ra-bills/{bill['id']}/submit", headers=h)
    assert r.json()["status"] == "submitted" and r.json()["net"] is not None
    assert (await client.put(f"/billing/ra-bills/{bill['id']}/lines/{plaster_line}", json={"quantity": "1"},
                             headers=h)).status_code == 409

    # RA-02: only what was measured since, plus the 100 sqm left off RA-01; the advance recovery continues.
    await _measured(client, ctx, test_engine, m20["id"], "30", "cum")
    two = (await client.post(f"/projects/{ctx['project']}/ra-bills", json={}, headers=h)).json()
    assert two["ref"] == "RA-02"
    assert [(ln["work"], ln["previous_quantity"], ln["quantity"]) for ln in two["lines"]] == [
        ("M20 in slab", "120.000", "30.000"), ("Plaster 12 mm", "700.000", "100.000")]
    assert two["previous_billed"] == "1074000.00"


async def test_advance_recovery_stops_at_the_advance(client, ctx, test_engine):
    h = _h(ctx["admin"])
    m20, _ = await _boq(client, ctx)
    await client.put(f"/projects/{ctx['project']}/contract", json={
        "mobilisation_advance": "100000", "advance_recovery_pct": "10"}, headers=h)
    await _measured(client, ctx, test_engine, m20["id"], "120", "cum")  # 7,80,000: 10% = 78,000
    one = (await client.post(f"/projects/{ctx['project']}/ra-bills", json={}, headers=h)).json()
    assert one["advance_recovery"] == "78000.00" and one["retention"] == "0.00"
    await client.post(f"/billing/ra-bills/{one['id']}/submit", headers=h)
    await _measured(client, ctx, test_engine, m20["id"], "120", "cum")
    two = (await client.post(f"/projects/{ctx['project']}/ra-bills", json={}, headers=h)).json()
    assert two["advance_recovery"] == "22000.00"  # only what is left of the advance


async def test_certify_cancel_remove_and_the_boq_keeps_billed_lines(client, ctx, test_engine):
    h = _h(ctx["admin"])
    m20, plaster = await _boq(client, ctx)
    await _measured(client, ctx, test_engine, m20["id"], "10", "cum")
    bill = (await client.post(f"/projects/{ctx['project']}/ra-bills", json={}, headers=h)).json()
    assert (await client.post(f"/billing/ra-bills/{bill['id']}/certify", json={"certified_amount": "1"},
                              headers=h)).status_code == 409  # a draft is not certified
    assert (await client.delete(f"/projects/{ctx['project']}/boq/lines/{m20['id']}", headers=h)).status_code == 409
    assert (await client.delete(f"/billing/ra-bills/{bill['id']}", headers=h)).status_code == 204

    bill = (await client.post(f"/projects/{ctx['project']}/ra-bills", json={}, headers=h)).json()
    assert bill["ref"] == "RA-01"  # a removed draft frees its number
    await client.post(f"/billing/ra-bills/{bill['id']}/submit", headers=h)
    r = (await client.post(f"/billing/ra-bills/{bill['id']}/certify", json={"certified_amount": "60000",
                                                                            "certified_on": "2026-11-20"}, headers=h)).json()
    assert (r["status"], r["certified_amount"], r["certified_on"]) == ("certified", "60000.00", "2026-11-20")
    assert (await client.post(f"/billing/ra-bills/{bill['id']}/cancel", headers=h)).status_code == 409

    await _measured(client, ctx, test_engine, m20["id"], "5", "cum")
    two = (await client.post(f"/projects/{ctx['project']}/ra-bills", json={}, headers=h)).json()
    await client.post(f"/billing/ra-bills/{two['id']}/submit", headers=h)
    assert (await client.post(f"/billing/ra-bills/{two['id']}/cancel", headers=h)).json()["status"] == "cancelled"
    three = (await client.post(f"/projects/{ctx['project']}/ra-bills", json={}, headers=h)).json()
    assert three["ref"] == "RA-03" and three["lines"][0]["quantity"] == "5.000"  # a withdrawn bill's work is free again

    listed = (await client.get(f"/billing/ra-bills?project_id={ctx['project']}", headers=h)).json()
    assert [b["ref"] for b in listed] == ["RA-03", "RA-02", "RA-01"] and listed[0]["net"] is not None
    pm = await _user(test_engine, ctx["org"], "project_manager")
    assert (await client.get(f"/billing/ra-bills/{bill['id']}", headers=_h(pm))).status_code == 403


async def test_bill_needs_contract_terms_and_says_what_it_cannot_bill(client, ctx, test_engine):
    """A bill is never made without the contract's terms; unpriced work, work in another unit and billing more
    than is measured are said on the bill, never dropped silently."""
    h, base = _h(ctx["admin"]), f"/projects/{ctx['project']}/boq"
    sec = (await client.post(f"{base}/sections", json={"name": "Finishes"}, headers=h)).json()
    tiles = (await client.post(f"{base}/sections/{sec['id']}/lines", json={
        "work": "Floor tiles", "unit": "sqm", "planned_quantity": "500", "client_rate": "950"}, headers=h)).json()
    paint = (await client.post(f"{base}/sections/{sec['id']}/lines", json={
        "work": "Painting", "unit": "sqm", "planned_quantity": "900"}, headers=h)).json()
    await _measured(client, ctx, test_engine, tiles["id"], "40", "sqm")
    await _measured(client, ctx, test_engine, tiles["id"], "100", "sqft")  # another unit
    await _measured(client, ctx, test_engine, paint["id"], "120", "sqm")  # no client rate
    r = await client.post(f"/projects/{ctx['project']}/ra-bills", json={}, headers=h)
    assert r.status_code == 422 and "contract terms" in r.json()["detail"]

    await client.put(f"/projects/{ctx['project']}/contract", json={"gst_pct": "18"}, headers=h)
    bill = (await client.post(f"/projects/{ctx['project']}/ra-bills", json={}, headers=h)).json()
    assert [ln["work"] for ln in bill["lines"]] == ["Floor tiles"]
    kinds = {w["kind"]: w["message"] for w in bill["warnings"]}
    assert "Painting: 120 sqm measured but the line has no client rate" in kinds["unpriced"]
    assert "Floor tiles: 1 work update recorded in another unit" in kinds["other_unit"]
    await client.post(f"/billing/ra-bills/{bill['id']}/submit", headers=h)

    # A site update removed after the bill went out: the bill says it now holds more than is measured.
    async with test_engine.begin() as conn:
        await conn.execute(sa.text(
            "UPDATE activities SET deleted_at = now() WHERE id IN (SELECT q.activity_id FROM activity_quantities q "
            "WHERE q.planned_item_id = :l AND q.quantity = 40)"), {"l": tiles["id"]})
    after = (await client.get(f"/billing/ra-bills/{bill['id']}", headers=h)).json()
    over = [w for w in after["warnings"] if w["kind"] == "overbilled"]
    assert over and "40 sqm billed so far but only 0 measured now" in over[0]["message"]



# -- NXT-03: money received and what clients owe --------------------------------------------------------------------


async def _account(engine, org, user_id=None) -> str:
    account = uuid.uuid4()
    async with engine.begin() as conn:
        creator = user_id or (await conn.execute(sa.text("SELECT id FROM users WHERE organization_id = :o LIMIT 1"),
                                                 {"o": org})).scalar_one()
        await conn.execute(sa.text(
            "INSERT INTO money_accounts (id, organization_id, account_type, name, opening_balance, opening_balance_date, "
            "created_by) VALUES (:id, :org, 'bank', 'HDFC current', 0, current_date - 90, :u)"),
            {"id": account, "org": org, "u": creator})
    return str(account)


async def test_money_received_settles_bills_oldest_first_and_an_advance_never(client, ctx, test_engine):
    h = _h(ctx["admin"])
    m20, plaster = await _boq(client, ctx)
    await _measured(client, ctx, test_engine, m20["id"], "120", "cum")
    await _measured(client, ctx, test_engine, plaster["id"], "800", "sqm")
    one = (await client.post(f"/projects/{ctx['project']}/ra-bills", json={"bill_date": "2026-09-01"}, headers=h)).json()
    assert (await client.post("/billing/receipts", headers=h, json={
        "ra_bill_id": one["id"], "amount": "100", "account_id": await _account(test_engine, ctx["org"])})).status_code == 409
    await client.post(f"/billing/ra-bills/{one['id']}/submit", headers=h)  # net 11,27,160
    account = await _account(test_engine, ctx["org"])

    r = await client.post("/billing/receipts", headers=h, json={
        "ra_bill_id": one["id"], "amount": "1000000", "account_id": account, "reference": "NEFT 778"})
    assert r.status_code == 201, r.text
    assert (r.json()["bill_ref"], r.json()["bill_left"]) == ("RA-01", "127160.00")
    too_much = await client.post("/billing/receipts", headers=h, json={
        "ra_bill_id": one["id"], "amount": "200000", "account_id": account})
    assert too_much.status_code == 422 and "on account" in too_much.json()["detail"]
    # The mobilisation advance is never applied to a bill (each bill recovers it); money on account is.
    await client.post("/billing/receipts", headers=h, json={
        "project_id": str(ctx["project"]), "kind": "advance", "amount": "850000", "account_id": account})
    on_acc = await client.post("/billing/receipts", headers=h, json={
        "project_id": str(ctx["project"]), "kind": "on_account", "amount": "27160", "account_id": account})
    assert on_acc.json()["project_left"] == "100000.00"

    owed = (await client.get("/billing/receivables", headers=h)).json()
    [row] = [c for c in owed["clients"] if c["outstanding"] != "0"]
    assert (row["outstanding"], row["advance_received"]) == ("100000.00", "850000.00")
    assert row["open_bills"][0]["ref"] == "RA-01" and row["open_bills"][0]["received"] == "1027160.00"
    assert owed["buckets"]["61_90"] == "100000.00"

    # Taking a receipt back puts it back on what is owed; the record stays.
    receipts = (await client.get("/billing/receipts", headers=h)).json()["receipts"]
    on_account = next(x for x in receipts if x["kind"] == "on_account")
    assert (await client.post(f"/billing/receipts/{on_account['id']}/cancel", headers=h)).json()["status"] == "cancelled"
    assert (await client.get("/billing/receivables", headers=h)).json()["outstanding"] == "127160.00"
    assert len((await client.get("/billing/receipts", headers=h)).json()["receipts"]) == 3

    pm = await _user(test_engine, ctx["org"], "PROJECT_MANAGER")
    for method, url in (("get", "/billing/receivables"), ("get", "/billing/receipts")):
        assert (await getattr(client, method)(url, headers=_h(pm))).status_code == 403
