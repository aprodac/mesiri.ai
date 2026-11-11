"""ACC-19 contract: the Tally export from the posted journals (run with `pytest -m integration`).

For a seeded month (a supplier bill with GST, its payment, an RA bill and the client's money) the old export (from the
records, NXT-12) and the new one (from the books) hold the same total per ledger. A manual voucher reaches Tally only
by the new path. A company without Accounts still gets the old export. Differences by design are in the ACC-19 report.
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from contract import test_accounts_contract as books
from contract.test_accounts_contract import ON, _last_month, _run, _user
from mesiri.http.app import create_app
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration
test_engine = books.test_engine
OFF = [m for m in ON if m != "accounts"]


@pytest.fixture
async def switch(test_engine, monkeypatch):
    """A client whose company has Accounts on or off (``state["modules"]``)."""
    state = {"modules": ON}

    async def enabled(request, organization_id):
        return state["modules"]

    monkeypatch.setattr("mesiri.domains.shared.modules.read_enabled_modules", enabled)
    app = create_app()

    async def conn():
        async with test_engine.begin() as c:
            yield c

    app.dependency_overrides[get_db_conn] = conn
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c, state


def _totals(xml: str) -> dict[str, Decimal]:
    """Per ledger, the net of every voucher (Tally's sign: a debit is negative)."""
    out: dict[str, Decimal] = defaultdict(Decimal)
    for e in ET.fromstring(xml).iter("ALLLEDGERENTRIES.LIST"):
        out[e.findtext("LEDGERNAME")] += Decimal(e.findtext("AMOUNT"))
    return {k: v for k, v in out.items() if v}


async def _month(engine) -> dict:
    from mesiri.infrastructure.postgres.repositories.expenses import (
        PostgresExpensePaymentRepository,
    )

    ids = {k: uuid.uuid4() for k in ("org", "project", "bank", "vendor", "cat", "client", "ra", "bill")}
    month, day = _last_month()
    ids.update(month=month, day=day)
    org = ids["org"]
    await _run(engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
               "VALUES (:id, 'Tally Books', 'local', 'default', 'active', now(), now())", id=org)
    admin_id, admin = await _user(engine, org, "admin")
    ids["admin"] = admin
    await _run(engine, "INSERT INTO projects (id, organization_id, name, created_at, updated_at) VALUES (:id, :org, 'Villa', "
               "now(), now())", id=ids["project"], org=org)
    await _run(engine, "INSERT INTO expense_categories (id, organization_id, name, code, created_by) VALUES (:id, :org, "
               "'Materials', 'MAT', :u)", id=ids["cat"], org=org, u=admin_id)
    await _run(engine, "INSERT INTO vendors (id, organization_id, name, created_by, gstin) VALUES (:id, :org, 'Malabar', :u, "
               "'32AAAAA0000A1Z5')", id=ids["vendor"], org=org, u=admin_id)
    await _run(engine, "INSERT INTO money_accounts (id, organization_id, account_type, name, opening_balance, "
               "opening_balance_date, created_by) VALUES (:id, :org, 'bank', 'SBI current', 0, :d, :u)",
               id=ids["bank"], org=org, d=month, u=admin_id)
    await _run(engine, "INSERT INTO expenses (id, organization_id, project_id, amount, occurred_date, created_by, "
               "category_id, vendor_id, workflow_status, payment_status, tax_amount, is_tax_inclusive, expense_number) "
               "VALUES (:id, :org, :p, 11800, :d, :u, :c, :v, 'confirmed', 'unpaid', 1800, true, 'EXP-1')",
               id=ids["bill"], org=org, p=ids["project"], d=day, u=admin_id, c=ids["cat"], v=ids["vendor"])
    async with engine.begin() as conn:
        await PostgresExpensePaymentRepository(conn).record_payment(
            organization_id=org, expense_id=ids["bill"], account_id=ids["bank"], amount=Decimal(5000), paid_date=day,
            created_by=admin_id)
    await _run(engine, "INSERT INTO clients (id, organization_id, name) VALUES (:id, :org, 'Mehta Builders')",
               id=ids["client"], org=org)
    await _run(engine, "INSERT INTO ra_bills (id, organization_id, project_id, number, status, bill_date, client_id, "
               "retention_pct, advance_recovery_pct, gst_pct, tds_pct, gross, retention, advance_recovery, gst, tds, net) "
               "VALUES (:id, :org, :p, 1, 'submitted', :d, :c, 5, 0, 18, 2, 100000, 5000, 0, 18000, 2000, 111000)",
               id=ids["ra"], org=org, p=ids["project"], d=day, c=ids["client"])
    return ids


async def test_old_and_new_exports_agree_per_ledger_and_a_manual_voucher_reaches_tally(switch, test_engine):
    client, state = switch
    ids = await _month(test_engine)
    h = {"Authorization": f"Bearer {ids['admin']}"}
    period = f"date_from={ids['month']}&date_to={ids['day']}"
    try:
        r = await client.post("/billing/receipts", headers=h, json={
            "ra_bill_id": str(ids["ra"]), "kind": "bill", "amount": "50000", "received_on": str(ids["day"]),
            "account_id": str(ids["bank"])})
        assert r.status_code == 201, r.text
        state["modules"] = OFF
        old = await client.get(f"/finance/tally/export?{period}", headers=h)
        assert (await client.get(f"/finance/tally/summary?{period}", headers=h)).json()["source"] == "records"
        state["modules"] = ON
        new = await client.get(f"/finance/tally/export?{period}", headers=h)
        assert old.status_code == new.status_code == 200
        assert new.headers["content-disposition"] == old.headers["content-disposition"]  # same file name
        assert _totals(new.text) == _totals(old.text)
        assert _totals(new.text)["Malabar"] == Decimal("6800.00") and _totals(new.text)["Input GST"] == Decimal("-1800.00")
        for v in ET.fromstring(new.text).iter("VOUCHER"):
            assert sum(Decimal(x.findtext("AMOUNT")) for x in v.findall("ALLLEDGERENTRIES.LIST")) == 0
        assert {v.get("VCHTYPE") for v in ET.fromstring(new.text).iter("VOUCHER")} == {"Purchase", "Payment", "Sales", "Receipt"}

        led = {x["name"]: x["id"] for x in (await client.get("/accounts/vouchers/ledgers", headers=h)).json()["ledgers"]}
        posted = await client.post("/accounts/vouchers", headers=h, json={
            "date": str(ids["day"]), "voucher_type": "journal", "narration": "SBI charges",
            "lines": [{"ledger_id": led["Bank charges"], "debit": "354", "credit": "0"},
                      {"ledger_id": led["SBI current"], "debit": "0", "credit": "354"}]})
        assert posted.status_code == 201, posted.text
        summary = (await client.get(f"/finance/tally/summary?{period}", headers=h)).json()
        assert (summary["source"], summary["manual"], summary["journals"]) == ("books", 1, 1)
        xml = (await client.get(f"/finance/tally/export?{period}", headers=h)).text
        assert _totals(xml)["Bank charges"] == Decimal("-354.00")
        masters = {x.get("NAME"): x.findtext("PARENT") for x in ET.fromstring(xml).iter("LEDGER")}
        assert masters["Bank charges"] == "Indirect Expenses" and masters["SBI current"] == "Bank Accounts"
        assert masters["Malabar"] == "Sundry Creditors" and masters["Mehta Builders"] == "Sundry Debtors"
        state["modules"] = OFF  # without Accounts: the old export, which never had manual vouchers
        assert "Bank charges" not in _totals((await client.get(f"/finance/tally/export?{period}", headers=h)).text)
    finally:
        await _run(test_engine, "DELETE FROM organizations WHERE id = :id", id=ids["org"])
