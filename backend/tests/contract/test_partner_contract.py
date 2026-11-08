# ruff: noqa: F811 -- pytest fixtures imported from other contract tests are used as test arguments
"""NXT-16 (option B, approved by Alan 8 Nov 2026): a subcontractor's contact on Mesiri, on a real Postgres.

Deny by default: a contact's token is refused by every route outside /partner (a sweep of the whole app); /partner
answers only their own work orders and money, only while the contact, the subcontractor and the company's switch are
on; what they send waits for staff (a bill for the check, work for the engineer) and is never payable by itself.
"""

from __future__ import annotations

import re
import uuid

import pytest

from contract.test_rates_api_contract import _exec, client, world  # noqa: F401
from contract.test_subcontracts_contract import _wo
from contract.test_supplier_ledger_contract import _account, test_engine  # noqa: F401
from mesiri.domains.partner.router import partner_token

pytestmark = pytest.mark.integration


async def _setup(client, w):
    h = w["admin"]["h"]
    await client.patch("/finance/settings", headers=h, json={"partner_access": True})
    wo = await _wo(client, w, issue=True)
    c = await client.post(f"/finance/vendors/{wo['vendor_id']}/contacts", headers=h, json={"name": "Ravi", "phone": "98470 11111"})
    assert c.status_code == 201, c.text
    tok = partner_token(c.json()["id"], w["org"], wo["vendor_id"])
    return wo, c.json(), {"Authorization": f"Bearer {tok}"}


async def test_a_contact_sees_only_their_own_and_what_they_send_waits(client, world):
    w = world
    h = w["admin"]["h"]
    wo, contact, ph = await _setup(client, w)
    other = (await client.post("/subcontracts/work-orders", headers=h, json={
        "vendor_name": "Sajan Plastering", "project_id": str(w["villa"]), "issue": True,
        "lines": [{"description": "Plastering", "unit": "sqft", "quantity": "1000", "rate": "14"}]})).json()

    me = (await client.get("/partner/me", headers=ph)).json()
    assert me["subcontractor"] == "Ravi Concrete Team"
    mine = (await client.get("/partner/work-orders", headers=ph)).json()
    assert [x["ref"] for x in mine] == [wo["ref"]]
    assert set(mine[0]["lines"][0]) <= {"id", "description", "unit", "quantity", "rate", "amount", "measured", "proposed", "billed",
                                        "billed_amount", "remaining"}
    assert (await client.post("/partner/work-done", headers=ph, json={
        "work_order_id": other["id"], "line_id": other["lines"][0]["id"], "quantity": "10"})).status_code == 404

    # Work they report waits for the engineer; their bill waits for the check and cannot be paid.
    done = await client.post("/partner/work-done", headers=ph, json={"work_order_id": wo["id"], "line_id": wo["lines"][0]["id"], "quantity": "40"})
    assert done.status_code == 201 and "waiting" in done.json()["status"]
    staff_view = (await client.get(f"/subcontracts/work-orders/{wo['id']}", headers=h)).json()
    assert staff_view["lines"][0]["measured"] == "0" and staff_view["lines"][0]["proposed"] == "40"
    sent = await client.post("/partner/bills", headers=ph, json={"work_order_id": wo["id"], "lines": [{"line_id": wo["lines"][0]["id"], "quantity": "40"}],
                                                                "their_bill_no": "RC/9"})
    assert sent.status_code == 201, sent.text
    assert sent.json()["status"].startswith("waiting") and "nothing measured yet on Concreting M20" in sent.json()["check"]
    waiting = (await client.get("/subcontracts/bills/waiting", headers=h)).json()
    assert len(waiting) == 1 and waiting[0]["submitted_by_contact"] == contact["id"]
    bank = await _account(client, h, "SBI", "bank")
    assert (await client.post(f"/expenses/{waiting[0]['expense_id']}/payments", headers=h, json={"account_id": bank})).status_code == 409
    st = (await client.get("/partner/statement", headers=ph)).json()
    assert st["waiting_for_check"][0]["ref"] == "RA-1" and st["totals"]["payable_now"] == "0.00"

    # Confirming their work, then approving: payable to them as any bill.
    m = next(x for x in staff_view["measurements"] if x["status"] == "proposed")
    await client.post(f"/subcontracts/measurements/{m['id']}/confirm", headers=h, json={})
    ok = await client.post(f"/subcontracts/bills/{waiting[0]['id']}/approve", headers=h, json={"reason": "Checked on site"})
    assert ok.json()["bill"]["check_status"] == "approved"


async def test_switches_close_the_door(client, world):
    w = world
    h = w["admin"]["h"]
    wo, contact, ph = await _setup(client, w)
    assert (await client.get("/partner/me", headers=ph)).status_code == 200
    await client.patch(f"/finance/vendors/{wo['vendor_id']}/contacts/{contact['id']}", headers=h, json={"status": "inactive"})
    assert (await client.get("/partner/me", headers=ph)).status_code == 403
    await client.patch(f"/finance/vendors/{wo['vendor_id']}/contacts/{contact['id']}", headers=h, json={"status": "active"})
    await client.patch("/finance/settings", headers=h, json={"partner_access": False})
    assert (await client.get("/partner/me", headers=ph)).status_code == 403
    # A site engineer may not add a contact.
    assert (await client.post(f"/finance/vendors/{wo['vendor_id']}/contacts", headers=w["arun"]["h"],
                              json={"name": "X", "phone": "9847022222"})).status_code == 403   # a site engineer may not add


async def test_sweep_a_contact_token_is_refused_by_every_staff_route(client, world):
    """Every mounted route outside /partner: with a contact's token it must not succeed, unless it also succeeds with
    no token at all (a public route: login, health, ...)."""
    w = world
    wo, contact, ph = await _setup(client, w)
    app = client._transport.app  # noqa: SLF001
    leaked, checked = [], 0
    for route_path, ops in app.openapi()["paths"].items():
        if route_path.startswith("/partner"):
            continue
        path = re.sub(r"{[^}]+}", str(uuid.uuid4()), route_path)
        for method in ops:
            if method.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                continue
            checked += 1
            with_token = await client.request(method.upper(), path, headers=ph, json={})
            if 200 <= with_token.status_code < 300:
                without = await client.request(method.upper(), path, json={})
                if not 200 <= without.status_code < 300:
                    leaked.append(f"{method.upper()} {route_path} -> {with_token.status_code}")
    assert leaked == []
    assert checked > 150, checked  # the sweep really went through the app
    # and the one that matters most: the staff work order read
    assert (await client.get(f"/subcontracts/work-orders/{wo['id']}", headers=ph)).status_code == 401
