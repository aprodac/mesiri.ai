"""ACC-12..21 contract: through the real routes on a live Postgres, with the month of records ACC-01..05's contract
builds (``_company``): manual vouchers, bank reconciliation, the month-end delivery accrual, fixed assets and
depreciation, year end, cash flow, the Tally export from the journals, and every report as Excel and PDF. After each,
the books still balance and still agree with Finance › Money, the supplier ledger and Receivables.

Requires a live Postgres reachable via Settings().postgres.dsn() -- run with `pytest -m integration`."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mesiri.bootstrap.settings import Settings

from .test_accounts_contract import ON, _app, _company, _row, _run, _user

pytestmark = pytest.mark.integration


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(test_engine: AsyncEngine, monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=_app(test_engine, monkeypatch, ON)),
                           base_url="http://testserver") as c:
        yield c


async def _receipt(client, ids, h):
    r = await client.post("/billing/receipts", headers=h, json={
        "ra_bill_id": str(ids["ra"]), "kind": "bill", "amount": "50000", "received_on": str(ids["day"]),
        "account_id": str(ids["bank"])})
    assert r.status_code == 201, r.text


async def _ledger(client, h, code=None, name=None):
    chart = (await client.get("/accounts/chart", headers=h)).json()
    return next(x for x in chart["ledgers"] if (code and x["code"] == code) or (name and x["name"] == name))


async def _agrees(client, h):
    checks = (await client.get("/accounts/checks", headers=h)).json()
    for part in ("accounts", "suppliers", "clients"):
        assert checks[part]["differ"] == 0, (part, checks[part]["rows"])
    tb = (await client.get("/accounts/trial-balance?date_from=2025-04-01", headers=h)).json()
    assert tb["totals"]["balanced"], tb["totals"]
    return tb


async def test_manual_vouchers_post_refuse_money_ledgers_and_closed_months_and_cancel(client, test_engine):
    ids = await _company(test_engine)
    h = {"Authorization": f"Bearer {ids['admin']}"}
    try:
        charges = await _ledger(client, h, "bank_charges")
        payable = await _ledger(client, h, "expenses_payable")
        bank = await _ledger(client, h, name="SBI current")
        body = {"date": str(ids["day"]), "narration": "Audit fee for the year, provided",
                "lines": [{"ledger_id": charges["id"], "debit": "25000", "project_id": str(ids["project"])},
                          {"ledger_id": payable["id"], "credit": "25000"}]}
        r = await client.post("/accounts/vouchers", headers=h, json=body)
        assert r.status_code == 201, r.text
        v = r.json()
        assert v["status"] == "posted" and v["amount"] == "25000.00" and v["ref"].startswith("JOU/")
        tb = await _agrees(client, h)
        assert _row(tb, "Bank charges")["closing"] == "25000.00"
        book = (await client.get(f"/accounts/day-book?date_from={ids['month']}&q=Audit", headers=h)).json()
        assert book["count"] == 1 and book["entries"][0]["source"]["kind"] == "voucher"

        # Never a bank or cash ledger (Finance would no longer agree); never unbalanced.
        bad = {**body, "lines": [{**body["lines"][0]}, {"ledger_id": bank["id"], "credit": "25000"}]}
        r = await client.post("/accounts/vouchers", headers=h, json=bad)
        assert r.status_code == 422 and "Finance › Money" in r.json()["detail"]
        r = await client.post("/accounts/vouchers", headers=h, json={**body, "lines": [
            {**body["lines"][0]}, {"ledger_id": payable["id"], "credit": "24000"}]})
        assert r.status_code == 422 and "differ by ₹1,000.00" in r.json()["detail"]

        # Changed in an open month: same number.
        r = await client.put(f"/accounts/vouchers/{v['id']}", headers=h, json={**body, "lines": [
            {**body["lines"][0], "debit": "30000"}, {"ledger_id": payable["id"], "credit": "30000"}]})
        assert r.status_code == 200 and r.json()["ref"] == v["ref"] and r.json()["amount"] == "30000.00"

        # Closed month: no new voucher in it, no change to one in it; cancelling posts the difference after close.
        assert (await client.post(f"/accounts/periods/{ids['month']:%Y-%m}/close", headers=h)).status_code == 200
        r = await client.post("/accounts/vouchers", headers=h, json=body)
        assert r.status_code == 409 and "is closed" in r.json()["detail"]
        assert (await client.put(f"/accounts/vouchers/{v['id']}", headers=h, json=body)).status_code == 409
        r = await client.post(f"/accounts/vouchers/{v['id']}/cancel", headers=h, json={"reason": "provided twice"})
        assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["cancel_reason"] == "provided twice"
        tb = await _agrees(client, h)
        assert _row(tb, "Bank charges")["closing"] == "0.00"
        late = (await client.get(f"/accounts/day-book?after_close=true&date_from={ids['month']}", headers=h)).json()
        assert late["count"] == 1 and late["entries"][0]["amount"] == "30000.00"

        # Who: finance may post; a project manager may not.
        _, pm = await _user(test_engine, ids["org"], "PROJECT_MANAGER")
        assert (await client.get("/accounts/vouchers", headers={"Authorization": f"Bearer {pm}"})).status_code == 403
    finally:
        await _run(test_engine, "DELETE FROM organizations WHERE id = :id", id=ids["org"])


def _statement(ids, closing: str) -> bytes:
    d = ids["day"]
    return ("Date,Narration,Chq./Ref.No.,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"
            f"{d:%d/%m/%Y},NEFT-MALABAR,,5000.00,,95000.00\n"
            f"{d:%d/%m/%Y},NEFT-MALABAR ON ACCOUNT,,2000.00,,93000.00\n"
            f"{d:%d/%m/%Y},CAPITAL INTRODUCED,,,20000.00,113000.00\n"
            f"{d:%d/%m/%Y},TRF TO PETTY CASH,,3000.00,,110000.00\n"
            f"{d:%d/%m/%Y},CHRG: SMS ALERT,,17.70,,{closing}\n").encode()


async def test_bank_reconciliation_matches_books_charges_through_finance_and_explains_the_difference(client, test_engine):
    ids = await _company(test_engine)
    h = {"Authorization": f"Bearer {ids['admin']}"}
    try:
        await _receipt(client, ids, h)  # 50,000 from the client: in the books, not yet in this statement
        files = {"file": ("hdfc.csv", _statement(ids, "109982.30"), "text/csv")}
        r = await client.post(f"/accounts/bank/{ids['bank']}/statements?preview=true", headers=h, files=files)
        assert r.status_code == 201 and r.json()["new"] == 5 and "statement_id" not in r.json()
        r = await client.post(f"/accounts/bank/{ids['bank']}/statements", headers=h, files=files)
        assert r.status_code == 201, r.text
        assert r.json()["matched"] == 4  # the two payments, the fund received, the transfer; the charge is the bank's
        again = await client.post(f"/accounts/bank/{ids['bank']}/statements", headers=h, files=files)
        assert again.json()["new"] == 0 and again.json()["already_imported"] == 5

        o = (await client.get(f"/accounts/bank/{ids['bank']}", headers=h)).json()
        assert o["counts"] == {"open": 1, "matched": 4, "booked": 0, "ignored": 0}
        rec = o["reconciliation"]
        # Books 1,60,000 − 50,000 received not yet in the bank − 17.70 bank only = 1,09,982.30, as the statement says.
        assert (rec["books"], rec["received_not_in_bank"], rec["bank_only_out"]) == ("160000.00", "50000.00", "17.70")
        assert rec["difference"] == "0.00"
        charge = next(ln for ln in o["lines"] if ln["status"] == "open")

        # Book the charge: a movement in Finance on Bank charges; the books and Finance still agree.
        charges = await _ledger(client, h, "bank_charges")
        r = await client.post(f"/accounts/bank/lines/{charge['id']}/book", headers=h, json={"ledger_id": charges["id"]})
        assert r.status_code == 200 and r.json()["counts"]["booked"] == 1 and r.json()["reconciled_pct"] == 100
        tb = await _agrees(client, h)
        assert _row(tb, "Bank charges")["closing"] == "17.70" and _row(tb, "SBI current")["closing"] == "159982.30"
        moved = (await _run(test_engine, "SELECT COUNT(*) FROM money_transactions WHERE source_type = 'bank_statement_line' "
                            "AND organization_id = :o", o=ids["org"])).scalar()
        assert moved == 1

        # Undo: reversed in Finance as Finance undoes; booked again on another ledger, the first stays as it was posted.
        r = await client.post(f"/accounts/bank/lines/{charge['id']}/undo", headers=h)
        assert r.json()["counts"]["open"] == 1
        tb = await _agrees(client, h)
        assert _row(tb, "Bank charges")["closing"] == "0.00" and _row(tb, "SBI current")["closing"] == "160000.00"
        rnd = await _ledger(client, h, "round_off")
        await client.post(f"/accounts/bank/lines/{charge['id']}/book", headers=h, json={"ledger_id": rnd["id"]})
        tb = await _agrees(client, h)
        assert _row(tb, "Bank charges")["closing"] == "0.00" and _row(tb, "Round off")["closing"] == "17.70"

        # A bank ledger cannot be booked against; a matched line cannot be matched again.
        petty = await _ledger(client, h, name="Block A petty cash")
        other = next(ln for ln in o["lines"] if ln["status"] == "matched")
        r = await client.post(f"/accounts/bank/lines/{other['id']}/book", headers=h, json={"ledger_id": petty["id"]})
        assert r.status_code == 422
        assert (await client.get(f"/accounts/bank/{ids['bank']}/export?format=pdf", headers=h)).content[:4] == b"%PDF"
        summary = (await client.get("/accounts/bank", headers=h)).json()["accounts"]
        assert next(a for a in summary if a["name"] == "SBI current")["open"] == 0
    finally:
        await _run(test_engine, "DELETE FROM organizations WHERE id = :id", id=ids["org"])


async def test_deliveries_not_billed_are_accrued_at_month_end_and_reversed(client, test_engine):
    ids = await _company(test_engine)
    h = {"Authorization": f"Bearer {ids['admin']}"}
    org, month, day = ids["org"], ids["month"], ids["day"]
    end = (month.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
    try:
        cement = uuid.uuid4()
        await _run(test_engine, "INSERT INTO materials_catalog (id, organization_id, name, default_unit_id, is_active, "
                   "created_by) VALUES (:id, :org, 'Cement', (SELECT id FROM units_of_measure WHERE code = 'bags'), true, :u)",
                   id=cement, org=org, u=ids["admin_id"])
        receipts = [uuid.uuid4(), uuid.uuid4()]
        for rid, qty in zip(receipts, (40, 10), strict=True):
            await _run(test_engine, "INSERT INTO material_receipts (id, organization_id, project_id, site_id, material_id, "
                       "unit_id, material_name, unit, quantity, unit_cost, occurred_date, vendor_id, created_by) VALUES "
                       "(:id, :org, :p, :s, :m, (SELECT id FROM units_of_measure WHERE code = 'bags'), 'Cement', 'bags', "
                       ":q, 400, :d, :v, :u)", id=rid, org=org, p=ids["project"], s=ids["site"], m=cement, q=qty, d=day,
                       v=ids["malabar"], u=ids["admin_id"])
        # The 10 bags' bill comes next month: at this month's end they were not billed.
        bill, inv = uuid.uuid4(), uuid.uuid4()
        await _run(test_engine, "INSERT INTO expenses (id, organization_id, project_id, amount, occurred_date, created_by, "
                   "category_id, vendor_id, workflow_status) VALUES (:id, :org, :p, 4000, :d, :u, :c, :v, 'confirmed')",
                   id=bill, org=org, p=ids["project"], d=end + datetime.timedelta(days=2), u=ids["admin_id"],
                   c=ids["materials"], v=ids["malabar"])
        await _run(test_engine, "INSERT INTO material_invoices (id, organization_id, project_id, vendor_id, expense_id, "
                   "created_by) VALUES (:id, :org, :p, :v, :e, :u)", id=inv, org=org, p=ids["project"], v=ids["malabar"],
                   e=bill, u=ids["admin_id"])
        await _run(test_engine, "UPDATE material_receipts SET invoice_id = :i WHERE id = :r", i=inv, r=receipts[1])
        tb = (await client.get(f"/accounts/trial-balance?date_from={month}&date_to={end}", headers=h)).json()
        assert _row(tb, "Materials received, bill awaited")["closing"] == "20000.00"  # all 50 bags × 400
        assert _row(tb, "Goods received not invoiced")["closing"] == "-20000.00"
        book = (await client.get(f"/accounts/day-book?q=not billed&date_from={month}&date_to={end + datetime.timedelta(days=1)}",
                                 headers=h)).json()
        assert sorted(e["date"] for e in book["entries"]) == [str(end), str(end + datetime.timedelta(days=1))]
        nxt = (await client.get(f"/accounts/trial-balance?date_from={month}&date_to={end + datetime.timedelta(days=1)}",
                                headers=h)).json()
        assert _row(nxt, "Goods received not invoiced")["closing"] == "0.00"  # reversed on the 1st
        pl = (await client.get(f"/accounts/pl?date_from={month}&date_to={end}", headers=h)).json()
        assert pl["totals"]["direct"] == "80700.00"  # 60,700 + the 20,000 delivered that month
        await _agrees(client, h)
    finally:
        await _run(test_engine, "DELETE FROM organizations WHERE id = :id", id=ids["org"])


async def test_fixed_assets_from_a_bill_written_down_sold_and_who_sets_the_method(client, test_engine):
    ids = await _company(test_engine)
    h = {"Authorization": f"Bearer {ids['admin']}"}
    org = ids["org"]
    try:
        mixer_bill = uuid.uuid4()
        bought = datetime.date(2025, 5, 1)
        await _run(test_engine, "INSERT INTO expenses (id, organization_id, project_id, amount, occurred_date, created_by, "
                   "category_id, vendor_id, workflow_status, expense_number, description) VALUES (:id, :org, :p, 200000, "
                   ":d, :u, :c, :v, 'confirmed', 'EXP-9', 'Concrete mixer')", id=mixer_bill, org=org, p=ids["project"],
                   d=bought, u=ids["admin_id"], c=ids["materials"], v=ids["malabar"])
        cands = (await client.get("/accounts/assets/candidates", headers=h)).json()["bills"]
        assert "EXP-9" in [c["expense_number"] for c in cands]  # big bills first look like assets
        r = await client.post("/accounts/assets", headers=h, json={
            "name": "Concrete mixer", "asset_class": "plant", "cost": "200000", "acquired_on": str(bought),
            "expense_id": str(mixer_bill), "project_id": str(ids["project"])})
        assert r.status_code == 201, r.text
        a = r.json()
        assert a["method"] == "wdv" and a["rate"] == "15.00"
        assert (await client.post("/accounts/assets", headers=h, json={
            "name": "Again", "asset_class": "plant", "cost": "1", "acquired_on": str(bought),
            "expense_id": str(mixer_bill)})).status_code == 409
        tb = await _agrees(client, h)
        # 2025-26 is over: written down 15% (30,000); the bill's 2,00,000 moved from Materials to the asset.
        assert _row(tb, "Plant & machinery")["closing"] == "170000.00"
        assert _row(tb, "Depreciation")["closing"] in ("30000.00", "0.00")  # 0 when the period starts in a new year
        r = (await client.get("/accounts/assets", headers=h)).json()
        assert r["totals"]["value"] == "170000.00" and r["assets"][0]["years"][0]["depreciation"] == "30000.00"

        r = await client.post(f"/accounts/assets/{a['id']}/dispose", headers=h,
                              json={"disposed_on": str(ids["day"]), "disposal_value": "150000"})
        assert r.status_code == 200 and r.json()["status"] == "sold"
        tb = await _agrees(client, h)
        assert _row(tb, "Plant & machinery")["closing"] == "0.00"
        assert _row(tb, "Assets sold, money to receive")["closing"] == "150000.00"
        assert _row(tb, "Loss or gain on assets sold")["closing"] == "20000.00"  # book 1,70,000 − 1,50,000
        assert (await client.get("/accounts/assets/export?format=pdf", headers=h)).content[:4] == b"%PDF"

        _, fin = await _user(test_engine, org, "FINANCE")
        f = {"Authorization": f"Bearer {fin}"}
        assert (await client.put("/accounts/assets/method", headers=f, json={"method": "slm"})).status_code == 403
        assert (await client.put("/accounts/assets/method", headers=h, json={"method": "slm"})).json() == {"method": "slm"}
        r = await client.post("/accounts/assets", headers=f, json={
            "name": "Laptop", "asset_class": "computers", "cost": "60000", "acquired_on": "2026-04-10",
            "books_from": "2026-04-10"})
        assert r.status_code == 201 and r.json()["method"] == "slm" and r.json()["useful_life_years"] == "3.00"
        assert (await client.delete(f"/accounts/assets/{r.json()['id']}", headers=f)).status_code == 204
        await _agrees(client, h)
    finally:
        await _run(test_engine, "DELETE FROM organizations WHERE id = :id", id=ids["org"])


async def test_year_end_closes_the_months_locks_them_and_carries_forward(client, test_engine):
    ids = await _company(test_engine)
    h = {"Authorization": f"Bearer {ids['admin']}"}
    try:
        # A voucher in 2025-26 gives that year books.
        charges = await _ledger(client, h, "bank_charges")
        payable = await _ledger(client, h, "expenses_payable")
        r = await client.post("/accounts/vouchers", headers=h, json={
            "date": "2026-03-20", "narration": "Bank charges for the year, provided",
            "lines": [{"ledger_id": charges["id"], "debit": "1200"}, {"ledger_id": payable["id"], "credit": "1200"}]})
        assert r.status_code == 201, r.text
        ys = (await client.get("/accounts/years", headers=h)).json()["years"]
        old = next(y for y in ys if y["financial_year"] == "2025-26")
        assert old["status"] == "open" and old["over"] is True and old["profit"] == "-1200.00"
        y = (await client.get("/accounts/years/2025-26", headers=h)).json()
        keys = {c["key"]: c for c in y["checklist"]}
        assert keys["over"]["ok"] and keys["balanced"]["ok"] and not keys["bank"]["ok"]
        r = await client.post("/accounts/years/2025-26/close", headers=h, json={})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "YEAR_END_WARNINGS"
        _, fin = await _user(test_engine, ids["org"], "FINANCE")
        f = {"Authorization": f"Bearer {fin}"}
        assert (await client.post("/accounts/years/2025-26/close", headers=f, json={"acknowledge": True})).status_code == 403
        r = await client.post("/accounts/years/2025-26/close", headers=h, json={"acknowledge": True})
        assert r.status_code == 200 and r.json()["status"] == "closed" and r.json()["carried_profit"] == "-1200.00"
        assert r.json()["drift"] == "0.00"
        months = (await client.get("/accounts/periods", headers=h)).json()["months"]
        assert next(m for m in months if m["month"] == "2026-03")["status"] == "closed"
        r = await client.post("/accounts/periods/2026-03/reopen", headers=h, json={"reason": "late bill"})
        assert r.status_code == 409 and "Reopen the year first" in r.json()["detail"]
        # This year carries it as earlier years' loss; the balance sheet still balances.
        bs = (await client.get("/accounts/balance-sheet", headers=h)).json()
        assert bs["balanced"] and bs["earlier_profit"] == "-1200.00"
        # What it carries balances: each ledger, earlier years' and this year's profit (Dr = Cr).
        y = (await client.get("/accounts/years/2025-26", headers=h)).json()
        assert sum(Decimal(r["balance"]) for r in y["carried"]) - Decimal(y["profit"]) - Decimal(y["earlier_profit"]) == 0
        carried = (await client.get("/accounts/years/2025-26/export?format=xlsx", headers=h))
        assert carried.status_code == 200 and carried.content[:2] == b"PK"
        r = await client.post("/accounts/years/2025-26/reopen", headers=h, json={"reason": "CA found a missing bill"})
        assert r.json()["status"] == "open" and r.json()["reopen_reason"] == "CA found a missing bill"
        assert (await client.post("/accounts/periods/2026-03/reopen", headers=h, json={"reason": "late bill"})).status_code == 200
        r = await client.post(f"/accounts/years/{ids['month']:%Y}-{(ids['month'].year + 1) % 100:02d}/close"
                              if ids["month"].month >= 4 else "/accounts/years/2026-27/close", headers=h,
                              json={"acknowledge": True})
        assert r.status_code == 409 and "can be closed from 1 April" in r.json()["detail"]
    finally:
        await _run(test_engine, "DELETE FROM organizations WHERE id = :id", id=ids["org"])


async def test_cash_flow_tally_from_the_books_and_every_report_as_excel_and_pdf(client, test_engine):
    ids = await _company(test_engine)
    h = {"Authorization": f"Bearer {ids['admin']}"}
    month = ids["month"]
    end = (month.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
    try:
        await _receipt(client, ids, h)
        cf = (await client.get(f"/accounts/cash-flow?date_from={month}&date_to={end}", headers=h)).json()
        assert cf["agrees"] is True and cf["closing"] == cf["books_closing"] == "163000.00"
        heads = {i["key"]: i for s in cf["sections"].values() for i in s["items"]}
        assert heads["clients"]["in"] == "50000.00"
        assert heads["suppliers"]["out"] == "7000.00"  # 5,000 on the bill + 2,000 on account
        assert heads["capital"]["in"] == "20000.00"
        assert heads["opening"]["in"] == "100000.00"  # the bank's opening balance entered that month
        assert "own_accounts" not in heads  # the petty cash transfer is not a flow company-wide
        pcf = (await client.get(f"/accounts/cash-flow?date_from={month}&date_to={end}&project_id={ids['project']}",
                                headers=h)).json()
        assert pcf["agrees"] is True

        r = await client.get(f"/finance/tally/summary?date_from={month}&date_to={end}", headers=h)
        assert r.status_code == 200 and r.json()["source"] == "books"
        book = (await client.get(f"/accounts/day-book?date_from={month}&date_to={end}", headers=h)).json()
        assert r.json()["vouchers"] == book["count"]
        xml = (await client.get(f"/finance/tally/export?date_from={month}&date_to={end}", headers=h)).text
        assert xml.count("<VOUCHER ") == book["count"] and "mesiri-je-" in xml

        q = f"date_from={month}&date_to={end}"
        paths = [f"/accounts/trial-balance/export?{q}", f"/accounts/day-book/export?{q}", f"/accounts/gst/export?{q}",
                 f"/accounts/tds/export?{q}", f"/accounts/pl/export?{q}&compare=previous", "/accounts/balance-sheet/export",
                 f"/accounts/cash-bank/export?{q}", f"/accounts/projects/export?{q}", f"/accounts/cash-flow/export?{q}",
                 "/accounts/assets/export"]
        malabar = (await _ledger(client, h, name="Malabar"))["id"]
        paths.append(f"/accounts/ledgers/{malabar}/statement/export?{q}")
        for path in paths:
            for fmt, magic in (("xlsx", b"PK"), ("pdf", b"%PDF")):
                r = await client.get(f"{path}{'&' if '?' in path else '?'}format={fmt}", headers=h)
                assert r.status_code == 200 and r.content[:len(magic)] == magic, (path, fmt, r.status_code, r.text[:200])
        st = (await client.get(f"/accounts/ledgers/{malabar}/statement?{q}", headers=h)).json()
        assert st["party"] == {"kind": "vendor", "name": "Malabar", "phone": None}
        _, pm = await _user(test_engine, ids["org"], "PROJECT_MANAGER")
        p = {"Authorization": f"Bearer {pm}"}
        assert (await client.get(f"/accounts/pl/export?project_id={ids['project']}&format=pdf", headers=p)).status_code == 200
        assert (await client.get("/accounts/pl/export?format=pdf", headers=p)).status_code == 403
        assert (await client.get("/accounts/cash-flow", headers=p)).status_code == 403
        assert Decimal(cf["net"]) == Decimal(cf["closing"]) - Decimal(cf["opening"])
    finally:
        await _run(test_engine, "DELETE FROM organizations WHERE id = :id", id=ids["org"])
