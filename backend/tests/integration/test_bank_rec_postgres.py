"""ACC-13 / FB-03: a bank statement imported and reconciled against the books, on a real Postgres.

The client's ₹3,20,000 recorded in Mesiri on 1 Nov reaches the bank on 2 Nov: auto-matched. The bank's ₹17.70 SMS
charge is not in the books: booked in one tap (a Journal against Bank charges) and matched, so the books' balance
moves with it. A line the bank reversed is ignored with a reason. Importing the same file again adds nothing.
Rolled back after the test."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.authorization.context import AuthorizationContext, ProjectAccessScope, SiteAccessScope
from mesiri.domains.accounts import router as accounts
from mesiri.domains.billing import router as billing

from .test_live_questions_postgres import NOW, conn  # noqa: F401 -- the shared fixture

pytestmark = pytest.mark.integration

STATEMENT = """Account Name :,STAGE BUILDERS
Txn Date,Value Date,Description,Ref No./Cheque No.,Debit,Credit,Balance
02 Nov 2026,02 Nov 2026,BY TRANSFER-NEFT*MR THOMAS,N305126789,,"3,20,000.00","3,20,000.00"
05 Nov 2026,05 Nov 2026,SMS CHARGES QTR,,17.70,,"3,19,982.30"
06 Nov 2026,06 Nov 2026,REV OF WRONG DEBIT,,"999.00",,"3,18,983.30"
"""


async def test_import_match_book_ignore_and_reimport(conn) -> None:  # noqa: F811
    made = await create_company(
        conn, NewCompany(name="Rec Builders", owner_name="Ravi Kumar", owner_phone="+919876500411",
                         project_name="Green Villa", site_names=("Main block",), auto_dpr=False), now=NOW)
    org, project = made.organization_id, made.project_id
    owner = AuthorizationContext(user_id=made.owner_user_id, organization_id=org, role="ADMIN", status="active",
                                 access_policy={},  # type: ignore[arg-type]
                                 project_scope=ProjectAccessScope(mode="all_projects", project_ids=set()),
                                 site_scopes={project: SiteAccessScope(mode="all_sites", site_ids=set())})
    bank, cash = uuid.uuid4(), uuid.uuid4()
    for acc, kind, name in ((bank, "bank", "Current account"), (cash, "cash", "Office cash")):
        await conn.execute(text(
            "INSERT INTO money_accounts (id, organization_id, account_type, name, opening_balance, "
            "opening_balance_date, created_by) VALUES (:id, :o, :k, :n, 0, :d, :u)"),
            {"id": acc, "o": org, "k": kind, "n": name, "d": dt.date(2026, 10, 1), "u": made.owner_user_id})
    await billing.put_contract(project, billing.ContractIn(new_client=billing.ClientIn(name="Mr Thomas")),
                               auth=owner, conn=conn)
    await billing.record_client_receipt(billing.ReceiptIn(
        project_id=project, kind="on_account", amount=Decimal(320000), account_id=bank,
        received_on=dt.date(2026, 11, 1)), auth=owner, conn=conn)

    # Only a bank account's statement is reconciled.
    with pytest.raises(HTTPException) as e:
        await accounts.bank_rec(cash, auth=owner, conn=conn)
    assert e.value.status_code == 422

    done = await accounts.bank_rec_import(bank, accounts.StatementIn(file_name="nov.csv", content=STATEMENT),
                                          auth=owner, conn=conn)
    assert done["added"] == 3 and done["repeated"] == 0 and done["matched"] == 1

    rec = await accounts.bank_rec(bank, auth=owner, conn=conn)
    assert rec["counts"] == {"unmatched": 2, "matched": 1, "ignored": 0}
    lines = {ln["description"]: ln for ln in rec["lines"]}
    receipt = lines["BY TRANSFER-NEFT*MR THOMAS"]
    assert receipt["status"] == "matched" and receipt["entry"]["amount"] == "320000.00"
    assert rec["statement_balance"] == "318983.30" and rec["book_balance"] == "320000.00"

    # The bank's charge, booked in one tap: a Journal against Bank charges, matched; the books follow the bank.
    sms = uuid.UUID(lines["SMS CHARGES QTR"]["id"])
    await accounts.bank_rec_book(sms, accounts.BookIn(), auth=owner, conn=conn)
    entry = (await conn.execute(text(
        "SELECT e.voucher_type, l.debit FROM journal_entries e JOIN journal_lines l ON l.entry_id = e.id "
        "JOIN ledgers g ON g.id = l.ledger_id WHERE e.organization_id = :o AND g.code = 'bank_charges'"),
        {"o": org})).one()
    assert entry.voucher_type == "journal" and entry.debit == Decimal("17.70")
    with pytest.raises(HTTPException):  # booked once
        await accounts.bank_rec_book(sms, accounts.BookIn(), auth=owner, conn=conn)

    wrong = uuid.UUID(lines["REV OF WRONG DEBIT"]["id"])
    await accounts.bank_rec_ignore(wrong, accounts.IgnoreIn(note="Bank error, reversed next day"), auth=owner,
                                   conn=conn)
    rec = await accounts.bank_rec(bank, auth=owner, conn=conn)
    assert rec["counts"] == {"unmatched": 0, "matched": 2, "ignored": 1}
    assert rec["book_balance"] == "319982.30"
    assert rec["books_unmatched"] == []

    # A match can't take an entry of another amount, nor one already matched.
    await accounts.bank_rec_reopen(wrong, auth=owner, conn=conn)
    with pytest.raises(HTTPException) as e:
        await accounts.bank_rec_match(wrong, accounts.MatchIn(entry_id=uuid.UUID(receipt["entry"]["entry_id"])),
                                      auth=owner, conn=conn)
    assert "same amount" in e.value.detail

    again = await accounts.bank_rec_import(bank, accounts.StatementIn(file_name="nov.csv", content=STATEMENT),
                                           auth=owner, conn=conn)
    assert again["added"] == 0 and again["repeated"] == 3
