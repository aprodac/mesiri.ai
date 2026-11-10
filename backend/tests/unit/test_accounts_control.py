"""ACC-12..21, the pure parts: manual voucher rules, bank statement reading and matching, depreciation, the delivery
accrual, the asset entries, cash-flow heads, the Tally export from journals, and the report writers."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest

from mesiri.domains.accounts import (
    bank,
    depreciation,
    export,
    posting,
    statements,
    tally_books,
    vouchers,
)

D = datetime.date


# --- ACC-12 -------------------------------------------------------------------------------------------------------

def test_a_voucher_needs_two_balanced_one_sided_lines():
    a, b = uuid.uuid4(), uuid.uuid4()
    assert vouchers.check_lines([{"ledger_id": a, "debit": "100.50"}, {"ledger_id": b, "credit": "100.50"}]) == (
        Decimal("100.50"), Decimal("100.50"))
    with pytest.raises(vouchers.VoucherError, match="at least two"):
        vouchers.check_lines([{"ledger_id": a, "debit": 1}])
    with pytest.raises(vouchers.VoucherError, match="differ by ₹0.50"):
        vouchers.check_lines([{"ledger_id": a, "debit": "100.50"}, {"ledger_id": b, "credit": 100}])
    with pytest.raises(vouchers.VoucherError, match="not both"):
        vouchers.check_lines([{"ledger_id": a, "debit": 5, "credit": 5}, {"ledger_id": b, "credit": 0}])
    with pytest.raises(vouchers.VoucherError, match="never negative"):
        vouchers.check_lines([{"ledger_id": a, "debit": -5}, {"ledger_id": b, "credit": -5}])
    with pytest.raises(vouchers.VoucherError, match="paisa"):
        vouchers.check_lines([{"ledger_id": a, "debit": "1.005"}, {"ledger_id": b, "credit": "1.005"}])


def test_a_cancelled_voucher_posts_nothing_and_a_posted_one_posts_as_typed():
    a, b, p = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    v = {"id": uuid.uuid4(), "date": D(2026, 10, 31), "status": "posted", "narration": "Provision for audit fee",
         "lines": [{"ledger_id": a, "debit": Decimal(25000), "credit": 0, "project_id": p, "site_id": None,
                    "cost_centre": None},
                   {"ledger_id": b, "debit": 0, "credit": Decimal(25000), "project_id": p, "site_id": None,
                    "cost_centre": None}]}
    [e] = posting.voucher_entries(v)
    assert posting.balanced(e) and e["voucher_type"] == "journal" and e["project_id"] == str(p)
    assert e["lines"][0]["ledger"] == ("id", str(a)) and e["lines"][0]["debit"] == Decimal("25000.00")
    assert posting.voucher_entries({**v, "status": "cancelled"}) == []


# --- ACC-13 -------------------------------------------------------------------------------------------------------

HDFC = (b"Statement of account\nAccount No: 5010\n\n"
        b"Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"
        b"01/10/26,NEFT-MALABAR STEEL-UTR123,UTR123,01/10/26,\"5,000.00\",,\"95,000.00\"\n"
        b"02/10/26,CHRG: SMS ALERT,,02/10/26,17.70,,\"94,982.30\"\n"
        b"03/10/26,NEFT CR-MEHTA BUILDERS,,03/10/26,,\"50,000.00\",\"1,44,982.30\"\n"
        b"03/10/26,CHRG: SMS ALERT,,03/10/26,17.70,,\"1,44,964.60\"\n")
SBI = (b"Txn Date\tValue Date\tDescription\tRef No./Cheque No.\tDebit\tCredit\tBalance\n"
       b"5 Oct 2026\t5 Oct 2026\tBY TRANSFER-INTEREST\t\t\t312.00\t1,00,312.00\n"
       b"6-Oct-2026\t6-Oct-2026\tTO CLG 000123\t000123\t20000\t\t80,312.00\n")
ICICI = (b"S No.,Transaction Date,Transaction Remarks,Amount(INR),Dr/Cr,Balance(INR)\n"
         b"1,2026-10-07,UPI/ACME CEMENT/9876,1200.00,DR,79112.00\n2,2026-10-08,CASH DEP,500,CR,79612.00\n")


def test_statements_of_the_big_banks_are_read_with_their_own_headers():
    h = bank.parse(HDFC, "hdfc.csv")
    assert h["header_row"] == 4 and [ln["amount"] for ln in h["lines"]] == [
        Decimal("-5000.00"), Decimal("-17.70"), Decimal("50000.00"), Decimal("-17.70")]
    assert h["lines"][0]["date"] == D(2026, 10, 1) and h["lines"][0]["reference"] == "UTR123"
    assert h["lines"][2]["balance"] == Decimal("144982.30")
    s = bank.parse(SBI, "sbi.csv")
    assert [(ln["date"], ln["amount"]) for ln in s["lines"]] == [(D(2026, 10, 5), Decimal("312.00")),
                                                                 (D(2026, 10, 6), Decimal("-20000.00"))]
    assert s["lines"][1]["reference"] == "000123"
    i = bank.parse(ICICI, "icici.csv")
    assert [ln["amount"] for ln in i["lines"]] == [Decimal("-1200.00"), Decimal("500.00")]
    with pytest.raises(bank.StatementError, match="header row"):
        bank.parse(b"a,b\n1,2\n", "x.csv")
    with pytest.raises(bank.StatementError, match=".xls"):
        bank.parse(b"\xd0\xcf", "old.xls")


def test_dates_money_and_duplicates():
    assert bank.parse_date("15-Oct-26") == D(2026, 10, 15)
    assert bank.parse_date(46310) == D(2026, 10, 15)
    assert bank.parse_date("31/02/2026") is None
    assert bank.parse_money("1,23,456.50 Dr") == Decimal("-123456.50")
    assert bank.parse_money("(500)") == Decimal("-500.00") and bank.parse_money("-") is None
    lines = bank.parse(HDFC, "hdfc.csv")["lines"]
    keys = bank.dedupe_keys(lines)
    assert len(set(keys)) == 4  # the two ₹17.70 charges on different days stay two lines
    twice = bank.dedupe_keys([lines[1], {**lines[1]}])
    assert twice[0] != twice[1]  # the same charge twice on one day stays two lines
    assert bank.dedupe_keys(lines) == keys  # and an overlapping statement finds them again


def test_a_line_matches_one_clear_movement_by_amount_direction_date_and_reference():
    line = {"date": D(2026, 10, 1), "amount": Decimal(-5000), "description": "NEFT-MALABAR STEEL-UTR123",
            "reference": "UTR123"}
    m = lambda i, d, ref=None, inflow=False, amount=5000: {"id": i, "date": d, "amount": Decimal(amount),  # noqa: E731
                                                          "inflow": inflow, "reference": ref}
    assert bank.best_match(line, [m(1, D(2026, 9, 29))])["id"] == 1
    assert bank.best_match(line, [m(1, D(2026, 9, 27))]) is None  # four days off
    assert bank.best_match(line, [m(1, D(2026, 10, 1), inflow=True)]) is None  # money the other way
    assert bank.best_match(line, [m(1, D(2026, 10, 1)), m(2, D(2026, 10, 1), "UTR123")])["id"] == 2
    assert bank.best_match(line, [m(1, D(2026, 10, 2)), m(2, D(2026, 10, 1))])["id"] == 2  # nearer
    assert bank.best_match(line, [m(1, D(2026, 10, 2)), m(2, D(2026, 9, 30))]) is None  # a tie waits for a tap


# --- ACC-16 -------------------------------------------------------------------------------------------------------

def _asset(**kw):
    return {"cost": Decimal(1000000), "acquired_on": D(2024, 5, 10), "put_to_use_on": None, "method": "wdv",
            "rate": Decimal(15), "useful_life_years": None, "salvage_value": 0, "opening_depreciation": 0,
            "books_from": None, "disposed_on": None, **kw}


def test_wdv_at_income_tax_rates_with_the_half_rate_under_180_days():
    years = depreciation.schedule(_asset(), D(2026, 11, 10))
    assert [(y["financial_year"], y["depreciation"], y["closing"], y["posted"]) for y in years] == [
        ("2024-25", Decimal("150000.00"), Decimal("850000.00"), True),
        ("2025-26", Decimal("127500.00"), Decimal("722500.00"), True),
        ("2026-27", Decimal("108375.00"), Decimal("614125.00"), False)]  # this year: posted on 31 March
    late = depreciation.schedule(_asset(acquired_on=D(2024, 11, 1)), D(2025, 6, 1))
    assert late[0]["depreciation"] == Decimal("75000.00")  # 151 days in use: half the rate
    assert depreciation.value_on(_asset(), D(2026, 11, 10), D(2026, 11, 10)) == Decimal("722500.00")


def test_slm_by_days_in_use_and_never_below_salvage_and_owned_before_the_books():
    a = _asset(method="slm", rate=None, useful_life_years=Decimal(10), salvage_value=Decimal(50000),
               acquired_on=D(2025, 10, 1))
    y = depreciation.schedule(a, D(2027, 6, 1))
    assert y[0]["depreciation"] == Decimal("47369.86")  # 95,000 a year × 182 / 365
    assert y[1]["depreciation"] == Decimal("95000.00")
    old = _asset(acquired_on=D(2019, 4, 1), books_from=D(2026, 4, 1), opening_depreciation=Decimal(600000))
    y = depreciation.schedule(old, D(2027, 6, 1))
    assert y[0]["financial_year"] == "2026-27" and y[0]["opening"] == Decimal("400000.00")
    sold = depreciation.schedule(_asset(disposed_on=D(2025, 12, 1)), D(2026, 11, 10))
    assert sold[-1]["financial_year"] == "2025-26" and sold[-1]["depreciation"] == 0  # no WDV in the year of sale
    assert sold[-1]["posted"] and sold[-1]["post_on"] == D(2025, 12, 1)


def test_asset_entries_move_the_bill_to_the_asset_write_it_down_and_sell_it():
    cat = uuid.uuid4()
    a = {**_asset(disposed_on=D(2025, 12, 1), disposal_value=Decimal(800000)), "name": "JCB 3DX",
         "expense_id": uuid.uuid4(), "expense_date": D(2024, 5, 10), "expense_category_id": cat, "project_id": None,
         "site_id": None}
    es = posting.asset_entries(a, depreciation.schedule(a, D(2026, 11, 10)), "fa_plant")
    assert [e["part"] for e in es] == ["cost", "dep:2024-25", "disposal"]
    assert all(posting.balanced(e) for e in es)
    cost = es[0]
    assert {ln["ledger"]: ln["debit"] or -ln["credit"] for ln in cost["lines"]} == {
        ("code", "fa_plant"): Decimal(1000000), ("link", "expense_category", str(cat)): Decimal(-1000000)}
    sale = {ln["ledger"][1]: ln["debit"] - ln["credit"] for ln in es[2]["lines"]}
    # Book value 8,50,000 out; 8,00,000 to receive; 50,000 lost.
    assert sale == {"fa_plant": Decimal(-850000), "asset_sale_receivable": Decimal(800000),
                    "asset_disposal": Decimal(50000)}
    opening = posting.asset_entries({**_asset(books_from=D(2026, 4, 1), opening_depreciation=Decimal(300000)),
                                     "name": "Mixer", "expense_id": None, "project_id": None, "site_id": None},
                                    [], "fa_plant")
    assert opening[0]["date"] == D(2026, 4, 1) and opening[0]["lines"][1]["ledger"] == ("code", "opening_difference")
    assert opening[0]["lines"][0]["debit"] == Decimal("700000.00")


# --- ACC-15 -------------------------------------------------------------------------------------------------------

def test_the_month_end_accrual_reverses_on_the_first():
    p = uuid.uuid4()
    es = posting.accrual_entries(D(2026, 10, 31), [{"project_id": p, "site_id": None, "amount": Decimal("12500.50")}],
                                 "Deliveries not billed at 31 Oct 2026 (3)")
    assert [(e["part"], e["date"]) for e in es] == [("main", D(2026, 10, 31)), ("reverse", D(2026, 11, 1))]
    main = {ln["ledger"][1]: (ln["debit"], ln["credit"], ln["cost_centre"]) for ln in es[0]["lines"]}
    assert main == {"materials_unbilled": (Decimal("12500.50"), 0, "materials"), "grni": (0, Decimal("12500.50"), None)}
    assert es[1]["lines"][0]["credit"] == Decimal("12500.50")
    assert posting.accrual_entries(D(2026, 10, 31), [], "nothing") == []


# --- ACC-18 / ACC-19 / ACC-21 -------------------------------------------------------------------------------------

def test_cash_heads_follow_the_other_side():
    assert statements.cash_head({"link_kind": "client"}, "current_assets") == "clients"
    assert statements.cash_head({"code": "advance_received"}, "current_liabilities") == "clients"
    assert statements.cash_head({"link_kind": "vendor"}, "current_liabilities") == "suppliers"
    assert statements.cash_head({"code": "wages_payable"}, "current_liabilities") == "labour"
    assert statements.cash_head({"code": "fa_plant"}, "fixed_assets") == "assets"
    assert statements.cash_head({"code": "funds_introduced"}, "capital") == "capital"
    assert statements.cash_head({"link_kind": "money_account"}, "duties_taxes") == "taxes"  # TDS deposited
    assert statements.cash_head({"code": "opening_difference"}, "suspense") == "opening"
    assert statements.cash_head({"code": "bank_charges"}, "indirect_expenses") == "other_operating"


def test_tally_from_the_books_sends_masters_then_vouchers_with_tally_group_names():
    sundry, office = uuid.uuid4(), uuid.uuid4()
    groups = [{"id": sundry, "parent_id": None, "name": "Creditors (renamed)", "code": "sundry_creditors"},
              {"id": office, "parent_id": None, "name": "Office", "code": None}]
    groups[1]["parent_id"] = uuid.uuid4()
    groups.append({"id": groups[1]["parent_id"], "parent_id": None, "name": "Indirect Expenses",
                   "code": "indirect_expenses"})
    malabar, rent = uuid.uuid4(), uuid.uuid4()
    ledgers = {malabar: {"name": "Malabar & Sons", "group_id": sundry, "link_kind": "vendor"},
               rent: {"name": "Office rent", "group_id": office, "link_kind": None}}
    e = {"id": uuid.uuid4(), "entry_date": D(2026, 10, 3), "voucher_type": "journal", "ref": "JOU/2026-27/4",
         "narration": "Rent <Oct>", "after_close": False}
    lines = {e["id"]: [{"ledger_id": rent, "debit": Decimal(9000), "credit": Decimal(0)},
                       {"ledger_id": malabar, "debit": Decimal(0), "credit": Decimal(9000)}]}
    xml, counts = tally_books.build("Acme", groups, ledgers, [e], lines)
    assert '<GROUP NAME="Office"' in xml and "<PARENT>Indirect Expenses</PARENT>" in xml
    assert "<PARENT>Sundry Creditors</PARENT>" in xml  # Tally's own name, not the renamed one
    assert xml.index("<GROUP ") < xml.index("<LEDGER ") < xml.index("<VOUCHER ")
    assert "Malabar &amp; Sons" in xml and "Rent &lt;Oct&gt;" in xml
    assert f'REMOTEID="mesiri-je-{e["id"]}"' in xml and "<AMOUNT>-9000.00</AMOUNT>" in xml
    assert "<PARTYLEDGERNAME>Malabar &amp; Sons</PARTYLEDGERNAME>" in xml
    assert counts["vouchers"] == 1 and counts["by_type"] == {"journal": 1} and counts["total"] == "9000.00"


def test_indian_grouping_and_both_file_kinds_from_one_description():
    assert export.inr(Decimal("12345678.5")) == "1,23,45,678.50"
    assert export.inr(Decimal("-999")) == "(999.00)" and export.inr(0) == "0.00"
    d = export.doc("Acme: cash flow", "whole company, 01 Apr 2026 to 10 Nov 2026", [
        export.table("Cash flow", ["Section", "For", "Net"],
                     [["Operating", "Received from clients — RA-01 ₹", Decimal("150000.00")],
                      ["Closing", "", Decimal("-20.00")]], [30, 60, 20], 1),
        export.table("Empty", ["A"], [], [20])])
    pdf, media, ext = export.render(d, "pdf")
    assert pdf[:5] == b"%PDF-" and media == "application/pdf" and ext == "pdf"
    xlsx, media, ext = export.render(d, "xlsx")
    assert xlsx[:2] == b"PK" and ext == "xlsx"
