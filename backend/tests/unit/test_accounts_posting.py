"""ACC-02/04/05: the posting rules, months and the trial balance, pure (domains/accounts)."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from mesiri.domains.accounts import periods, posting
from mesiri.domains.accounts.reports import HEAD_OFFICE, trial_rows
from mesiri.domains.accounts.sweep import adjustment

DAY = datetime.date(2026, 10, 10)
V, CAT, STAFF, P, S, ACC, ACC2, CLIENT = (uuid.uuid4() for _ in range(8))


def _sides(e):
    return {(ln["ledger"], "Dr" if ln["debit"] else "Cr"): ln["debit"] or ln["credit"] for ln in e["lines"]}


def test_a_supplier_bill_with_claimable_gst_splits_it_and_balances():
    [e] = posting.expense_entries({"id": 1, "date": DAY, "amount": "11800", "claimable_gst": "1800", "category_id": CAT,
                                   "cost_centre": "materials", "vendor_id": V, "project_id": P, "site_id": S})
    assert posting.balanced(e) and e["voucher_type"] == "purchase"
    assert _sides(e) == {(posting.link("expense_category", CAT), "Dr"): Decimal("10000.00"),
                         (posting.code("input_gst"), "Dr"): Decimal("1800.00"),
                         (posting.link("vendor", V), "Cr"): Decimal("11800.00")}
    assert {ln["project_id"] for ln in e["lines"]} == {str(P)} and e["lines"][0]["cost_centre"] == "materials"


def test_gst_not_claimable_stays_in_the_cost_and_no_zero_lines():
    [e] = posting.expense_entries({"id": 1, "date": DAY, "amount": "1180", "claimable_gst": 0, "category_id": CAT})
    assert len(e["lines"]) == 2 and e["voucher_type"] == "journal"
    assert _sides(e)[(posting.code("expenses_payable"), "Cr")] == Decimal("1180.00")


def test_who_is_owed_staff_pocket_then_supplier_then_payable_and_before_the_opening_date():
    assert posting.party(V, "reimbursable", STAFF) == posting.link("staff", STAFF)
    assert posting.party(V, "reimbursed", None) == posting.link("vendor", V)  # nobody to owe: the supplier
    assert posting.party(V, "paid", STAFF) == posting.link("vendor", V)
    assert posting.party(None, "unpaid", None) == posting.code("expenses_payable")
    start = datetime.date(2026, 10, 1)
    assert posting.party(V, None, None, datetime.date(2026, 9, 30), start) == posting.code("opening_difference")
    assert posting.party(V, None, None, start, start) == posting.link("vendor", V)


def test_money_movements_transfer_payment_receipt_and_reversal():
    [t] = posting.money_entries({"amount": "3000", "date": DAY, "from_account_id": ACC, "to_account_id": ACC2,
                                 "to_project_id": P}, None)
    assert t["voucher_type"] == "contra" and posting.balanced(t)
    assert _sides(t) == {(posting.link("money_account", ACC2), "Dr"): Decimal("3000.00"),
                         (posting.link("money_account", ACC), "Cr"): Decimal("3000.00")}
    paid = {"ledger": posting.link("vendor", V), "project_id": P, "words": "Paid Malabar"}
    [p] = posting.money_entries({"amount": "5000", "date": DAY, "from_account_id": ACC}, paid)
    assert p["voucher_type"] == "payment" and _sides(p)[(posting.link("vendor", V), "Dr")] == Decimal("5000.00")
    assert {ln["project_id"] for ln in p["lines"]} == {str(P)}  # the bank side is the project's payment too
    [back] = posting.money_entries({"amount": "5000", "date": DAY, "to_account_id": ACC}, paid)  # payment undone
    assert _sides(back)[(posting.link("vendor", V), "Cr")] == Decimal("5000.00")
    got = {"ledger": posting.link("client", CLIENT), "project_id": P}
    [r] = posting.money_entries({"amount": "50000", "date": DAY, "to_account_id": ACC}, got)
    assert r["voucher_type"] == "receipt" and _sides(r)[(posting.link("money_account", ACC), "Dr")] == Decimal("50000.00")
    assert posting.money_entries({"amount": "100", "date": DAY, "from_account_id": ACC}, None) == []


def test_an_ra_bill_sent_balances_and_a_draft_posts_nothing():
    bill = {"id": 1, "ref": "RA-01", "date": DAY, "status": "submitted", "client_id": CLIENT, "gross": "100000",
            "gst": "18000", "retention": "5000", "advance_recovery": "0", "tds": "2000", "net": "111000", "project_id": P}
    [e] = posting.ra_bill_entries(bill)
    assert posting.balanced(e) and e["voucher_type"] == "sales"
    assert _sides(e) == {(posting.link("client", CLIENT), "Dr"): Decimal("111000.00"),
                         (posting.code("tds_receivable"), "Dr"): Decimal("2000.00"),
                         (posting.code("retention_receivable"), "Dr"): Decimal("5000.00"),
                         (posting.code("contract_revenue"), "Cr"): Decimal("100000.00"),
                         (posting.code("output_gst"), "Cr"): Decimal("18000.00")}
    assert posting.ra_bill_entries({**bill, "status": "draft"}) == []
    # An older bill whose stored net is a paisa out still balances, the paisa on Round off.
    [odd] = posting.ra_bill_entries({**bill, "client_id": None, "net": "110999.99"})
    assert posting.balanced(odd) and _sides(odd)[(posting.code("round_off"), "Dr")] == Decimal("0.01")
    assert (posting.code("no_client"), "Dr") in _sides(odd)


def test_opening_balances_go_against_the_opening_difference_either_way():
    [a] = posting.opening_account_entries({"id": ACC, "name": "SBI", "opening_balance": "-500",
                                           "opening_balance_date": DAY})
    assert _sides(a) == {(posting.link("money_account", ACC), "Cr"): Decimal("500.00"),
                         (posting.code("opening_difference"), "Dr"): Decimal("500.00")}
    [v] = posting.opening_vendor_entries({"id": V, "name": "Malabar", "opening_balance": "2500",
                                          "opening_balance_date": DAY})
    assert _sides(v)[(posting.link("vendor", V), "Cr")] == Decimal("2500.00")
    assert posting.opening_vendor_entries({"id": V, "opening_balance": "0", "opening_balance_date": DAY}) == []


def test_the_fingerprint_changes_with_the_record_and_not_otherwise():
    e = posting.expense_entries({"id": 1, "date": DAY, "amount": "100", "category_id": CAT})
    assert posting.fingerprint(e) == posting.fingerprint(posting.expense_entries(
        {"id": 1, "date": DAY, "amount": "100.00", "category_id": CAT}))
    assert posting.fingerprint(e) != posting.fingerprint(posting.expense_entries(
        {"id": 1, "date": DAY, "amount": "101", "category_id": CAT}))


def test_financial_years_and_the_first_open_day_after_closed_months():
    assert periods.fy_label(datetime.date(2026, 3, 31)) == "2025-26"
    assert periods.fy_label(datetime.date(2026, 4, 1)) == "2026-27"
    assert periods.fy_start(datetime.date(2027, 2, 1)) == datetime.date(2026, 4, 1)
    assert periods.month_end(datetime.date(2026, 2, 3)) == datetime.date(2026, 2, 28)
    oct_, nov = ((datetime.date(2026, 10, 1), datetime.date(2026, 10, 31)),
                 (datetime.date(2026, 11, 1), datetime.date(2026, 11, 30)))
    assert periods.first_open_day([oct_, nov], DAY) == datetime.date(2026, 12, 1)
    assert periods.first_open_day([nov], DAY) == DAY


def test_a_change_after_close_posts_only_the_difference_and_balances():
    old = posting.expense_entries({"id": 1, "date": DAY, "amount": "11800", "claimable_gst": "1800",
                                   "category_id": CAT, "vendor_id": V})
    new = posting.expense_entries({"id": 1, "date": DAY, "amount": "12000", "claimable_gst": "1800",
                                   "category_id": CAT, "vendor_id": V})
    adj = adjustment(new, old[0]["lines"], datetime.date(2026, 11, 1), "Changed after Oct 2026 was closed")
    assert posting.balanced(adj)
    assert _sides(adj) == {(posting.link("expense_category", CAT), "Dr"): Decimal("200.00"),
                           (posting.link("vendor", V), "Cr"): Decimal("200.00")}
    assert adjustment(old, old[0]["lines"], DAY, "x") is None  # nothing changed: nothing posted
    gone = adjustment([], old[0]["lines"], DAY, "removed")  # the record was taken back: all of it reversed
    assert _sides(gone)[(posting.link("vendor", V), "Dr")] == Decimal("11800.00")


def test_trial_balance_rows_earlier_years_and_the_head_office_line():
    reserves, liab = uuid.uuid4(), uuid.uuid4()
    groups = {reserves: {"id": reserves, "code": "reserves"}, liab: {"id": liab, "code": "current_liabilities"}}
    bank, exp = uuid.uuid4(), uuid.uuid4()
    ledgers = {bank: {"name": "SBI", "group_id": liab, "nature": "asset", "code": None, "link_kind": None, "link_id": None},
               exp: {"name": "Cement", "group_id": liab, "nature": "expense", "code": None, "link_kind": None,
                     "link_id": None}}
    raw = [{"ledger_id": bank, "opening": "-900", "earlier": 0, "debit": "0", "credit": "100"},
           {"ledger_id": exp, "opening": "0", "earlier": "900", "debit": "100", "credit": "0"}]
    out = trial_rows(raw, ledgers, groups, scoped=False)
    assert any(r["name"] == "Profit or loss of earlier years" and r["closing"] == Decimal(900) for r in out["rows"])
    assert out["totals"]["balanced"]
    # A project's lines alone: the cash came from the head office, said as one line, so it still balances.
    scoped = trial_rows([{"ledger_id": exp, "opening": 0, "earlier": 0, "debit": "300", "credit": "0"}], ledgers, groups,
                        scoped=True)
    ho = next(r for r in scoped["rows"] if r["code"] == HEAD_OFFICE)
    assert ho["credit"] == Decimal(300) and scoped["totals"]["balanced"]
