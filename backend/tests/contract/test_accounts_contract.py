"""ACC-01..05 contract: the books posted from real records through the real write paths, and what they must agree with.

A month of a small company: a supplier bill with GST and its part payment, an on-account payment, a subcontract bill
with TDS deducted, a bill paid from a staff member's own pocket, money put in, a transfer to the site's petty cash, an
RA bill and the client's payment (through the Billing route). Then: the trial balance balances, every money account
agrees with Finance › Money, every supplier with the supplier ledger, every client with Receivables; a change re-posts
under the same number; a change after the month is closed leaves the closed month alone and posts the difference on
the first open day; who may read and reopen; another company never sees a ledger.

Requires a live Postgres reachable via Settings().postgres.dsn() -- run with `pytest -m integration`."""

from __future__ import annotations

import datetime
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
_ALL = '{"mode": "all_projects", "projects": []}'
ON = ["dpr", "labour", "materials", "finance", "equipment", "cost", "accounts"]


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


def _app(test_engine, monkeypatch, modules):
    async def enabled(request, organization_id):
        return modules

    monkeypatch.setattr("mesiri.domains.shared.modules.read_enabled_modules", enabled)
    app = create_app()

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    return app


@pytest.fixture
async def client(test_engine: AsyncEngine, monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=_app(test_engine, monkeypatch, ON)),
                           base_url="http://testserver") as c:
        yield c


async def _run(engine, sql: str, **params):
    async with engine.begin() as conn:
        return await conn.execute(sa.text(sql), params)


async def _user(engine, org, role: str, name: str = "Ravi") -> tuple[uuid.UUID, str]:
    user_id = uuid.uuid4()
    await _run(engine,
               "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, access_policy, "
               "created_at, updated_at) VALUES (:id, :org, :e, 'hash', :n, :role, 'active', CAST(:p AS jsonb), now(), now())",
               id=user_id, org=org, e=f"{uuid.uuid4().hex[:8]}@example.com", n=name, role=role, p=_ALL)
    return user_id, create_access_token(data={"sub": str(user_id), "org": str(org), "role": role})


def _last_month() -> tuple[datetime.date, datetime.date]:
    first = datetime.date.today().replace(day=1)
    prev = (first - datetime.timedelta(days=1)).replace(day=1)
    return prev, prev.replace(day=10)


async def _company(engine):
    """A company with a month of records, through the real write paths where there is one."""
    from mesiri.domains.subcontracts import store as wo_store
    from mesiri.infrastructure.postgres.repositories.expenses import (
        PostgresExpensePaymentRepository,
    )
    from mesiri.infrastructure.postgres.repositories.finance import (
        PostgresMoneyTransactionRepository,
    )

    ids = {k: uuid.uuid4() for k in ("org", "project", "site", "bank", "petty", "malabar", "sub", "materials",
                                     "subwork", "client", "bill", "ra")}
    month, day = _last_month()
    ids["month"], ids["day"] = month, day
    await _run(engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
               "VALUES (:id, 'Books Org', 'local', 'default', 'active', now(), now())", id=ids["org"])
    admin_id, admin = await _user(engine, ids["org"], "admin")
    ids["admin_id"], ids["admin"] = admin_id, admin
    staff_id, _ = await _user(engine, ids["org"], "SITE_ENGINEER", "Suresh")
    org = ids["org"]
    await _run(engine, "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
               "VALUES (:id, :org, 'Villa', now(), now())", id=ids["project"], org=org)
    await _run(engine, "INSERT INTO sites (id, organization_id, project_id, name, created_at, updated_at) "
               "VALUES (:id, :org, :p, 'Block A', now(), now())", id=ids["site"], org=org, p=ids["project"])
    await _run(engine, "INSERT INTO expense_categories (id, organization_id, name, code, created_by, cost_centre) "
               "VALUES (:id, :org, 'Materials', 'MAT', :u, 'materials')", id=ids["materials"], org=org, u=admin_id)
    await _run(engine, "INSERT INTO expense_categories (id, organization_id, name, code, created_by, cost_centre) "
               "VALUES (:id, :org, 'Subcontract work', 'SUB', :u, 'subcontract')", id=ids["subwork"], org=org, u=admin_id)
    await _run(engine, "INSERT INTO vendors (id, organization_id, name, created_by, gstin) "
               "VALUES (:id, :org, 'Malabar', :u, '32AAAAA0000A1Z5')", id=ids["malabar"], org=org, u=admin_id)
    await _run(engine, "INSERT INTO vendors (id, organization_id, name, created_by, kind) "
               "VALUES (:id, :org, 'Ajay Tiling', :u, 'subcontractor')", id=ids["sub"], org=org, u=admin_id)
    await _run(engine, "INSERT INTO money_accounts (id, organization_id, account_type, name, opening_balance, "
               "opening_balance_date, created_by) VALUES (:id, :org, 'bank', 'SBI current', 100000, :d, :u)",
               id=ids["bank"], org=org, d=month, u=admin_id)
    await _run(engine, "INSERT INTO money_accounts (id, organization_id, account_type, name, opening_balance, "
               "opening_balance_date, created_by, project_id, site_id) VALUES (:id, :org, 'cash', 'Block A petty cash', 0, "
               ":d, :u, :p, :s)", id=ids["petty"], org=org, d=month, u=admin_id, p=ids["project"], s=ids["site"])

    def expense(eid, amount, cat, vendor=None, tax=None, status="unpaid", by=admin_id, number=None):
        return _run(engine,
                    "INSERT INTO expenses (id, organization_id, project_id, site_id, amount, occurred_date, created_by, "
                    "category_id, vendor_id, workflow_status, payment_status, tax_amount, is_tax_inclusive, expense_number, "
                    "description) VALUES (:id, :org, :p, :s, :a, :d, :u, :c, :v, 'confirmed', :ps, :t, true, :n, :desc)",
                    id=eid, org=org, p=ids["project"], s=ids["site"], a=amount, d=day, u=by, c=cat, v=vendor, ps=status,
                    t=tax, n=number, desc=number)

    await expense(ids["bill"], 11800, ids["materials"], ids["malabar"], 1800, number="EXP-1")
    sub_bill = uuid.uuid4()
    await expense(sub_bill, 50000, ids["subwork"], ids["sub"], number="EXP-2")
    await expense(uuid.uuid4(), 700, ids["materials"], status="reimbursable", by=staff_id, number="EXP-3")

    async with engine.begin() as conn:
        pay = PostgresExpensePaymentRepository(conn)
        money = PostgresMoneyTransactionRepository(conn)
        await pay.record_payment(organization_id=org, expense_id=ids["bill"], account_id=ids["bank"],
                                 amount=Decimal(5000), paid_date=day, created_by=admin_id)
        await pay.record_on_account(organization_id=org, vendor_id=ids["malabar"], account_id=ids["bank"],
                                    amount=Decimal(2000), paid_date=day, created_by=admin_id)
        tds = await wo_store.tds_account(conn, org, admin_id)
        ids["tds"] = tds
        await pay.record_payment(organization_id=org, expense_id=sub_bill, account_id=tds, amount=Decimal(500),
                                 paid_date=day, created_by=admin_id, payment_method="TDS 194C")
        await money.record(organization_id=org, transaction_type="fund_received", amount=Decimal(20000),
                           occurred_date=day, created_by=admin_id, to_account_id=ids["bank"])
        await money.record(organization_id=org, transaction_type="transfer", amount=Decimal(3000), occurred_date=day,
                           created_by=admin_id, from_account_id=ids["bank"], to_account_id=ids["petty"])
    await _run(engine, "INSERT INTO clients (id, organization_id, name) VALUES (:id, :org, 'Mehta Builders')",
               id=ids["client"], org=org)
    await _run(engine, "INSERT INTO ra_bills (id, organization_id, project_id, number, status, bill_date, client_id, "
               "retention_pct, advance_recovery_pct, gst_pct, tds_pct, gross, retention, advance_recovery, gst, tds, net) "
               "VALUES (:id, :org, :p, 1, 'submitted', :d, :c, 5, 0, 18, 2, 100000, 5000, 0, 18000, 2000, 111000)",
               id=ids["ra"], org=org, p=ids["project"], d=day, c=ids["client"])
    return ids


def _row(tb, name):
    return next(r for r in tb["rows"] if r["name"] == name)


async def test_a_month_of_records_posts_balanced_books_that_agree_with_every_module(client, test_engine):
    ids = await _company(test_engine)
    h = {"Authorization": f"Bearer {ids['admin']}"}
    r = await client.post("/billing/receipts", headers=h, json={
        "ra_bill_id": str(ids["ra"]), "kind": "bill", "amount": "50000", "received_on": str(ids["day"]),
        "account_id": str(ids["bank"])})
    assert r.status_code == 201, r.text
    try:
        # The client's money reached the bank in Finance too (it did not before 0530).
        moved = (await _run(test_engine, "SELECT COUNT(*) FROM money_transactions WHERE source_type = 'client_receipt' "
                            "AND organization_id = :o", o=ids["org"])).scalar()
        assert moved == 1

        tb = (await client.get(f"/accounts/trial-balance?date_from={ids['month']}", headers=h)).json()
        assert tb["totals"]["balanced"] is True, tb["totals"]
        assert tb["totals"]["debit"] == tb["totals"]["credit"]
        # Bank: 1,00,000 opening + 20,000 put in + 50,000 from the client − 5,000 − 2,000 − 3,000 = 1,60,000.
        assert _row(tb, "SBI current")["closing"] == "160000.00"
        assert _row(tb, "Block A petty cash")["closing"] == "3000.00"
        # Malabar: 11,800 bill − 5,000 paid − 2,000 on account = 4,800 owed (a credit).
        assert _row(tb, "Malabar")["closing"] == "-4800.00"
        assert _row(tb, "Input GST")["closing"] == "1800.00"
        assert _row(tb, "Materials")["closing"] == "10700.00"  # 10,000 net of GST + 700 from the own-pocket bill
        assert _row(tb, "Ajay Tiling")["closing"] == "-49500.00"  # 50,000 less 500 TDS deducted
        assert _row(tb, "TDS payable (194C)")["closing"] == "-500.00"
        assert _row(tb, "Suresh (own pocket)")["closing"] == "-700.00"
        assert _row(tb, "Mehta Builders")["closing"] == "61000.00"  # 1,11,000 net − 50,000 received
        assert _row(tb, "Contract revenue")["closing"] == "-100000.00"
        assert _row(tb, "Output GST")["closing"] == "-18000.00"
        assert _row(tb, "Funds introduced")["closing"] == "-20000.00"

        checks = (await client.get("/accounts/checks", headers=h)).json()
        for part in ("accounts", "suppliers", "clients"):
            assert checks[part]["differ"] == 0, (part, checks[part]["rows"])
        assert checks["accounts"]["agree"] == 3  # bank, petty cash, TDS payable

        book = (await client.get(f"/accounts/day-book?date_from={ids['month']}", headers=h)).json()
        kinds = sorted(e["voucher_type"] for e in book["entries"])
        assert kinds.count("purchase") == 2 and kinds.count("sales") == 1 and kinds.count("contra") == 1
        for e in book["entries"]:
            assert sum(Decimal(ln["debit"]) for ln in e["lines"]) == sum(Decimal(ln["credit"]) for ln in e["lines"])
        bill = next(e for e in book["entries"] if e["source"]["kind"] == "expense" and e["source"]["id"] == str(ids["bill"]))
        assert {ln["project"] for ln in bill["lines"]} == {"Villa"} and {ln["site"] for ln in bill["lines"]} == {"Block A"}
        paid = [e for e in book["entries"] if e["source"].get("expense_id") == str(ids["bill"])]
        assert len(paid) == 1 and paid[0]["voucher_type"] == "payment"
        # Numbered in date order within each kind of voucher, as a book is read.
        for kind in {e["voucher_type"] for e in book["entries"]}:
            mine = [e for e in book["entries"] if e["voucher_type"] == kind]
            assert [e["number"] for e in sorted(mine, key=lambda e: (e["date"], e["number"]))] == sorted(e["number"] for e in mine)
        receipt = next(e for e in book["entries"] if e["voucher_type"] == "receipt" and "RA-01" in (e["narration"] or ""))
        assert receipt["narration"].count("RA-01") == 1  # said once, not twice
        found = (await client.get(f"/accounts/day-book?date_from={ids['month']}&q=Malabar", headers=h)).json()
        assert found["count"] == 3  # the bill, the payment, the on-account payment

        malabar = _row(tb, "Malabar")["ledger_id"]
        st = (await client.get(f"/accounts/ledgers/{malabar}/statement?date_from={ids['month']}", headers=h)).json()
        assert [ln["balance"] for ln in st["lines"]][-1] == st["closing"] == "-4800.00"
        assert st["ledger"]["link_kind"] == "vendor"
        xl = await client.get(f"/accounts/ledgers/{malabar}/statement/export?date_from={ids['month']}", headers=h)
        assert xl.status_code == 200 and xl.headers["content-type"].startswith("application/vnd.openxmlformats")

        # Scope: the project's books show what moved between it and the head office.
        ptb = (await client.get(f"/accounts/trial-balance?date_from={ids['month']}&project_id={ids['project']}",
                                headers=h)).json()
        assert ptb["totals"]["balanced"] is True and ptb["scope"] == "project Villa"

        # A change re-posts under the same number.
        number = bill["number"]
        await _run(test_engine, "UPDATE expenses SET amount = 11900, tax_amount = 1800 WHERE id = :id", id=ids["bill"])
        again = (await client.get(f"/accounts/entries/{bill['id']}", headers=h)).json()
        assert again["number"] == number and again["amount"] == "11900.00"

        # Close the month; a later change leaves it alone and posts the difference on the first open day.
        r = await client.post(f"/accounts/periods/{ids['month']:%Y-%m}/close", headers=h)
        assert r.status_code == 200
        await _run(test_engine, "UPDATE expenses SET amount = 12000 WHERE id = :id", id=ids["bill"])
        closed = (await client.get(f"/accounts/entries/{bill['id']}", headers=h)).json()
        assert closed["amount"] == "11900.00"  # the closed month is untouched
        late = (await client.get("/accounts/day-book?after_close=true&date_from=" + str(ids["month"]), headers=h)).json()
        assert late["count"] == 1
        adj = late["entries"][0]
        nxt = (ids["month"].replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        assert adj["date"] == str(nxt) and adj["amount"] == "100.00" and adj["narration"].startswith("Changed after")
        tb2 = (await client.get(f"/accounts/trial-balance?date_from={ids['month']}", headers=h)).json()
        assert tb2["totals"]["balanced"] and _row(tb2, "Malabar")["closing"] == "-5000.00"  # 12,000 − 5,000 − 2,000
        # Nothing changes on the next read (no churn).
        assert (await client.post("/accounts/post", headers=h)).json()["after_close"] == 0

        months = (await client.get("/accounts/periods", headers=h)).json()["months"]
        assert next(m for m in months if m["month"] == f"{ids['month']:%Y-%m}")["status"] == "closed"
        _, fin = await _user(test_engine, ids["org"], "FINANCE")
        f = {"Authorization": f"Bearer {fin}"}
        assert (await client.get("/accounts/chart", headers=f)).status_code == 200
        r = await client.post(f"/accounts/periods/{ids['month']:%Y-%m}/reopen", headers=f, json={"reason": "late bill"})
        assert r.status_code == 403
        r = await client.post(f"/accounts/periods/{ids['month']:%Y-%m}/reopen", headers=h, json={"reason": "late bill"})
        assert next(m for m in r.json()["months"] if m["month"] == f"{ids['month']:%Y-%m}")["reopen_reason"] == "late bill"
    finally:
        await _run(test_engine, "DELETE FROM organizations WHERE id = :id", id=ids["org"])


async def test_the_chart_is_seeded_editable_and_kept_to_its_company(client, test_engine):
    ids = await _company(test_engine)
    other = uuid.uuid4()
    try:
        h = {"Authorization": f"Bearer {ids['admin']}"}
        chart = (await client.get("/accounts/chart", headers=h)).json()
        names = {g["name"] for g in chart["groups"]}
        assert {"Sundry Creditors", "Sundry Debtors", "Bank Accounts", "Duties & Taxes", "Direct Expenses"} <= names
        malabar = next(x for x in chart["ledgers"] if x["name"] == "Malabar")
        revenue = next(x for x in chart["ledgers"] if x["code"] == "contract_revenue")
        # A linked ledger is renamed in its module; a seeded one cannot be switched off.
        assert (await client.patch(f"/accounts/ledgers/{malabar['id']}", headers=h, json={"name": "M"})).status_code == 409
        assert (await client.patch(f"/accounts/ledgers/{revenue['id']}", headers=h,
                                   json={"is_active": False})).status_code == 409
        await _run(test_engine, "UPDATE vendors SET name = 'Malabar Steel' WHERE id = :id", id=ids["malabar"])
        chart = (await client.get("/accounts/chart", headers=h)).json()
        assert any(x["name"] == "Malabar Steel" for x in chart["ledgers"])
        # Add a group under Indirect Expenses and a ledger in it; rename the seeded revenue ledger.
        indirect = next(g for g in chart["groups"] if g["code"] == "indirect_expenses")
        g = await client.post("/accounts/groups", headers=h, json={"name": "Office", "parent_id": indirect["id"]})
        assert g.status_code == 201 and g.json()["nature"] == "expense"
        led = await client.post("/accounts/ledgers", headers=h, json={"name": "Office rent", "group_id": g.json()["id"]})
        assert led.status_code == 201
        r = await client.patch(f"/accounts/ledgers/{revenue['id']}", headers=h, json={"name": "Contract receipts"})
        assert r.status_code == 200 and r.json()["name"] == "Contract receipts"
        assert (await client.post("/accounts/groups", headers=h,
                                  json={"name": "office", "parent_id": indirect["id"]})).status_code == 409

        # Money that came in for a receipt no longer there (its project was deleted) stays a client's, never capital.
        await _run(test_engine, "INSERT INTO money_transactions (id, organization_id, transaction_type, to_account_id, amount, "
                   "source_type, source_id, occurred_date, created_by) VALUES (gen_random_uuid(), :o, 'fund_received', :a, 900, "
                   "'client_receipt', gen_random_uuid(), :d, :u)", o=ids["org"], a=ids["bank"], d=ids["day"], u=ids["admin_id"])
        tb = (await client.get(f"/accounts/trial-balance?date_from={ids['month']}", headers=h)).json()
        assert next(r for r in tb["rows"] if r["code"] == "no_client")["closing"] == "-900.00"
        assert next(r for r in tb["rows"] if r["code"] == "funds_introduced")["closing"] == "-20000.00"  # only the real one

        # Who: a project manager and a site engineer never see the books; another company never sees a ledger.
        _, pm = await _user(test_engine, ids["org"], "PROJECT_MANAGER")
        assert (await client.get("/accounts/trial-balance", headers={"Authorization": f"Bearer {pm}"})).status_code == 403
        await _run(test_engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, "
                   "updated_at) VALUES (:id, 'Other', 'local', 'default', 'active', now(), now())", id=other)
        _, stranger = await _user(test_engine, other, "admin")
        s = {"Authorization": f"Bearer {stranger}"}
        assert (await client.get(f"/accounts/ledgers/{malabar['id']}/statement", headers=s)).status_code == 404
        assert (await client.get(f"/accounts/trial-balance?project_id={ids['project']}", headers=s)).status_code == 404
        assert not any(x["name"].startswith("Malabar") for x in (await client.get("/accounts/chart", headers=s)).json()["ledgers"])
    finally:
        await _run(test_engine, "DELETE FROM organizations WHERE id = ANY(:ids)", ids=[ids["org"], other])


async def test_the_books_are_off_until_the_module_is_switched_on(test_engine, monkeypatch):
    ids = await _company(test_engine)
    try:
        app = _app(test_engine, monkeypatch, ["dpr", "finance"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get("/accounts/trial-balance", headers={"Authorization": f"Bearer {ids['admin']}"})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "MODULE_DISABLED"
    finally:
        await _run(test_engine, "DELETE FROM organizations WHERE id = :id", id=ids["org"])
