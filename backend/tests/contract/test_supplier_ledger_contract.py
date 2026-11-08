# ruff: noqa: F811 -- pytest fixtures imported from the rates contract test are used as test arguments
"""CC-09 / CC-10: the supplier ledger and paying suppliers, on a real Postgres (run with `pytest -m integration`).

Every rupee is owed once: a priced delivery until its bill comes, then the bill. A payment leaves the account once and
pays the oldest bills first; the rest stays with the supplier as an advance and pays the next bill without moving
money again. Undoing it opens the bills again and returns the money. An opening balance starts the ledger on its date.
Taking back an expense paid in parts returns every part. Delete is refused with history; merge moves everything.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contract.test_rates_api_contract import (  # noqa: F401 -- fixtures
    _TABLES,
    TODAY,
    _came,
    _day,
    _exec,
    _user,
    client,
    world,
)
from mesiri.bootstrap.settings import Settings

pytestmark = pytest.mark.integration


async def _wipe(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(sa.text("UPDATE material_usage SET reverses_movement_id = NULL"))
        await conn.execute(sa.text("UPDATE material_receipts SET reverses_movement_id = NULL, invoice_id = NULL"))
        await conn.execute(sa.text("UPDATE material_invoices SET expense_id = NULL"))
        await conn.execute(sa.text("UPDATE expense_payments SET advance_id = NULL"))
        await conn.execute(sa.text("DELETE FROM partner_audit"))
        for t in ("work_order_bill_lines", "work_order_bills", "work_order_measurements", "work_order_events",
                  "work_order_lines"):
            await conn.execute(sa.text(f"DELETE FROM {t}"))  # noqa: S608
        await conn.execute(sa.text("UPDATE expense_payments SET work_order_id = NULL"))
        await conn.execute(sa.text("UPDATE activity_quantities SET work_order_line_id = NULL"))
        await conn.execute(sa.text("DELETE FROM work_orders"))
        await conn.execute(sa.text("DELETE FROM vendor_contacts"))
        await conn.execute(sa.text("DELETE FROM activity_quantities"))
        await conn.execute(sa.text("DELETE FROM activities"))
        await conn.execute(sa.text("DELETE FROM organization_settings"))
        for table in _TABLES:
            if table == "sites":  # accounts point at sites and users
                await conn.execute(sa.text("DELETE FROM money_accounts"))
            await conn.execute(sa.text(f"DELETE FROM {table}"))  # noqa: S608 -- fixed names


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    await _wipe(engine)
    yield engine
    await _wipe(engine)
    await engine.dispose()


async def _account(client, h, name: str, kind: str, opening: str = "500000") -> str:
    r = await client.post("/finance/accounts", json={"name": name, "account_type": kind, "opening_balance": opening},
                          headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _balance(client, h, account_id: str) -> str:
    acc = next(a for a in (await client.get("/finance/accounts", headers=h)).json() if a["id"] == account_id)
    return f"{float(acc['current_balance']):.2f}"


async def _vendor(client, h, name: str, **extra) -> str:
    r = await client.post("/finance/vendors", json={"name": name, **extra}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _bill(client, w, vendor_id: str, amount: str, days_ago: int, project="villa") -> str:
    r = await client.post("/expenses", headers={**w["admin"]["h"], "Idempotency-Key": str(uuid.uuid4())}, json={
        "project_id": str(w[project]), "amount": amount, "category_text": "Materials", "vendor_id": vendor_id,
        "occurred_date": _day(days_ago), "description": f"Bill {amount}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _ledger(client, h, vendor_id: str, **params) -> dict:
    r = await client.get(f"/finance/vendors/{vendor_id}/ledger", params=params, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


async def test_owed_once_paid_oldest_first_advance_used_and_undone(client, world, test_engine):
    w = world
    h = w["admin"]["h"]
    bank = await _account(client, h, "SBI current", "bank")
    malabar = await _vendor(client, h, "Malabar Hardware", credit_days=30, kind="supplier")
    old_bill = await _bill(client, w, malabar, "10000", days_ago=40)                                  # overdue
    d1 = await _came(client, w, "cement", "100", "400", days_ago=10, vendor_id=malabar)                # 40,000
    d2 = await _came(client, w, "cement", "20", "410", days_ago=5, vendor_id=malabar, site="yard")     #  8,200

    led = await _ledger(client, h, malabar)
    assert led["closing"] == "58200.00"
    assert [x["kind"] for x in led["lines"]] == ["bill", "delivery", "delivery"]
    s = led["summary"]
    assert (s["unbilled"], s["unbilled_count"], s["bills_left"], s["overdue"]) == ("48200.00", 2, "10000.00", "10000.00")
    assert s["open_bills"][0]["overdue_days"] == 10 and s["open_bills"][0]["due"] == _day(10)
    pay = (await client.get("/finance/vendors/payables", headers=h)).json()
    row = next(v for v in pay["vendors"] if v["id"] == malabar)
    assert (row["balance"], pay["totals"]["payable"], pay["totals"]["overdue"]) == ("58200.00", "58200.00", "10000.00")
    assert (pay["buckets"]["31_60"], pay["buckets"]["0_30"]) == ("10000.00", "48200.00")

    # Pay 30,000: the old bill first, 20,000 stays as an advance. The money leaves once.
    paid = await client.post(f"/finance/vendors/{malabar}/payments", headers=h,
                             json={"account_id": bank, "amount": "30000", "reference": "UTR 991"})
    assert paid.status_code == 201, paid.text
    p = paid.json()
    assert (p["bills_paid"][0]["expense_id"], p["bills_paid"][0]["amount"], p["advance_left"]) == (old_bill, "10000.00", "20000.00")
    assert await _balance(client, h, bank) == "470000.00"
    txs = [t for t in (await client.get("/finance/transactions", headers=h)).json() if t["transaction_type"] == "expense_payment"]
    assert len(txs) == 1 and txs[0]["vendor_name"] == "Malabar Hardware" and txs[0]["expense_id"] is None
    one = (await client.get(f"/expenses/{old_bill}/payments", headers=h)).json()
    assert one["payment_status"] == "paid" and one["payments"][0]["from_advance"] is True
    assert (await _ledger(client, h, malabar))["closing"] == "28200.00"

    # The bill for both deliveries (48,500 with freight) replaces them: owed once, cost once.
    billed = await client.post(f"/finance/vendors/{malabar}/bills", headers=h, json={
        "receipt_ids": [d1["id"], d2["id"]], "amount": "48500", "bill_number": "MH/1", "bill_date": _day(2)})
    assert billed.status_code == 201, billed.text
    assert (billed.json()["deliveries_total"], billed.json()["difference"]) == ("48200.00", "300.00")
    bill2 = billed.json()["expense_id"]
    led = await _ledger(client, h, malabar)
    assert led["closing"] == "28500.00" and led["summary"]["unbilled_count"] == 0
    assert next(x for x in led["lines"] if x["kind"] == "bill" and x["links"]["expense_id"] == bill2)["detail"].startswith("Bill MH/1")
    costs = (await client.get("/finance/costs", params={"project_id": str(w["villa"]), "date_from": _day(60),
                                                     "date_to": _day(0)}, headers=h)).json()
    assert (costs["materials"]["amount"], costs["expenses"]["amount"]) == ("0.00", "58500.00")
    on_bill = (await client.get(f"/finance/vendors/{malabar}/bills/{bill2}/deliveries", headers=h)).json()
    assert {d["receipt_id"] for d in on_bill} == {d1["id"], d2["id"]}

    # The new bill can use the advance: paying it offers what is left.
    offer = (await client.get(f"/expenses/{bill2}/payments", headers=h)).json()["vendor_advance"]
    assert offer["left"] == "20000.00"
    used = await client.post(f"/finance/vendors/{malabar}/payments/{p['payment_id']}/apply", headers=h, json={})
    assert used.status_code == 200 and used.json()["advance_left"] == "0.00"
    assert (await client.get(f"/expenses/{bill2}/payments", headers=h)).json()["payment_status"] == "partially_paid"
    assert await _balance(client, h, bank) == "470000.00"          # no money moved
    assert (await _ledger(client, h, malabar))["closing"] == "28500.00"

    # Undo the payment: both bills open again, the money is back, once.
    undone = await client.post(f"/finance/vendors/{malabar}/payments/{p['payment_id']}/reverse", headers=h)
    assert undone.status_code == 200, undone.text
    assert await _balance(client, h, bank) == "500000.00"
    for bid in (old_bill, bill2):
        assert (await client.get(f"/expenses/{bid}/payments", headers=h)).json()["payment_status"] == "unpaid"
    assert (await _ledger(client, h, malabar))["closing"] == "58500.00"

    # A delivery put on the wrong bill goes back to being owed by itself.
    off = await client.delete(f"/finance/vendors/{malabar}/bills/{bill2}/deliveries/{d2['id']}", headers=h)
    assert off.status_code == 200
    assert (await _ledger(client, h, malabar))["summary"]["unbilled"] == "8200.00"


async def test_a_typed_bill_and_its_deliveries_are_linked_and_counted_once(client, world):
    w = world
    h = w["admin"]["h"]
    v = await _vendor(client, h, "Edappally Stores")
    d = await _came(client, w, "cement", "20", "410", days_ago=3, vendor_id=v)
    bill = await _bill(client, w, v, "8500", days_ago=2)                          # with freight: not certain, offered
    assert (await _ledger(client, h, v))["closing"] == "16700.00"                 # twice until linked
    linked = await client.post(f"/finance/vendors/{v}/bills/{bill}/deliveries", headers=h, json={"receipt_ids": [d["id"]]})
    assert linked.status_code == 200 and linked.json()["difference"] == "300.00"
    assert (await _ledger(client, h, v))["closing"] == "8500.00"
    costs = (await client.get("/finance/costs", params={"project_id": str(w["villa"])}, headers=h)).json()
    assert costs["total"] == "8500.00"
    again = await client.post(f"/finance/vendors/{v}/bills/{bill}/deliveries", headers=h, json={"receipt_ids": [d["id"]]})
    assert again.status_code == 409


async def test_opening_balance_starts_the_ledger_and_who_may_see_and_pay(client, world, test_engine):
    w = world
    h = w["admin"]["h"]
    v = await _vendor(client, h, "Kerala Steel")
    await _bill(client, w, v, "10000", days_ago=40)                         # before the start: inside the opening
    await _bill(client, w, v, "5000", days_ago=5, project="flats")
    set_ob = await client.patch(f"/finance/vendors/{v}", headers=h,
                                json={"opening_balance": "15000", "opening_balance_date": _day(20)})
    assert set_ob.status_code == 200 and set_ob.json()["opening_balance"] == "15000.00"
    led = await _ledger(client, h, v)
    assert [x["kind"] for x in led["lines"]] == ["opening", "bill"] and led["closing"] == "20000.00"
    period = await _ledger(client, h, v, date_from=_day(10))
    assert period["brought_forward"] == "15000.00" and [x["kind"] for x in period["lines"]] == ["bill"]

    pm = await _user(test_engine, w["org"], "project_manager", "Sanjay", projects=[w["flats"]])
    mine = await _ledger(client, pm["h"], v)
    assert mine["partial"] is True and mine["closing"] == "5000.00"         # their project only, no company opening
    bank = await _account(client, h, "HDFC", "bank")
    assert (await client.post(f"/finance/vendors/{v}/payments", headers=pm["h"],
                              json={"account_id": bank, "amount": "100"})).status_code == 403
    assert (await client.patch(f"/finance/vendors/{v}", headers=pm["h"], json={"opening_balance": "1"})).status_code == 403
    assert (await client.get(f"/finance/vendors/{v}/ledger", headers=w["arun"]["h"])).status_code == 403
    assert (await client.get("/finance/vendors/payables", headers=w["arun"]["h"])).status_code == 403
    assert (await client.get("/finance/vendors", headers=w["arun"]["h"])).status_code == 200  # the picker stays open


async def test_taking_back_an_expense_paid_in_two_parts_returns_both(client, world):
    """8 Nov 2026: only the first payment was returned, the second account stayed short."""
    w = world
    h = w["admin"]["h"]
    bank = await _account(client, h, "SBI", "bank")
    box = await _account(client, h, "Villa box", "cash", opening="100000")
    v = await _vendor(client, h, "Concrete team", kind="subcontractor")
    eid = await _bill(client, w, v, "15000", days_ago=1)
    assert (await client.post(f"/expenses/{eid}/payments", headers=h, json={"account_id": box, "amount": "5000"})).status_code == 201
    assert (await client.post(f"/expenses/{eid}/payments", headers=h, json={"account_id": bank})).status_code == 201
    back = await client.post(f"/expenses/{eid}/reverse", headers={**h, "Idempotency-Key": str(uuid.uuid4())})
    assert back.status_code == 200, back.text
    assert (await _balance(client, h, bank), await _balance(client, h, box)) == ("500000.00", "100000.00")
    assert (await _ledger(client, h, v))["closing"] == "0.00"


async def test_delete_refused_with_history_merge_moves_everything(client, world):
    w = world
    h = w["admin"]["h"]
    a = await _vendor(client, h, "Malabar", phone="9847012345")
    b = await _vendor(client, h, "Malabar Traders", gstin="32ABCDE1234F1Z5", credit_days=15)
    await _came(client, w, "cement", "10", "400", days_ago=3, vendor_id=a)
    await _bill(client, w, a, "2000", days_ago=2)
    refused = await client.delete(f"/finance/vendors/{a}", headers=h)
    assert refused.status_code == 409 and "1 expenses" in refused.text and "1 deliveries" in refused.text
    clash = await client.patch(f"/finance/vendors/{a}", headers=h, json={"name": "malabar traders"})
    assert clash.status_code == 409

    merged = await client.post(f"/finance/vendors/{a}/merge", headers=h, json={"into_vendor_id": b})
    assert merged.status_code == 200, merged.text
    into = merged.json()["into"]
    assert (into["phone"], into["gstin"], into["credit_days"]) == ("9847012345", "32ABCDE1234F1Z5", 15)  # gaps filled
    assert merged.json()["moved"]["deliveries"] == 1 and merged.json()["moved"]["expenses"] == 1
    assert (await _ledger(client, h, b))["closing"] == "6000.00"
    assert (await client.get(f"/finance/vendors/{a}", headers=h)).status_code == 404

    fresh = await _vendor(client, h, "Typo Shop")
    assert (await client.delete(f"/finance/vendors/{fresh}", headers=h)).status_code == 200


async def test_delete_and_merge_know_every_table_that_points_at_a_vendor(test_engine):
    """A new table with a vendor_id must be added to VENDOR_LINKS, or a merge would leave rows on a deleted vendor."""
    from mesiri.domains.vendors.router import VENDOR_LINKS

    async with test_engine.begin() as conn:
        rows = (await conn.execute(sa.text(
            "SELECT conrelid::regclass::text, a.attname FROM pg_constraint k JOIN pg_attribute a "
            "ON a.attrelid = k.conrelid AND a.attnum = ANY(k.conkey) "
            "WHERE k.confrelid = 'vendors'::regclass AND k.contype = 'f'"))).all()
    assert {(t, c) for t, c in rows} == {(t, c) for t, c, _ in VENDOR_LINKS}


async def test_a_payment_for_one_project_pays_only_that_projects_bills(client, world):
    """8 Nov 2026: a payment made for Edappally paid Villa's older bill first."""
    w = world
    h = w["admin"]["h"]
    bank = await _account(client, h, "SBI", "bank")
    v = await _vendor(client, h, "Kerala Steel")
    villa_bill = await _bill(client, w, v, "10000", days_ago=20)
    flats_bill = await _bill(client, w, v, "4000", days_ago=2, project="flats")
    paid = await client.post(f"/finance/vendors/{v}/payments", headers=h,
                             json={"account_id": bank, "amount": "6000", "project_id": str(w["flats"])})
    assert paid.status_code == 201, paid.text
    assert [b["expense_id"] for b in paid.json()["bills_paid"]] == [flats_bill]
    assert paid.json()["advance_left"] == "2000.00"
    assert (await client.get(f"/expenses/{villa_bill}/payments", headers=h)).json()["payment_status"] == "unpaid"
    # Its advance stays with that project: using it never reaches Villa's bill.
    nothing = await client.post(f"/finance/vendors/{v}/payments/{paid.json()['payment_id']}/apply", headers=h, json={})
    assert nothing.status_code == 409


async def test_the_money_summary_works_and_only_for_who_sees_all_spending(client, world):
    w = world
    h = w["admin"]["h"]
    v = await _vendor(client, h, "Malabar")
    await _bill(client, w, v, "2500", days_ago=1)
    summary = await client.get("/finance/summary", headers=h)
    assert summary.status_code == 200, summary.text          # failed with any vendor before (a missing key)
    assert next(t for t in summary.json()["top_vendors"] if t["name"] == "Malabar")["unpaid_amount"] in ("2500.00", "2500", 2500)
    assert (await client.get("/finance/summary", headers=w["arun"]["h"])).status_code == 403


# --- PRC-11: a bill matched to the deliveries the site already recorded ------------------------------------------------


async def _receipts(engine, material) -> list:
    async with engine.begin() as conn:
        return (await conn.execute(sa.text(
            "SELECT quantity, invoice_id, billed_quantity, billed_rate, vendor_id FROM material_receipts "
            "WHERE material_id = :m ORDER BY occurred_date, created_at"), {"m": material})).mappings().all()


async def _invoice(client, w, lines, total=None, supplier="Malabar Hardware", days_ago=0, **extra):
    r = await client.post("/materials/invoices", headers={**w["admin"]["h"], "Idempotency-Key": str(uuid.uuid4())}, json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]), "supplier_name": supplier, "invoice_number": "MH/9",
        "invoice_date": _day(days_ago), **({"invoice_total": total} if total else {}),
        "lines": [{"material_id": w["cement"], "unit_id": w["units"]["bags"], "quantity": q, "unit_cost": rate} for q, rate in lines],
        **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def test_a_bill_for_a_delivery_already_recorded_is_linked_not_added_again(client, world, test_engine):
    w = world
    await _came(client, w, "cement", "100", None, days_ago=4, supplier="Malabar Hardware")   # site: no rate
    preview = await client.post("/materials/invoices/match", headers=w["admin"]["h"], json={
        "project_id": str(w["villa"]), "site_id": str(w["block_a"]), "supplier_name": "Malabar Hardware",
        "invoice_date": _day(0), "lines": [{"material_id": w["cement"], "unit_id": w["units"]["bags"], "quantity": "100", "unit_cost": "413"}]})
    assert preview.status_code == 200 and len(preview.json()["lines"][0]["deliveries"]) == 1
    bill = await _invoice(client, w, [("100", "413")], total="41300")
    assert len(bill["matched"]) == 1 and bill["matched"][0]["flags"] == []
    rows = await _receipts(test_engine, w["cement"])
    assert len(rows) == 1                                               # stock counted once
    assert rows[0]["invoice_id"] is not None and rows[0]["billed_rate"] == 413
    v = rows[0]["vendor_id"]
    led = await _ledger(client, w["admin"]["h"], str(v))
    assert led["closing"] == "41300.00" and [x["kind"] for x in led["lines"]] == ["bill"]


async def test_a_bill_saying_more_or_a_different_rate_is_flagged(client, world, test_engine):
    w = world
    await _came(client, w, "cement", "150", "400", days_ago=3, supplier="Malabar Hardware")
    bill = await _invoice(client, w, [("200", "420")])
    assert bill["matched"][0]["flags"] == ["billed 50 bags more than delivered", "rate ₹420 on the bill, ₹400 on site"]
    rows = await _receipts(test_engine, w["cement"])
    assert [r["quantity"] for r in rows] == [150]                       # the site's count stays
    led = await _ledger(client, w["admin"]["h"], str(rows[0]["vendor_id"]))
    assert led["summary"]["open_bills"][0]["mismatches"] == 1
    on = (await client.get(f"/finance/vendors/{rows[0]['vendor_id']}/bills/{bill['expense_id']}/deliveries", headers=w["admin"]["h"])).json()
    assert on[0]["billed_quantity"] == "200" and len(on[0]["flags"]) == 2


async def test_two_deliveries_on_one_bill_line_and_a_new_line_with_the_bill(client, world, test_engine):
    w = world
    await _came(client, w, "cement", "100", None, days_ago=6, supplier="Malabar Hardware")
    await _came(client, w, "cement", "100", None, days_ago=2, supplier="Malabar Hardware")
    await _invoice(client, w, [("200", "410")])
    assert len(await _receipts(test_engine, w["cement"])) == 2          # both linked, none added
    await _invoice(client, w, [("50", "410")])                          # came with the bill: a new delivery
    rows = await _receipts(test_engine, w["cement"])
    assert len(rows) == 3 and all(r["invoice_id"] for r in rows)
    await _invoice(client, w, [("50", "410")], match_deliveries=False)  # said new: never matched
    assert len(await _receipts(test_engine, w["cement"])) == 4


async def test_a_bill_typed_as_an_expense_links_its_deliveries_when_certain_else_offers(client, world):
    w = world
    h = w["admin"]["h"]
    v = await _vendor(client, h, "Edappally Stores")
    await _came(client, w, "cement", "20", "410", days_ago=3, vendor_id=v)
    exact = await client.post("/expenses", headers={**h, "Idempotency-Key": str(uuid.uuid4())}, json={
        "project_id": str(w["villa"]), "amount": "8200", "category_text": "Materials", "vendor_text": "Edappally Stores",
        "occurred_date": _day(1)})
    assert exact.status_code == 201 and exact.json()["unbilled_deliveries"]["linked"] is True
    assert (await _ledger(client, h, v))["closing"] == "8200.00"        # once

    await _came(client, w, "cement", "10", "410", days_ago=1, vendor_id=v)
    other = await client.post("/expenses", headers={**h, "Idempotency-Key": str(uuid.uuid4())}, json={
        "project_id": str(w["villa"]), "amount": "5000", "category_text": "Materials", "vendor_id": v, "occurred_date": _day(0)})
    offer = other.json()["unbilled_deliveries"]
    assert offer["linked"] is False and offer["count"] == 1 and offer["total"] == "4100.00"

    listed = (await client.get("/finance/vendors/unbilled", headers=h)).json()
    assert listed["totals"]["count"] == 1 and listed["deliveries"][0]["order_id"] is None and listed["totals"]["no_order"] == 1


# --- 8 Nov 2026: money reads by role, supplier names on no account, the daily supplier note -------------------------


async def test_a_site_engineer_sees_their_sites_cash_box_never_the_bank(client, world):
    w = world
    h = w["admin"]["h"]
    bank = await _account(client, h, "HDFC current", "bank")
    villa_box = (await client.post("/finance/accounts", headers=h, json={"name": "Villa box", "account_type": "cash",
                 "opening_balance": "20000", "project_id": str(w["villa"]), "site_id": str(w["block_a"])})).json()["id"]
    flats_box = (await client.post("/finance/accounts", headers=h, json={"name": "Flats box", "account_type": "cash",
                 "opening_balance": "20000", "project_id": str(w["flats"]), "site_id": str(w["tower"])})).json()["id"]
    arun = w["arun"]["h"]                                                     # site engineer on Villa
    assert {a["name"] for a in (await client.get("/finance/accounts", headers=arun)).json()} == {"Villa box"}
    assert (await client.get(f"/finance/accounts/{bank}", headers=arun)).status_code == 404
    assert (await client.get(f"/finance/accounts/{flats_box}/transactions", headers=arun)).status_code == 404
    assert (await client.get(f"/finance/accounts/{villa_box}/transactions", headers=arun)).status_code == 200
    await client.post("/finance/transfers", headers=h, json={"from_account_id": bank, "to_account_id": flats_box, "amount": "500"})
    assert all(t["to_account_id"] != flats_box for t in (await client.get("/finance/transactions", headers=arun)).json())
    assert (await client.get("/finance/reports/statement", headers=arun)).status_code == 403
    assert len((await client.get("/finance/accounts", headers=h)).json()) == 3   # the owner's view is unchanged


async def test_supplier_names_on_no_account_are_listed_and_linked(client, world):
    w = world
    h = w["admin"]["h"]
    malabar = await _vendor(client, h, "Malabar Hardware")
    await _came(client, w, "cement", "10", "400", days_ago=3, supplier="Malabar Hardware")
    # an old delivery typed before vendors were linked
    eng = create_async_engine(Settings().postgres.dsn())
    async with eng.begin() as conn:
        await conn.execute(sa.text("UPDATE material_receipts SET vendor_id = NULL, supplier = 'malabar hardware '"))
    await eng.dispose()
    names = (await client.get("/finance/vendors/unlinked-names", headers=h)).json()
    assert names[0]["name"].strip().lower() == "malabar hardware" and names[0]["likely"]["id"] == malabar
    linked = await client.post("/finance/vendors/link-name", headers=h, json={"name": names[0]["name"], "vendor_id": malabar})
    assert linked.json()["deliveries"] == 1
    assert (await _ledger(client, h, malabar))["summary"]["unbilled"] == "4000.00"
    assert (await client.get("/finance/vendors/unlinked-names", headers=h)).json() == []


async def test_overdue_bills_are_told_once_a_day_to_who_pays(client, world, test_engine):
    from mesiri.domains.vendors.reminders import queue_supplier_reminders

    w = world
    h = w["admin"]["h"]
    v = await _vendor(client, h, "Concrete team", credit_days=7)
    await _bill(client, w, v, "27000", days_ago=20)
    async with test_engine.begin() as conn:
        first = await queue_supplier_reminders(conn, w["org"], TODAY)
        again = await queue_supplier_reminders(conn, w["org"], TODAY)
        note = (await conn.execute(sa.text("SELECT payload->>'message' FROM notifications WHERE rule_key = 'suppliers_waiting'"))).scalar()
    assert (first, again) == (1, 0)                                           # the admin only (engineers not told)
    assert "₹27,000 of supplier bills is overdue (Concrete team ₹27,000)" in note
