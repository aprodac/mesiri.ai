"""Accounts reports as Excel workbooks (for the CA): the trial balance, a ledger statement and the day book, from
the same reads the pages use. Money is written as numbers (Excel adds them up), debit and credit in their own columns.
"""

from __future__ import annotations

import io
from decimal import Decimal
from typing import Any

from mesiri.domains.costing.export import _sheet


def _dr(v: Decimal) -> Decimal | None:
    return v if v > 0 else None


def _cr(v: Decimal) -> Decimal | None:
    return -v if v < 0 else None


def _save(book) -> bytes:
    del book["Sheet"]
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def trial_balance(company: str, scope: str, date_from, date_to, tb: dict[str, Any]) -> bytes:
    from openpyxl import Workbook

    groups = {g["id"]: g for g in tb["groups"]}

    def path(gid: str | None) -> str:
        names = []
        while gid:
            g = groups.get(gid)
            if not g:
                break
            names.append(g["name"])
            gid = g["parent_id"]
        return " › ".join(reversed(names))

    rows = [[path(r["group_id"]), r["name"], _dr(r["opening"]), _cr(r["opening"]), r["debit"] or None,
             r["credit"] or None, _dr(r["closing"]), _cr(r["closing"])]
            for r in sorted(tb["rows"], key=lambda r: (path(r["group_id"]), r["name"].lower()))]
    t = tb["totals"]
    rows.append(["", "Total", t["opening_debit"], t["opening_credit"], t["debit"], t["credit"], t["closing_debit"],
                 t["closing_credit"]])
    book = Workbook()
    sheet = _sheet(book, "Trial balance", ["Group", "Ledger", "Opening Dr", "Opening Cr", "Debit", "Credit",
                                           "Closing Dr", "Closing Cr"], rows, [34, 36, 14, 14, 14, 14, 14, 14])
    sheet.insert_rows(1, 2)
    sheet["A1"] = f"{company}: trial balance, {scope}, {date_from} to {date_to}"
    return _save(book)


def ledger_statement(company: str, scope: str, date_from, date_to, st: dict[str, Any]) -> bytes:
    from openpyxl import Workbook

    rows = [[str(date_from), "", "Opening balance", "", _dr(st["opening"]), _cr(st["opening"]), st["opening"]]]
    rows += [[str(r["date"]), r["ref"], r["narration"], r["against"], r["debit"] or None, r["credit"] or None,
              r["balance"]] for r in st["lines"]]
    rows.append([str(date_to), "", "Closing balance", "", st["debit"], st["credit"], st["closing"]])
    book = Workbook()
    sheet = _sheet(book, "Ledger", ["Date", "Voucher", "Narration", "Against", "Debit", "Credit", "Balance (Dr +)"],
                   rows, [12, 20, 50, 30, 14, 14, 16])
    sheet.insert_rows(1, 2)
    sheet["A1"] = f"{company}: {st['ledger']['name']} ({st['ledger']['group_name']}), {scope}, {date_from} to {date_to}"
    return _save(book)


def day_book(company: str, scope: str, date_from, date_to, book_: dict[str, Any]) -> bytes:
    from openpyxl import Workbook

    rows = []
    for e in book_["entries"]:
        for i, ln in enumerate(e["lines"]):
            rows.append([str(e["date"]) if i == 0 else "", e["ref"] if i == 0 else "", e["narration"] if i == 0 else "",
                         ln["ledger"], ln["debit"] or None, ln["credit"] or None, ln["project"], ln["site"],
                         ln["cost_centre"]])
    book = Workbook()
    sheet = _sheet(book, "Day book", ["Date", "Voucher", "Narration", "Ledger", "Debit", "Credit", "Project", "Site",
                                      "Cost centre"], rows, [12, 20, 50, 34, 14, 14, 24, 20, 16])
    sheet.insert_rows(1, 2)
    sheet["A1"] = f"{company}: day book, {scope}, {date_from} to {date_to}"
    return _save(book)


def gst(company: str, date_from, date_to, g: dict[str, Any]) -> bytes:
    """GST for the CA: Summary (GSTR-3B terms), Sales (outward), Purchases (inward, claimable or why not), by GSTIN."""
    from openpyxl import Workbook

    book = Workbook()
    o, i = g["output"], g["input"]
    summary = [
        ["3.1(a) Outward taxable supplies", o["taxable"], o["igst"], o["cgst"], o["sgst"], o["unknown"], o["gst"]],
        ["4(A)(5) Input tax credit (claimable)", i["taxable"], i["igst"], i["cgst"], i["sgst"], i["unknown"], i["gst"]],
        ["Net GST payable", None, None, None, None, None, g["payable"]],
        ["GST paid, not claimable (missed credit)", None, None, None, None, None, g["missed"]],
    ]
    sheet = _sheet(book, "Summary", ["", "Taxable value", "IGST", "CGST", "SGST", "GST (state unknown)", "Total GST"],
                   summary, [40, 16, 14, 14, 14, 18, 14])
    sheet.insert_rows(1, 2)
    sheet["A1"] = f"{company} (GSTIN {g['company_gstin'] or 'not set'}): GST {date_from} to {date_to}"
    _sheet(book, "Sales", ["Date", "Bill", "Client", "GSTIN", "Project", "Rate %", "Taxable", "IGST", "CGST", "SGST", "GST"],
           [[str(r["date"]), r["ref"], r["client"], r["gstin"], r["project"], r["rate"], r["taxable"], r["igst"],
             r["cgst"], r["sgst"], r["gst"]] for r in g["sales"]], [12, 10, 28, 18, 22, 8, 14, 12, 12, 12, 12])
    words = {"no_gstin": "Supplier has no GSTIN", "not_included": "GST said as not included",
             "tax_not_below_amount": "GST not below the amount"}
    _sheet(book, "Purchases", ["Date", "Expense", "Supplier", "GSTIN", "Project", "Taxable", "IGST", "CGST", "SGST",
                               "GST", "Claimable", "Why not"],
           [[str(r["date"]), r["number"], r["supplier"], r["gstin"], r["project"], r["taxable"], r["igst"], r["cgst"],
             r["sgst"], r["gst"], "Yes" if r["claimable"] else "No", words.get(r["reason"] or "", "")]
            for r in g["purchases"]], [12, 12, 28, 18, 22, 14, 12, 12, 12, 12, 10, 26])
    _sheet(book, "By supplier GSTIN", ["Supplier", "GSTIN", "Bills", "Taxable", "GST", "Claimable"],
           [[s["supplier"], s["gstin"], s["bills"], s["taxable"], s["gst"], s["claimable"]] for s in g["by_supplier"]],
           [32, 18, 8, 14, 14, 14])
    return _save(book)


def tds(company: str, date_from, date_to, t: dict[str, Any]) -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    sheet = _sheet(book, "Months", ["Month", "Deducted", "Deposited", "To deposit", "Due by", "Status"],
                   [[m["month"], m["deducted"], m["deposited"], m["left"], str(m["due"]), m["status"]] for m in t["months"]],
                   [10, 14, 14, 14, 12, 12])
    sheet.insert_rows(1, 2)
    sheet["A1"] = f"{company}: TDS {date_from} to {date_to}"
    _sheet(book, "Deducted 194C", ["Date", "Subcontractor", "PAN", "Section", "Bill", "Bill amount", "TDS", "Project"],
           [[str(d["date"]), d["party"], d["pan"], d["section"], d["bill"], d["bill_amount"], d["amount"], d["project"]]
            for d in t["deducted"]], [12, 30, 14, 9, 12, 14, 12, 24])
    _sheet(book, "Deposited", ["Date", "Amount", "From"], [[str(d["date"]), d["amount"], d["from"]] for d in t["deposits"]],
           [12, 14, 28])
    _sheet(book, "Deducted by clients", ["Date", "RA bill", "Client", "PAN", "Project", "Gross", "Rate %", "TDS"],
           [[str(r["date"]), r["ref"], r["client"], r["pan"], r["project"], r["gross"], r["rate"], r["amount"]]
            for r in t["by_clients"]], [12, 10, 28, 14, 24, 14, 8, 12])
    return _save(book)
