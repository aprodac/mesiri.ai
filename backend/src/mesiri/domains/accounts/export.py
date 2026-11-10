"""ACC-05 / ACC-21: every Accounts report as a file for the CA, Excel or PDF, from the same reads the pages use.

One pipeline: each report is described once as a ``Doc`` (a title, what it covers, and one or more tables), and
``render`` writes that as an Excel workbook (a sheet per table; money as numbers, so Excel adds them up; debit and
credit in their own columns) or a PDF (A4, landscape when the table is wide; Indian digit grouping; every page
numbered). A new report adds one ``*_doc`` function, never a second writer.
"""

from __future__ import annotations

import datetime
import io
from decimal import Decimal
from typing import Any

from mesiri.domains.costing.export import _sheet

Doc = dict[str, Any]


def _dr(v: Decimal) -> Decimal | None:
    return v if v > 0 else None


def _cr(v: Decimal) -> Decimal | None:
    return -v if v < 0 else None


def _d(v: Any) -> Decimal:
    return Decimal(str(v or 0))


def doc(title: str, subtitle: str, tables: list[dict[str, Any]]) -> Doc:
    return {"title": title, "subtitle": subtitle, "tables": tables}


def table(name: str, headers: list[str], rows: list[list[Any]], widths: list[int], total_rows: int = 0) -> dict[str, Any]:
    """``total_rows``: how many rows at the end are totals (bold in the PDF)."""
    return {"name": name, "headers": headers, "rows": rows, "widths": widths, "total_rows": total_rows}


# --- writers -------------------------------------------------------------------------------------------------------

def to_xlsx(d: Doc) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    book = Workbook()
    for i, t in enumerate(d["tables"]):
        sheet = _sheet(book, t["name"][:31], t["headers"], t["rows"], t["widths"])
        if i == 0:
            sheet.insert_rows(1, 2)
            sheet["A1"] = f"{d['title']}, {d['subtitle']}"
            sheet["A1"].font = Font(bold=True)
    del book["Sheet"]
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def inr(v: Any) -> str:
    """1,23,456.78 (Indian grouping); negative in brackets."""
    n = _d(v).quantize(Decimal("0.01"))
    neg = n < 0
    whole, frac = f"{abs(n):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts) + "," + tail
    s = f"{whole}.{frac}"
    return f"({s})" if neg else s


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, Decimal | float) or (isinstance(v, int) and not isinstance(v, bool)):
        return inr(v)
    if isinstance(v, datetime.date):
        return v.strftime("%d %b %Y")
    return str(v)


def to_pdf(d: Doc) -> bytes:
    from fpdf import FPDF

    from mesiri.domains.dpr.pdf import _latin1

    def txt(s: str) -> str:
        return _latin1(str(s).replace("₹", "Rs ").replace("›", ">").replace("→", "->").replace("−", "-"))

    wide = max(sum(t["widths"]) for t in d["tables"]) > 120
    pdf = FPDF(orientation="L" if wide else "P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(12, 12, 12)
    pdf.alias_nb_pages()
    page_w = (297 if wide else 210) - 24

    def footer() -> None:
        pdf.set_y(-10)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 4, txt(f"{d['title']} · page {pdf.page_no()} of {{nb}} · from Mesiri"), align="R")
        pdf.set_text_color(0, 0, 0)

    pdf.footer = footer  # type: ignore[method-assign]
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 7, txt(d["title"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.multi_cell(0, 5, txt(d["subtitle"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    for t in d["tables"]:
        pdf.ln(3)
        if len(d["tables"]) > 1:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 6, txt(t["name"]), new_x="LMARGIN", new_y="NEXT")
        scale = page_w / sum(t["widths"])
        widths = [w * scale for w in t["widths"]]
        numeric = [any(isinstance(r[i], Decimal | int | float) and not isinstance(r[i], bool)
                       for r in t["rows"] if i < len(r)) for i in range(len(t["headers"]))]

        def head(t: dict = t, widths: list = widths, numeric: list = numeric) -> None:
            pdf.set_font("Helvetica", "B", 7.5)
            pdf.set_fill_color(235, 235, 235)
            for h, w, num in zip(t["headers"], widths, numeric, strict=False):
                pdf.cell(w, 6, txt(h)[:40], border="B", fill=True, align="R" if num else "L")
            pdf.ln()
        head()
        if not t["rows"]:
            pdf.set_font("Helvetica", "I", 8)
            pdf.cell(sum(widths), 6, "Nothing in this period.", new_x="LMARGIN", new_y="NEXT")
        body = len(t["rows"]) - t["total_rows"]
        for n, row in enumerate(t["rows"]):
            if pdf.will_page_break(5.5):
                pdf.add_page()
                head()
            pdf.set_font("Helvetica", "B" if n >= body else "", 7.5)
            for i, w in enumerate(widths):
                v = row[i] if i < len(row) else None
                s = txt(_cell(v))
                if pdf.get_string_width(s) > w - 1:
                    while s and pdf.get_string_width(s + "..") > w - 1:
                        s = s[:-1]
                    s = f"{s}.." if s else ""
                pdf.cell(w, 5.5, s, border="T" if n == body else 0, align="R" if numeric[i] else "L")
            pdf.ln()
    return bytes(pdf.output())


def render(d: Doc, fmt: str) -> tuple[bytes, str, str]:
    """(content, media type, extension)."""
    if fmt == "pdf":
        return to_pdf(d), "application/pdf", "pdf"
    return to_xlsx(d), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"


def _period(date_from, date_to) -> str:
    return f"{_cell(date_from)} to {_cell(date_to)}"


# --- reports -------------------------------------------------------------------------------------------------------

def trial_balance(company: str, scope: str, date_from, date_to, tb: dict[str, Any]) -> Doc:
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
    return doc(f"{company}: trial balance", f"{scope}, {_period(date_from, date_to)}", [
        table("Trial balance", ["Group", "Ledger", "Opening Dr", "Opening Cr", "Debit", "Credit", "Closing Dr",
                                "Closing Cr"], rows, [34, 36, 14, 14, 14, 14, 14, 14], 1)])


def ledger_statement(company: str, scope: str, date_from, date_to, st: dict[str, Any]) -> Doc:
    rows = [[date_from, "", "Opening balance", "", _dr(st["opening"]), _cr(st["opening"]), st["opening"]]]
    rows += [[r["date"], r["ref"], r["narration"], r["against"], r["debit"] or None, r["credit"] or None,
              r["balance"]] for r in st["lines"]]
    rows.append([date_to, "", "Closing balance", "", st["debit"], st["credit"], st["closing"]])
    return doc(f"{company}: {st['ledger']['name']}", f"{st['ledger']['group_name']}, {scope}, {_period(date_from, date_to)}. "
               "Balance: positive is Dr (owed to us), in brackets Cr (we owe).", [
        table("Ledger", ["Date", "Voucher", "Narration", "Against", "Debit", "Credit", "Balance (Dr +)"],
              rows, [12, 20, 50, 30, 14, 14, 16], 1)])


def day_book(company: str, scope: str, date_from, date_to, book_: dict[str, Any]) -> Doc:
    rows = []
    for e in book_["entries"]:
        for i, ln in enumerate(e["lines"]):
            rows.append([e["date"] if i == 0 else "", e["ref"] if i == 0 else "", e["narration"] if i == 0 else "",
                         ln["ledger"], ln["debit"] or None, ln["credit"] or None, ln["project"], ln["site"],
                         ln["cost_centre"]])
    return doc(f"{company}: day book", f"{scope}, {_period(date_from, date_to)}", [
        table("Day book", ["Date", "Voucher", "Narration", "Ledger", "Debit", "Credit", "Project", "Site", "Cost centre"],
              rows, [12, 20, 50, 34, 14, 14, 24, 20, 16])])


def gst(company: str, date_from, date_to, g: dict[str, Any]) -> Doc:
    """GST for the CA: Summary (GSTR-3B terms), Sales (outward), Purchases (inward, claimable or why not), by GSTIN."""
    o, i = g["output"], g["input"]
    summary = [
        ["3.1(a) Outward taxable supplies", o["taxable"], o["igst"], o["cgst"], o["sgst"], o["unknown"], o["gst"]],
        ["4(A)(5) Input tax credit (claimable)", i["taxable"], i["igst"], i["cgst"], i["sgst"], i["unknown"], i["gst"]],
        ["Net GST payable", None, None, None, None, None, g["payable"]],
        ["GST paid, not claimable (missed credit)", None, None, None, None, None, g["missed"]],
    ]
    words = {"no_gstin": "Supplier has no GSTIN", "not_included": "GST said as not included",
             "tax_not_below_amount": "GST not below the amount"}
    return doc(f"{company}: GST", f"GSTIN {g['company_gstin'] or 'not set'}, {_period(date_from, date_to)}", [
        table("Summary", ["", "Taxable value", "IGST", "CGST", "SGST", "GST (state unknown)", "Total GST"],
              summary, [40, 16, 14, 14, 14, 18, 14]),
        table("Sales", ["Date", "Bill", "Client", "GSTIN", "Project", "Rate %", "Taxable", "IGST", "CGST", "SGST", "GST"],
              [[r["date"], r["ref"], r["client"], r["gstin"], r["project"], r["rate"], r["taxable"], r["igst"],
                r["cgst"], r["sgst"], r["gst"]] for r in g["sales"]], [12, 10, 28, 18, 22, 8, 14, 12, 12, 12, 12]),
        table("Purchases", ["Date", "Expense", "Supplier", "GSTIN", "Project", "Taxable", "IGST", "CGST", "SGST",
                            "GST", "Claimable", "Why not"],
              [[r["date"], r["number"], r["supplier"], r["gstin"], r["project"], r["taxable"], r["igst"], r["cgst"],
                r["sgst"], r["gst"], "Yes" if r["claimable"] else "No", words.get(r["reason"] or "", "")]
               for r in g["purchases"]], [12, 12, 28, 18, 22, 14, 12, 12, 12, 12, 10, 26]),
        table("By supplier GSTIN", ["Supplier", "GSTIN", "Bills", "Taxable", "GST", "Claimable"],
              [[s["supplier"], s["gstin"], s["bills"], s["taxable"], s["gst"], s["claimable"]] for s in g["by_supplier"]],
              [32, 18, 8, 14, 14, 14]),
    ])


def tds(company: str, date_from, date_to, t: dict[str, Any]) -> Doc:
    return doc(f"{company}: TDS", _period(date_from, date_to), [
        table("Months", ["Month", "Deducted", "Deposited", "To deposit", "Due by", "Status"],
              [[m["month"], m["deducted"], m["deposited"], m["left"], m["due"], m["status"]] for m in t["months"]],
              [10, 14, 14, 14, 12, 12]),
        table("Deducted 194C", ["Date", "Subcontractor", "PAN", "Section", "Bill", "Bill amount", "TDS", "Project"],
              [[d["date"], d["party"], d["pan"], d["section"], d["bill"], d["bill_amount"], d["amount"], d["project"]]
               for d in t["deducted"]], [12, 30, 14, 9, 12, 14, 12, 24]),
        table("Deposited", ["Date", "Amount", "From"], [[d["date"], d["amount"], d["from"]] for d in t["deposits"]],
              [12, 14, 28]),
        table("Deducted by clients", ["Date", "RA bill", "Client", "PAN", "Project", "Gross", "Rate %", "TDS"],
              [[r["date"], r["ref"], r["client"], r["pan"], r["project"], r["gross"], r["rate"], r["amount"]]
               for r in t["by_clients"]], [12, 10, 28, 14, 24, 14, 8, 12]),
    ])


_PL_SECTIONS = (("income", "Income (sales and direct income)"), ("direct", "Direct costs (purchases and direct expenses)"),
                ("other_income", "Other income"), ("indirect", "Indirect expenses"))


def pl(company: str, scope: str, date_from, date_to, p: dict[str, Any]) -> Doc:
    """ACC-21: the P&L as the page shows it, each group with its ledgers, then gross and net profit."""
    prior = p.get("prior_totals") is not None
    rows: list[list[Any]] = []
    for key, label in _PL_SECTIONS:
        rows.append([label, "", None, None])
        for g in p["sections"][key]:
            rows.append(["", g["name"], g["amount"], g["prior"] if prior else None])
            for led in g["ledgers"]:
                rows.append(["", f"   {led['name']}", led["amount"], led["prior"] if prior else None])
        if key == "direct":
            t = p["totals"]
            rows.append(["Gross profit", "", t["gross_profit"], p["prior_totals"]["gross_profit"] if prior else None])
    t = p["totals"]
    rows.append(["Net profit", "", t["net_profit"], p["prior_totals"]["net_profit"] if prior else None])
    if p.get("overheads"):
        rows.append(["Net profit before head-office share", "", p["net_before_overheads"], None])
    compare = p.get("compare")
    head = ["Section", "Group / ledger", "This period", (f"{_cell(compare['date_from'])} to {_cell(compare['date_to'])}"
                                                        if compare else "Compared")]
    return doc(f"{company}: profit and loss", f"{scope}, {_period(date_from, date_to)}", [
        table("Profit and loss", head if prior else head[:3], [r if prior else r[:3] for r in rows],
              [34, 46, 18, 18] if prior else [34, 46, 18], 2 if p.get("overheads") else 1)])


def balance_sheet(company: str, b: dict[str, Any]) -> Doc:
    def side(groups: list[dict]) -> list[list[Any]]:
        rows = []
        for g in groups:
            rows.append([g["name"], "", g["amount"]])
            for s in g["subgroups"]:
                rows.append(["", s["name"], s["amount"]])
                for led in s["ledgers"]:
                    rows.append(["", f"   {led['name']}", led["amount"]])
        return rows
    liabilities = side(b["liabilities"]) + [["Total", "", b["total_liabilities"]]]
    assets = side(b["assets"]) + [["Total", "", b["total_assets"]]]
    return doc(f"{company}: balance sheet", f"As on {_cell(b['as_of'])}" + ("" if b["balanced"] else " (does not balance)"), [
        table("Capital and liabilities", ["Group", "Ledger", "Amount"], liabilities, [40, 50, 18], 1),
        table("Assets", ["Group", "Ledger", "Amount"], assets, [40, 50, 18], 1)])


def cash_bank(company: str, scope: str, date_from, date_to, c: dict[str, Any]) -> Doc:
    t = c["total"]
    return doc(f"{company}: cash and bank", f"{scope}, {_period(date_from, date_to)}", [
        table("Accounts", ["Account", "Group", "Opening", "In", "Out", "Closing"],
              [[a["name"], a["group"], a["opening"], a["in"], a["out"], a["closing"]] for a in c["accounts"]]
              + [["Total", "", t["opening"], t["in"], t["out"], t["closing"]]], [36, 22, 16, 16, 16, 16], 1),
        table("Days", ["Date", "In", "Out"], [[d["date"], d["in"], d["out"]] for d in c["days"]], [14, 16, 16])])


def projects(company: str, date_from, date_to, rows: list[dict[str, Any]], total: dict[str, Any]) -> Doc:
    body = [[r["name"], r["billed"], r["cost"], r["overheads"], r["profit"], r["margin"], r["receivable"], r["payable"]]
            for r in rows]
    body.append(["Total", total["billed"], total["cost"], total["overheads"], total["profit"], total["margin"],
                 total["receivable"], total["payable"]])
    return doc(f"{company}: project P&L", _period(date_from, date_to), [
        table("Projects", ["Project", "Billed", "Cost", "Head office share", "Profit", "Margin %", "Clients owe",
                           "We owe suppliers"], body, [34, 16, 16, 16, 16, 10, 16, 16], 1)])


def cash_flow(company: str, scope: str, date_from, date_to, c: dict[str, Any]) -> Doc:
    words = {"operating": "Operating", "investing": "Investing", "financing": "Financing", "other": "Other"}
    rows: list[list[Any]] = [["Opening cash and bank", "", None, None, c["opening"]]]
    for key, label in words.items():
        s = c["sections"][key]
        if not s["items"]:
            continue
        for i in s["items"]:
            rows.append([label, i["label"], i["in"], i["out"], i["net"]])
        rows.append([f"Net from {label.lower()}", "", s["in"], s["out"], s["net"]])
    rows.append(["Closing cash and bank", "", None, None, c["closing"]])
    return doc(f"{company}: cash flow", f"{scope}, {_period(date_from, date_to)} (direct method)", [
        table("Cash flow", ["Section", "For", "In", "Out", "Net"], rows, [26, 52, 16, 16, 16], 1),
        table("Months", ["Month", "In", "Out", "Net"], [[m["month"], m["in"], m["out"], m["net"]] for m in c["months"]],
              [12, 16, 16, 16])])


def assets_register(company: str, r: dict[str, Any]) -> Doc:
    rows = [[a["name"], a["class_label"], a["acquired_on"], a["cost"], f"{a['method'].upper()} "
             + (f"{_d(a['rate']).normalize()}%" if a["method"] == "wdv" else f"{_d(a['useful_life_years']).normalize()} yrs"),
             a["this_year"], a["value"], "Sold " + _cell(a["disposed_on"]) if a["disposed_on"] else "In use"]
            for a in r["assets"]]
    t = r["totals"]
    rows.append(["Total in use", "", None, t["cost"], "", t["this_year"], t["value"], ""])
    years = [[a["name"], y["financial_year"], y["opening"], y["depreciation"], y["closing"],
              "Posted" if y["posted"] else "At the year's end"] for a in r["assets"] for y in a["years"]]
    return doc(f"{company}: fixed assets", f"As on {_cell(r['today'])}, year {r['financial_year']}", [
        table("Register", ["Asset", "Class", "Bought", "Cost", "Method", "This year", "Value now", "Status"], rows,
              [36, 22, 14, 16, 14, 16, 16, 18], 1),
        table("Depreciation by year", ["Asset", "Year", "Opening", "Depreciation", "Closing", ""], years,
              [36, 12, 16, 16, 16, 18])])


def bank_reco(company: str, o: dict[str, Any]) -> Doc:
    words = {"open": "Not reconciled", "matched": "Matched", "booked": "Booked", "ignored": "Ignored"}
    rows = [[ln["date"], ln["description"], ln["reference"], ln["amount"] if ln["amount"] > 0 else None,
             -ln["amount"] if ln["amount"] < 0 else None, words[ln["status"]],
             (ln["movement"] or {}).get("description") or ln.get("booked_ledger")] for ln in o["lines"]]
    rec = o["reconciliation"]
    tables = [table("Statement lines", ["Date", "Narration", "Ref", "In", "Out", "State", "In Mesiri"], rows,
                    [12, 50, 18, 14, 14, 16, 40])]
    if rec:
        tables.insert(0, table("Reconciliation", ["", "Amount"], [
            ["Balance in the books", rec["books"]],
            ["Add: paid in Mesiri, not yet in the bank", rec["paid_not_in_bank"]],
            ["Less: received in Mesiri, not yet in the bank", rec["received_not_in_bank"]],
            ["Add: in the bank only (not reconciled)", rec["bank_only_in"]],
            ["Less: out of the bank only (not reconciled)", rec["bank_only_out"]],
            ["Balance as per the statement, worked out", rec["explained_bank"]],
            ["Balance the statement shows", rec["statement"]],
            ["Difference", rec["difference"]]], [60, 18], 1))
    return doc(f"{company}: bank reconciliation, {o['account']['name']}",
               f"As on {_cell(rec['as_of']) if rec else 'no statement yet'}", tables)


def year_end(company: str, fy: str, rows: list[dict[str, Any]], profit: Any, earlier: Any = 0) -> Doc:
    """What a year carries forward: each balance-sheet ledger, earlier years' and this year's profit or loss (capital).
    A profit is a credit; Dr = Cr in total."""
    body = [[r["group"], r["name"], _dr(r["balance"]), _cr(r["balance"])] for r in rows]
    for words, v in (("Profit or loss of earlier years", _d(earlier)), ("Profit or loss of the year", _d(profit))):
        if v:
            body.append(["Capital", words, -v if v < 0 else None, v if v > 0 else None])
    body.append(["Total", "", sum((r[2] or 0 for r in body), Decimal(0)), sum((r[3] or 0 for r in body), Decimal(0))])
    return doc(f"{company}: balances carried forward from {fy}", "Each balance-sheet ledger on 31 March", [
        table("Carried forward", ["Group", "Ledger", "Dr", "Cr"], body, [34, 44, 16, 16], 1)])
