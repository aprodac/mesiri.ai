"""NXT-12: expenses and payments as Tally vouchers (domains/finance/tally.py)."""

from __future__ import annotations

import datetime
import uuid
import xml.etree.ElementTree as ET
from decimal import Decimal

from mesiri.domains.finance.tally import EXPENSES_PAYABLE, INPUT_GST, build, party_of

DAY = datetime.date(2026, 11, 3)


def _exp(**kw):
    base = {"id": uuid.uuid4(), "expense_number": 41, "occurred_date": DAY, "amount": Decimal("11800"),
            "tax_amount": None, "is_tax_inclusive": True, "description": "Cement 25 bags", "payment_status": "unpaid",
            "category": "Materials", "vendor": "Malabar Hardware", "project": "Villa Kakkanad", "site": "Block A",
            "staff": "Ravi"}
    return {**base, **kw}


def _entries(voucher):
    return [(e.findtext("LEDGERNAME"), e.findtext("ISDEEMEDPOSITIVE"), Decimal(e.findtext("AMOUNT")))
            for e in voucher.findall("ALLLEDGERENTRIES.LIST")]


def test_a_supplier_bill_with_gst_included_splits_the_tax_and_credits_the_supplier():
    xml, counts = build("Malabar Builders", [_exp(tax_amount=Decimal("1800"))], [])
    root = ET.fromstring(xml)
    [voucher] = root.iter("VOUCHER")
    assert voucher.get("VCHTYPE") == "Journal" and voucher.findtext("VOUCHERNUMBER") == "EXP-41"
    assert voucher.findtext("DATE") == "20261103"
    # A debit is "Yes" with a negative amount (Tally's convention); debits and credits balance.
    assert _entries(voucher) == [("Materials", "Yes", Decimal("-10000.00")), (INPUT_GST, "Yes", Decimal("-1800.00")),
                                 ("Malabar Hardware", "No", Decimal("11800.00"))]
    assert sum(a for _, _, a in _entries(voucher)) == 0
    ledgers = {ledger.get("NAME"): ledger.findtext("PARENT") for ledger in root.iter("LEDGER")}
    assert ledgers == {"Malabar Hardware": "Sundry Creditors", "Materials": "Indirect Expenses",
                       INPUT_GST: "Duties & Taxes"}
    assert counts["gst_split"] == 1


def test_gst_said_as_not_included_is_named_never_grossed_up():
    xml, counts = build("C", [_exp(tax_amount=Decimal("1800"), is_tax_inclusive=False)], [])
    [voucher] = ET.fromstring(xml).iter("VOUCHER")
    assert _entries(voucher)[0] == ("Materials", "Yes", Decimal("-11800.00"))
    assert "GST ₹1800.00 said as not included" in voucher.findtext("NARRATION")
    assert counts["gst_not_split"] == 1


def test_who_is_owed_is_the_supplier_the_staff_member_or_expenses_payable():
    assert party_of({"vendor": "Malabar"}) == "Malabar"
    assert party_of({"vendor": None, "payment_status": "reimbursable", "staff": "Ravi"}) == "Ravi (reimbursable)"
    assert party_of({"vendor": None, "payment_status": "unpaid"}) == EXPENSES_PAYABLE


def test_a_payment_debits_the_party_and_credits_the_account_it_left():
    pay = {"id": uuid.uuid4(), "paid_date": DAY, "amount": Decimal("20000"), "payment_method": "UPI",
           "reference_number": "UTR998", "account": "SBI current", "account_type": "bank", "vendor": "Malabar Hardware",
           "expense_number": None, "payment_status": None, "staff": None, "project": None}
    cash = {**pay, "id": uuid.uuid4(), "account": "Site cash", "account_type": "cash", "vendor": None,
            "expense_number": 7, "payment_status": "unpaid", "reference_number": None}
    xml, counts = build("C", [], [pay, cash])
    root = ET.fromstring(xml)
    first, second = list(root.iter("VOUCHER"))
    assert first.get("VCHTYPE") == "Payment" and first.findtext("VOUCHERNUMBER") == "UTR998"
    assert _entries(first) == [("Malabar Hardware", "Yes", Decimal("-20000.00")), ("SBI current", "No", Decimal("20000.00"))]
    assert "on account (advance)" in first.findtext("NARRATION")
    assert _entries(second)[0][0] == EXPENSES_PAYABLE and "against EXP-7" in second.findtext("NARRATION")
    ledgers = {ledger.get("NAME"): ledger.findtext("PARENT") for ledger in root.iter("LEDGER")}
    assert ledgers["SBI current"] == "Bank Accounts" and ledgers["Site cash"] == "Cash-in-Hand"
    assert counts == {"ledgers": 4, "journals": 0, "payments": 2, "sales": 0, "receipts": 0, "gst_split": 0,
                      "gst_not_split": 0}


def test_names_with_xml_characters_are_escaped():
    xml, _ = build("A & B <Builders>", [_exp(vendor="Shah & Sons", description='3" pipe <PVC>')], [])
    root = ET.fromstring(xml)  # parses: nothing broke the XML
    assert root.findtext(".//SVCURRENTCOMPANY") == "A & B <Builders>"
    assert next(root.iter("VOUCHER")).findtext("PARTYLEDGERNAME") == "Shah & Sons"


def test_an_ra_bill_is_a_balanced_sales_voucher_and_money_received_a_receipt():
    bill = {"id": uuid.uuid4(), "ref": "RA-01", "bill_date": DAY, "client": "Mr. Thomas", "project": "Villa",
            "gross": "1116000", "gst": "200880", "net": "1127160", "tds": "22320", "retention": "55800",
            "advance_recovery": "111600"}
    got = {"id": uuid.uuid4(), "kind": "bill", "amount": "1000000", "received_on": DAY, "client": "Mr. Thomas",
           "bill_ref": "RA-01", "account": "HDFC current", "account_type": "bank", "reference": "NEFT778",
           "method": None, "project": "Villa"}
    advance = {**got, "id": uuid.uuid4(), "kind": "advance", "amount": "850000", "reference": None, "bill_ref": None}
    xml, counts = build("C", [], [], [bill], [got, advance])
    root = ET.fromstring(xml)
    sale, receipt, adv = list(root.iter("VOUCHER"))
    assert sale.get("VCHTYPE") == "Sales" and sale.findtext("VOUCHERNUMBER") == "RA-01"
    assert sum(a for _, _, a in _entries(sale)) == 0
    assert ("Mr. Thomas", "Yes", Decimal("-1127160.00")) in _entries(sale)
    assert ("Contract revenue", "No", Decimal("1116000.00")) in _entries(sale)
    assert _entries(receipt) == [("HDFC current", "Yes", Decimal("-1000000.00")), ("Mr. Thomas", "No", Decimal("1000000.00"))]
    assert _entries(adv)[1][0] == "Mobilisation advance received"
    ledgers = {ledger.get("NAME"): ledger.findtext("PARENT") for ledger in root.iter("LEDGER")}
    assert ledgers["Mr. Thomas"] == "Sundry Debtors" and ledgers["Output GST"] == "Duties & Taxes"
    assert (counts["sales"], counts["receipts"]) == (1, 2)
