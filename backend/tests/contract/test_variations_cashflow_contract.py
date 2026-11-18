"""Contract tests for variations (NXT-04, CC-24) and the cash flow ahead (ACC-18 / MP-06).

Requires a live Postgres (``pytest -m integration``). The company, project, BOQ and measured-work helpers are the
billing contract tests' own.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from contract.test_billing_contract import (  # noqa: F401
    _account,
    _boq,
    _h,
    _measured,
    _org,
    _project,
    _user,
    client,
    test_engine,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def clean_db(test_engine: AsyncEngine):  # noqa: F811 -- replaces the billing file's own, adding variations
    yield
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM variations"))
        await conn.execute(sa.text("DELETE FROM client_receipts"))
        await conn.execute(sa.text("DELETE FROM ra_bills"))


@pytest.fixture
async def ctx(test_engine):  # noqa: F811
    org = await _org(test_engine)
    return {"org": org, "project": await _project(test_engine, org), "admin": await _user(test_engine, org, "admin")}


async def _boq_lines(client, ctx) -> list[dict]:  # noqa: F811
    boq = (await client.get(f"/projects/{ctx['project']}/boq", headers=_h(ctx["admin"]))).json()
    return [{**ln, "section": s["name"]} for s in boq["sections"] for ln in s["lines"]]


async def test_new_work_asked_sent_approved_becomes_a_boq_line_that_is_measured_and_billed(client, ctx, test_engine):  # noqa: F811
    h, p = _h(ctx["admin"]), ctx["project"]
    await _boq(client, ctx)
    r = await client.post(f"/projects/{p}/variations", headers=h, json={
        "title": "Extra balcony, first floor", "unit": "sqm", "quantity": "20", "client_rate": "3500",
        "cost_estimate": "52000", "days_added": 6, "asked_by": "Mr. Thomas"})
    assert r.status_code == 201, r.text
    vo = r.json()
    assert (vo["ref"], vo["status"], vo["amount"], vo["margin"], vo["margin_pct"]) == (
        "VO-01", "draft", "70000.00", "18000.00", "25.7")
    assert not [ln for ln in await _boq_lines(client, ctx) if ln["section"] == "Variations"]  # nothing until approved

    sent = (await client.post(f"/billing/variations/{vo['id']}/send", headers=h)).json()
    assert sent["status"] == "sent" and sent["sent_on"] is not None
    listed = (await client.get("/billing/variations", headers=h)).json()
    assert listed["summary"]["waiting"] == "70000.00" and listed["summary"]["counts"]["sent"] == 1

    ok = await client.post(f"/billing/variations/{vo['id']}/approve", headers=h,
                           json={"decided_by": "Mr. Thomas", "note": "On WhatsApp, 18 Nov"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved" and ok.json()["decided_by"] == "Mr. Thomas"
    line = next(ln for ln in await _boq_lines(client, ctx) if ln["section"] == "Variations")
    assert (line["boq_code"], line["work"], line["planned_quantity"], line["client_rate"]) == (
        "VO-01", "Extra balcony, first floor", "20.000", "3500.00")
    assert (await client.post(f"/billing/variations/{vo['id']}/approve", headers=h, json={})).status_code == 409

    # The site builds 12 sqm of it: it is measured on its line and the next RA bill takes it, like any line.
    await _measured(client, ctx, test_engine, line["id"], "12", "sqm")
    bill = (await client.post(f"/projects/{p}/ra-bills", json={"bill_date": "2026-11-18"}, headers=h)).json()
    assert ("Extra balcony, first floor", "12.000", "42000.00") in [(ln["work"], ln["quantity"], ln["amount"]) for ln in bill["lines"]]
    await client.post(f"/billing/ra-bills/{bill['id']}/submit", headers=h)
    after = (await client.get(f"/billing/variations/{vo['id']}", headers=h)).json()
    assert (after["done"], after["billed"], after["billed_amount"]) == ("12.000", "12.000", "42000.00")
    summary = (await client.get("/billing/variations", headers=h)).json()["summary"]
    assert (summary["approved"], summary["billed"], summary["days_added"]) == ("70000.00", "42000.00", 6)


async def test_more_of_a_boq_line_raises_its_quantity_as_a_revision(client, ctx, test_engine):  # noqa: F811
    h, p = _h(ctx["admin"]), ctx["project"]
    _m20, plaster = await _boq(client, ctx)
    r = await client.post(f"/projects/{p}/variations", headers=h, json={
        "kind": "more", "line_id": plaster["id"], "title": "Plaster the compound wall too", "quantity": "200"})
    assert r.status_code == 201, r.text
    vo = r.json()
    assert (vo["unit"], vo["client_rate"], vo["amount"], vo["line"]["work"]) == ("sqm", "420.00", "84000.00", "Plaster 12 mm")
    await client.post(f"/billing/variations/{vo['id']}/approve", headers=h, json={})
    line = next(ln for ln in await _boq_lines(client, ctx) if ln["work"] == "Plaster 12 mm")
    assert line["planned_quantity"] == "4200.000" and line["revision_no"] == 2
    async with test_engine.begin() as conn:
        reason = (await conn.execute(sa.text("SELECT revision_reason FROM work_package_planned_items WHERE id = :id"),
                                     {"id": line["id"]})).scalar_one()
    assert reason == "VO-01 approved by the client"  # the BOQ's own history says why it grew


async def test_the_rules_on_states_input_and_who(client, ctx, test_engine):  # noqa: F811
    h, p = _h(ctx["admin"]), ctx["project"]
    assert (await client.post(f"/projects/{p}/variations", headers=h, json={
        "title": "x", "unit": "furlongs", "quantity": "1", "client_rate": "1"})).status_code == 422
    assert (await client.post(f"/projects/{p}/variations", headers=h, json={
        "kind": "more", "title": "x", "quantity": "1"})).status_code == 422  # no line
    assert (await client.post(f"/projects/{p}/variations", headers=h, json={
        "title": "x", "unit": "nos", "quantity": "1"})).status_code == 422  # no rate

    sent = (await client.post(f"/projects/{p}/variations", headers=h, json={
        "title": "Extra door", "unit": "nos", "quantity": "1", "client_rate": "18000", "send": True})).json()
    assert sent["status"] == "sent" and sent["ref"] == "VO-01"
    assert (await client.delete(f"/billing/variations/{sent['id']}", headers=h)).status_code == 409
    edited = await client.patch(f"/billing/variations/{sent['id']}", headers=h, json={"client_rate": "20000"})
    assert edited.json()["amount"] == "20000.00"
    no = (await client.post(f"/billing/variations/{sent['id']}/reject", headers=h, json={"note": "Too dear"})).json()
    assert no["status"] == "rejected" and no["decision_note"] == "Too dear"
    assert (await client.patch(f"/billing/variations/{sent['id']}", headers=h, json={"quantity": "2"})).status_code == 409
    assert (await client.post(f"/billing/variations/{sent['id']}/cancel", headers=h)).status_code == 409

    draft = (await client.post(f"/projects/{p}/variations", headers=h, json={
        "title": "Grill", "unit": "nos", "quantity": "2", "client_rate": "5000"})).json()
    assert draft["ref"] == "VO-02"
    assert (await client.delete(f"/billing/variations/{draft['id']}", headers=h)).status_code == 204

    for role in ("project_manager", "site_engineer"):
        other = _h(await _user(test_engine, ctx["org"], role))
        assert (await client.get("/billing/variations", headers=other)).status_code == 403
        assert (await client.post(f"/projects/{p}/variations", headers=other, json={
            "title": "y", "unit": "nos", "quantity": "1", "client_rate": "1"})).status_code == 403


async def test_cash_flow_from_bills_work_and_cash_with_a_project_without_the_bank(client, ctx, test_engine, monkeypatch):  # noqa: F811
    from mesiri.domains.organizations import settings as org_settings

    async def every_module(request, organization_id):  # the books (and so the cash flow) are a module to switch on
        return list(org_settings.MODULES)

    monkeypatch.setattr("mesiri.domains.shared.modules.read_enabled_modules", every_module)
    h, p = _h(ctx["admin"]), ctx["project"]
    m20, plaster = await _boq(client, ctx)
    account = await _account(test_engine, ctx["org"])
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("UPDATE money_accounts SET opening_balance = 500000 WHERE id = :a"), {"a": account})
    await _measured(client, ctx, test_engine, m20["id"], "120", "cum")
    await _measured(client, ctx, test_engine, plaster["id"], "800", "sqm")
    async with test_engine.begin() as conn:
        today = (await conn.execute(sa.text("SELECT current_date"))).scalar_one()
    billed_on = today - datetime.timedelta(days=10)
    bill = (await client.post(f"/projects/{p}/ra-bills", json={"bill_date": billed_on.isoformat()}, headers=h)).json()
    await client.post(f"/billing/ra-bills/{bill['id']}/submit", headers=h)  # net 11,27,160
    await _measured(client, ctx, test_engine, m20["id"], "10", "cum")  # ₹65,000 of work on no bill yet

    # A supplier with 15 days' credit, billed 3 days ago: paid in 12 days; one with no credit set: 30 (the page's).
    malabar = (await client.post("/finance/vendors", json={"name": "Malabar Hardware", "credit_days": 15}, headers=h)).json()
    kerala = (await client.post("/finance/vendors", json={"name": "Kerala Steel"}, headers=h)).json()
    for vendor, amount in ((malabar, "80000"), (kerala, "25000")):
        r = await client.post("/expenses", headers={**h, "Idempotency-Key": str(uuid.uuid4())}, json={
            "project_id": str(p), "amount": amount, "category_text": "Materials", "vendor_id": vendor["id"],
            "occurred_date": (today - datetime.timedelta(days=3)).isoformat(), "description": f"Bill {amount}"})
        assert r.status_code == 201, r.text

    r = await client.get("/accounts/cash-flow", headers=h)
    assert r.status_code == 200, r.text
    cf = r.json()
    assert cf["opening"] == "500000.00" and cf["horizon"] == 8 and len(cf["weeks"]) == 8 and len(cf["accounts"]) == 1
    client_bill = next(i for i in cf["items"] if i["kind"] == "client_bills")
    assert client_bill["amount"] == "1127160.00"
    assert client_bill["date"] == (billed_on + datetime.timedelta(days=30)).isoformat()
    to_bill = next(i for i in cf["items"] if i["kind"] == "to_bill")
    assert to_bill["amount"] == "65000.00" and "to_bill" not in cf["default_on"]
    # The bill lands in its week (or after the weeks shown); the work not billed is left out of the totals.
    counted_in = sum((Decimal(w["in"]) for w in cf["weeks"]), Decimal(0)) + Decimal(cf["later"]["in"])
    assert counted_in == Decimal("1127160.00")
    assert Decimal(cf["weeks"][-1]["balance"]) == Decimal("500000.00") + sum((Decimal(w["net"]) for w in cf["weeks"]), Decimal(0))

    owed = {i["who"]: (i["amount"], i["date"], i["assumed"]) for i in cf["items"] if i["kind"] == "supplier_bills"}
    assert owed["Malabar Hardware"] == ("80000.00", (today + datetime.timedelta(days=12)).isoformat(), False)
    assert owed["Kerala Steel"] == ("25000.00", (today + datetime.timedelta(days=27)).isoformat(), True)

    faster = (await client.get("/accounts/cash-flow?client_days=7", headers=h)).json()
    assert next(i for i in faster["items"] if i["kind"] == "client_bills")["date"] == (
        billed_on + datetime.timedelta(days=7)).isoformat()

    one = (await client.get(f"/accounts/cash-flow?project_id={p}", headers=h)).json()
    assert one["opening"] is None and one["accounts"] == []

    pm = _h(await _user(test_engine, ctx["org"], "project_manager"))
    assert (await client.get("/accounts/cash-flow", headers=pm)).status_code == 403
