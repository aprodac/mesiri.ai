"""ACC-13 / FB-03: reading bank statements and matching them to the books (pure parts)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from mesiri.domains.accounts import bankrec

D = dt.date

# An SBI-style export: account details first, then the table; separate Debit / Credit columns.
SBI = """Account Name :,GREEN BUILDERS
Account Number :,00000012345678901
Period :,01 Nov 2026 to 10 Nov 2026

Txn Date,Value Date,Description,Ref No./Cheque No.,Debit,Credit,Balance
01 Nov 2026,01 Nov 2026,BY TRANSFER-NEFT*THOMAS K*N30512,N305126789,,"3,20,000.00","5,20,000.00"
03 Nov 2026,03 Nov 2026,TO CHQ 000451 MALABAR STEELS,000451,"1,25,000.00",,"3,95,000.00"
05 Nov 2026,05 Nov 2026,SMS CHARGES QTR,,17.70,,"3,94,982.30"
,,Closing balance,,,,"3,94,982.30"
"""

# An HDFC-style export: dd/mm/yy dates, its own column names.
HDFC = """Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance
02/11/26,UPI-RAVI CEMENT-OKAXIS,0000430612345,02/11/26,"45,000.00",,"1,55,000.00"
30/11/26,CREDIT INTEREST,,30/11/26,,212.00,"1,55,212.00"
"""

# One Amount column with Dr / Cr beside it.
DRCR = """Transaction Date,Particulars,Amount,Dr/Cr,Balance
2026-11-04,ATM WDL,"10,000.00",Dr,90000.00
2026-11-06,CASH DEP,"5,000.00",Cr,95000.00
"""


def test_reads_an_sbi_statement_below_its_account_details() -> None:
    out = bankrec.parse(SBI)
    assert [(ln["date"], ln["amount"]) for ln in out["lines"]] == [
        (D(2026, 11, 1), Decimal("320000.00")), (D(2026, 11, 3), Decimal("-125000.00")),
        (D(2026, 11, 5), Decimal("-17.70"))]
    first = out["lines"][0]
    assert first["reference"] == "N305126789" and first["balance"] == Decimal("520000.00")
    assert "THOMAS" in first["description"]
    assert out["from"] == D(2026, 11, 1) and out["to"] == D(2026, 11, 5)
    assert out["skipped"] == []  # the closing-balance line is not a transaction, and not reported as one


def test_reads_hdfc_and_dr_cr_layouts() -> None:
    hdfc = bankrec.parse(HDFC)["lines"]
    assert [(ln["date"], ln["amount"]) for ln in hdfc] == [(D(2026, 11, 2), Decimal("-45000.00")),
                                                          (D(2026, 11, 30), Decimal("212.00"))]
    drcr = bankrec.parse(DRCR)["lines"]
    assert [ln["amount"] for ln in drcr] == [Decimal("-10000.00"), Decimal("5000.00")]


@pytest.mark.parametrize("raw,day", [("05/11/2026", D(2026, 11, 5)), ("05-11-26", D(2026, 11, 5)),
                                     ("05-Nov-2026", D(2026, 11, 5)), ("5 Nov 26", D(2026, 11, 5)),
                                     ("2026-11-05", D(2026, 11, 5)), ("31/02/2026", None), ("Total", None)])
def test_dates_day_first(raw, day) -> None:
    assert bankrec.parse_date(raw) == day


def test_a_file_with_no_table_says_what_to_do() -> None:
    with pytest.raises(bankrec.StatementError) as e:
        bankrec.parse("hello,world\n1,2\n")
    assert "CSV" in str(e.value)


def test_same_line_twice_in_one_file_gets_two_keys_and_a_reimport_the_same_keys() -> None:
    line = {"date": D(2026, 11, 5), "amount": Decimal("-17.70"), "description": "SMS", "reference": None,
            "balance": None}
    keys = [x["line_key"] for x in bankrec.keyed([line, dict(line)])]
    assert keys[0] != keys[1]
    assert [x["line_key"] for x in bankrec.keyed([line, dict(line)])] == keys


def test_auto_match_same_amount_nearest_date_one_to_one() -> None:
    statement = [
        {"id": "s1", "date": D(2026, 11, 3), "amount": Decimal("-125000"), "reference": "000451"},
        {"id": "s2", "date": D(2026, 11, 4), "amount": Decimal("-125000"), "reference": None},
        {"id": "s3", "date": D(2026, 11, 5), "amount": Decimal("-17.70"), "reference": None},
        {"id": "s4", "date": D(2026, 11, 1), "amount": Decimal("320000"), "reference": None},
    ]
    books = [
        {"key": "b-far", "date": D(2026, 11, 20), "amount": Decimal("320000"), "words": "Thomas"},  # too far
        {"key": "b1", "date": D(2026, 10, 31), "amount": Decimal("-125000"), "words": "Malabar chq 000451"},
        {"key": "b2", "date": D(2026, 11, 4), "amount": Decimal("-125000"), "words": "Malabar"},
    ]
    pairs = dict(bankrec.auto_match(statement, books))
    # s1's cheque number is in b1's words: that beats b2's nearer date; s2 takes what is left (same day).
    assert pairs == {"s1": "b1", "s2": "b2"}


def test_nearest_date_wins_when_no_reference_says_otherwise() -> None:
    statement = [{"id": "s1", "date": D(2026, 11, 3), "amount": Decimal("-900"), "reference": None}]
    books = [{"key": "far", "date": D(2026, 11, 7), "amount": Decimal("-900"), "words": "Diesel"},
             {"key": "near", "date": D(2026, 11, 2), "amount": Decimal("-900"), "words": "Diesel"}]
    assert bankrec.auto_match(statement, books) == [("s1", "near")]


def test_reference_breaks_a_tie_between_two_equally_near_entries() -> None:
    statement = [{"id": "s1", "date": D(2026, 11, 3), "amount": Decimal("-500"), "reference": "CHQ 000777"}]
    books = [{"key": "a", "date": D(2026, 11, 2), "amount": Decimal("-500"), "words": "Diesel"},
             {"key": "b", "date": D(2026, 11, 4), "amount": Decimal("-500"), "words": "Paid by chq 000777"}]
    assert bankrec.auto_match(statement, books) == [("s1", "b")]
