# ruff: noqa: F811 -- pytest fixtures imported from the rates contract test are used as test arguments
"""NXT-05/06/07, CC-04: subcontracts on a real Postgres (run with `pytest -m integration`).

A work order from the BOQ or typed; work measured (directly or a site work update counted on a line); a bill checked
against measured and agreed (passed -> payable after retention, advance recovered and TDS; flagged -> waits; approved
with a reason or rejected); a bill waiting or retention held is never paid; retention released; the statement. Who:
site engineers see quantities only, the office gives work orders, money roles bills, money managers advances.
"""

from __future__ import annotations

import datetime
import uuid

import pytest

from contract.test_rates_api_contract import _day, _exec, client, world  # noqa: F401
from contract.test_supplier_ledger_contract import (  # noqa: F401
    _account,
    _balance,
    _ledger,
    test_engine,
)

pytestmark = pytest.mark.integration


async def _wo(client, w, **extra) -> dict:
    body = {"vendor_name": "Ravi Concrete Team", "project_id": str(w["villa"]), "site_id": str(w["block_a"]),
            "name": "Slab concreting", "advance_agreed": "20000",
            "lines": [{"description": "Concreting M20", "unit": "m³", "quantity": "400", "rate": "380"},
                      {"description": "Shuttering", "unit": "sqm", "quantity": "1000", "rate": "45"}], **extra}
    r = await client.post("/subcontracts/work-orders", headers=w["admin"]["h"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _measure(client, w, wo, line, qty, who="admin"):
    r = await client.post(f"/subcontracts/work-orders/{wo['id']}/measurements", headers=w[who]["h"],
                          json={"line_id": wo["lines"][line]["id"], "quantity": qty})
    assert r.status_code == 201, r.text
    return r.json()


async def test_work_order_measure_bill_pay_retention(client, world, test_engine):
    w = world
    h = w["admin"]["h"]
    await client.patch("/finance/settings", headers=h, json={"tds_enabled": True})
    wo = await _wo(client, w, issue=True)
    assert (wo["ref"], wo["status"], wo["totals"]["value"], wo["retention_pct"]) == ("WO-0001", "issued", "197000.00", "5.00")
    bank = await _account(client, h, "SBI", "bank")
    adv = await client.post(f"/subcontracts/work-orders/{wo['id']}/advance", headers=h, json={"account_id": bank, "amount": "20000"})
    assert adv.status_code == 201 and adv.json()["totals"]["advance_left"] == "20000.00"

    # The site engineer measures; sees quantities, never rates or bills.
    m = await _measure(client, w, wo, 0, "40", who="arun")
    assert m["line"]["measured"] == "40"
    eng = (await client.get(f"/subcontracts/work-orders/{wo['id']}", headers=w["arun"]["h"])).json()
    assert eng["with_money"] is False and "rate" not in eng["lines"][0] and "bills" not in eng
    assert (await client.post(f"/subcontracts/work-orders/{wo['id']}/bills", headers=w["arun"]["h"],
                              json={"lines": [{"line_id": wo["lines"][0]["id"], "quantity": "40"}]})).status_code == 403

    # Bill 1: 40 m³ as measured, at the agreed rate -> passed; retention 5%, advance recovered pro rata, TDS 1%.
    preview = (await client.post(f"/subcontracts/work-orders/{wo['id']}/bills/check", headers=h,
                                 json={"lines": [{"line_id": wo["lines"][0]["id"], "quantity": "40"}]})).json()
    assert preview["status"] == "passed" and preview["gross"] == "15200.00"
    d = preview["deductions"]
    assert (d["retention"], d["tds"]) == ("760.00", "152.00")
    assert d["advance"] == "1543.15"   # 20,000 / 1,97,000 = 10.15% of 15,200
    bill = await client.post(f"/subcontracts/work-orders/{wo['id']}/bills", headers=h, json={
        "lines": [{"line_id": wo["lines"][0]["id"], "quantity": "40"}], "their_bill_no": "RC/7"})
    assert bill.status_code == 201, bill.text
    b1 = bill.json()["bill"]
    assert (b1["ref"], b1["check_status"], b1["tds_amount"], b1["retention_held"]) == ("RA-1", "passed", "152.00", "760.00")
    assert b1["payable_now"] == "12744.85"                        # 15,200 - 760 - 1,543.15 - 152

    # Bill 2: 30 m³ more than measured, and a higher rate -> flagged; never paid until approved.
    b2 = (await client.post(f"/subcontracts/work-orders/{wo['id']}/bills", headers=h, json={
        "lines": [{"line_id": wo["lines"][0]["id"], "quantity": "30", "rate": "400"}]})).json()["bill"]
    assert b2["check_status"] == "flagged"
    assert {f["code"] for f in b2["flags"]} == {"over_measured", "rate_above"}
    assert b2["payable_now"] == "0.00"
    refused = await client.post(f"/expenses/{b2['expense_id']}/payments", headers=h, json={"account_id": bank})
    assert refused.status_code == 409 and "check" in refused.text

    # Pay the supplier: only bill 1's payable part goes; bill 2 and the retention stay.
    paid = await client.post(f"/finance/vendors/{wo['vendor_id']}/payments", headers=h, json={"account_id": bank, "amount": "12744.85"})
    assert paid.status_code == 201, paid.text
    assert [x["expense_id"] for x in paid.json()["bills_paid"]] == [b1["expense_id"]]
    assert paid.json()["advance_left"] == "0.00"

    # Approve bill 2 with a reason (the extra was measured late): payable after its deductions.
    ok = await client.post(f"/subcontracts/bills/{b2['id']}/approve", headers=h, json={"reason": "Measured on Saturday, entry late"})
    assert ok.status_code == 200 and ok.json()["bill"]["check_status"] == "approved"
    wo_now = ok.json()["work_order"]
    assert wo_now["totals"]["retention_held"] == "1360.00"       # 5% of 15,200 + 12,000

    # Retention: released on completion, then payable.
    await client.post(f"/subcontracts/work-orders/{wo['id']}/complete", headers=h, json={})
    rel = await client.post(f"/subcontracts/work-orders/{wo['id']}/retention/release", headers=h, json={})
    assert rel.status_code == 200 and rel.json()["totals"]["retention_held"] == "0.00"

    st = (await client.get(f"/subcontracts/vendors/{wo['vendor_id']}/statement", headers=h)).json()
    assert st["totals"]["billed"] == "27200.00" and st["totals"]["tds"] == "272.00"
    led = await _ledger(client, h, wo["vendor_id"])
    tds_lines = [x for x in led["lines"] if x["kind"] == "payment" and "TDS" in x["detail"]]
    assert len(tds_lines) == 2


async def test_reject_takes_the_bill_back_and_lines_cannot_go_below_work_done(client, world):
    w = world
    h = w["admin"]["h"]
    wo = await _wo(client, w, issue=True)
    await _measure(client, w, wo, 1, "200")
    b = (await client.post(f"/subcontracts/work-orders/{wo['id']}/bills", headers=h, json={
        "lines": [{"line_id": wo["lines"][1]["id"], "quantity": "500"}]})).json()["bill"]
    assert b["check_status"] == "flagged"
    no = await client.post(f"/subcontracts/bills/{b['id']}/reject", headers=h, json={"reason": "Only 200 sqm done"})
    assert no.json()["bill"]["check_status"] == "rejected" and no.json()["work_order"]["lines"][1]["billed"] == "0"
    lines = [{"id": x["id"], "description": x["description"], "unit": x["unit"], "quantity": x["quantity"], "rate": x["rate"]}
             for x in wo["lines"]]
    lines[1]["quantity"] = "100"
    below = await client.patch(f"/subcontracts/work-orders/{wo['id']}", headers=h, json={"lines": lines})
    assert below.status_code == 409 and "200" in below.text
    lines[1]["quantity"] = "1200"
    more = await client.patch(f"/subcontracts/work-orders/{wo['id']}", headers=h, json={"lines": lines, "retention_pct": "10"})
    assert more.status_code == 200 and more.json()["lines"][1]["quantity"] == "1200"
    hist = (await client.get(f"/subcontracts/work-orders/{wo['id']}", headers=h)).json()["history"]
    assert any("1000 sqm" in x["what"] or "Shuttering" in x["what"] for x in hist)
    assert (await client.post(f"/subcontracts/work-orders/{wo['id']}/cancel", headers=h, json={})).status_code == 409


async def test_site_work_updates_count_on_a_line_once(client, world, test_engine):
    w = world
    h = w["admin"]["h"]
    wo = await _wo(client, w, issue=True)
    act, q = uuid.uuid4(), uuid.uuid4()
    await _exec(test_engine, "INSERT INTO activities (id, organization_id, project_id, site_id, work_type, activity_date, "
                "status, contractor, source, created_at, updated_at) VALUES (:id, :org, :p, :s, 'Concreting M20 slab', :d, "
                "'COMPLETED', 'Ravi team', 'whatsapp', now(), now())", id=act, org=w["org"], p=w["villa"], s=w["block_a"],
                d=datetime.date.fromisoformat(_day(1)))
    unit = (await (await client.get("/materials/units-of-measure", headers=h)).aread())
    import json as _json
    cum = next(u["id"] for u in _json.loads(unit)["items"] if u["code"] == "cum")
    await _exec(test_engine, "INSERT INTO activity_quantities (id, activity_id, unit_id, quantity) VALUES (:id, :a, :u, 35)",
                id=q, a=act, u=cum)
    found = (await client.get(f"/subcontracts/work-orders/{wo['id']}/site-work", headers=h)).json()
    assert found and found[0]["likely"] is True and found[0]["line_id"] == wo["lines"][0]["id"]
    counted = await client.post(f"/subcontracts/work-orders/{wo['id']}/site-work", headers=h,
                                json={"activity_quantity_id": found[0]["activity_quantity_id"], "line_id": wo["lines"][0]["id"]})
    assert counted.status_code == 201 and counted.json()["lines"][0]["measured"] == "35"
    again = await client.post(f"/subcontracts/work-orders/{wo['id']}/site-work", headers=h,
                              json={"activity_quantity_id": found[0]["activity_quantity_id"], "line_id": wo["lines"][0]["id"]})
    assert again.status_code == 409
    assert (await client.get(f"/subcontracts/work-orders/{wo['id']}/site-work", headers=h)).json() == []
