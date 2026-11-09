"""The period report as an Excel workbook (PRC-19, D-R4): Summary, then one sheet per section.

Plain columns, one header row, no merged cells, so a pivot table works. Money and quantities are written as
numbers; a figure that is not known stays empty, never 0 (the cost export's rule, ``costing/export.py``). It renders
what ``engine.build`` returned and computes nothing of its own.
"""

from __future__ import annotations

import io
from decimal import Decimal
from typing import Any

from mesiri.domains.costing.export import _sheet


def _n(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value not in (None, "") else None


def workbook(report: dict[str, Any]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    s = report["sections"]
    money = bool(report.get("sees_money"))
    book = Workbook()
    cover = book.active
    cover.title = "Summary"
    p = report["period"]
    where = report["project"]["name"] + (f" · {report['site']['name']}" if report.get("site") else "")
    cover.append([f"{where}: {p['label']} ({p['range']})"])
    cover["A1"].font = Font(bold=True, size=13)
    cover.append([" ".join([report["headline"]["lead"], *report["headline"]["facts"]])])
    cover.append([])
    cover.append(["Figure", "Value", "Compared with"])
    for cell in cover[4]:
        cell.font = Font(bold=True)
    for k in report["kpis"]:
        cover.append([k["label"], k["value"], k.get("note") or ""])
    cover.append([])
    cover.append(["Area", "Status", "In short"])
    for cell in cover[cover.max_row]:
        cell.font = Font(bold=True)
    for a in report["areas"]:
        cover.append([a["title"], a["word"], a["note"]])
    cover.append([])
    cover.append([f"Made from Mesiri on {report['generated_at'][:16].replace('T', ' ')} UTC"])
    cover.column_dimensions["A"].width = 26
    cover.column_dimensions["B"].width = 18
    cover.column_dimensions["C"].width = 90

    if "work" in s:
        _sheet(book, "Work", ["Activity", "Site", "Work done this period", "Quantity", "Unit", "To date %", "Plan %",
                              "Status", "Days late", "Critical path"],
               [[r["activity"], r.get("site"), d["work"], _n(d["quantity"]), d["unit"], r.get("progress"),
                 r.get("expected"), r.get("state"), r["days_late"] or r["slip_days"], "yes" if r["critical"] else ""]
                for r in s["work"]["rows"] for d in (r["done_in_period"] or [{"work": None, "quantity": None,
                                                                              "unit": None}])],
               [34, 18, 34, 12, 8, 10, 10, 12, 10, 12])
    if "schedule" in s:
        _sheet(book, "Schedule", ["Activity", "Site", "State", "Days late", "Slip days", "Planned end", "Now ends",
                                  "Critical path", "Who", "Open issues"],
               [[r["activity"], r.get("site"), r["state"], r["days_late"], r["slip_days"], r.get("end"),
                 r.get("forecast_end"), "yes" if r["critical"] else "", r.get("assigned_to"), r["open_issues"]]
                for r in s["schedule"]["rows"]], [34, 18, 12, 10, 10, 12, 12, 12, 20, 10])
    if "labour" in s:
        lb = s["labour"]
        head = ["Day", "Man-days"] + (["Wages"] if money else [])
        rows = [[d["date"], _n(d["man_days"])] + ([_n(d.get("wages"))] if money else []) for d in lb["by_day"]]
        sheet = _sheet(book, "Labour", head, rows, [14, 12, 14])
        sheet.append([])
        sheet.append(["Trade", "Man-days"] + (["Wages"] if money else []))
        for cell in sheet[sheet.max_row]:
            cell.font = Font(bold=True)
        for r in lb["by_trade"]:
            sheet.append([r["label"], _n(r["man_days"])] + ([_n(r.get("wages"))] if money else []))
    if "materials" in s:
        _sheet(book, "Materials", ["Material", "Category", "Site", "Unit", "Opening", "Received", "Used", "Closing",
                                   "Days left", "Running low"] + (["Spend"] if money else []),
               [[r["material"], r.get("category"), r.get("site"), r["unit"], _n(r["opening"]), _n(r["received"]),
                 _n(r["used"]), _n(r["closing"]), r.get("days_left"), "yes" if r["running_low"] else ""]
                + ([_n(r.get("spend"))] if money else []) for r in s["materials"]["rows"]],
               [28, 16, 18, 8, 10, 10, 10, 10, 10, 12, 12])
    if "money" in s:
        mo = s["money"]
        rows: list[list[Any]] = [["Spent", c["label"], _n(c["amount"])] for c in mo["centres"]]
        rows.append(["Spent", "Total", _n(mo["spent"])])
        rows.append(["Spent", "Last period", _n(mo["prev_spent"])])
        for key, label in (("billed", "Billed in the period"), ("received", "Received in the period"),
                           ("owed", "Owed by the client now"), ("overdue", "Of it, over 30 days")):
            if key in mo:
                rows.append(["Client bills", label, _n(mo[key])])
        for ln in mo["worst_lines"]:
            rows.append(["Labour against work done", f"{ln['work']} ({ln['colour']})", _n(ln["difference"])])
        _sheet(book, "Money", ["Kind", "What", "Amount"], rows, [26, 44, 16])
    if "issues" in s:
        _sheet(book, "Issues", ["Type", "Severity", "What", "Site", "Since", "Days open"],
               [[r["type"], r["severity"], r.get("what"), r.get("site"), r["since"], r["days_open"]]
                for r in s["issues"]["rows"]], [18, 10, 60, 18, 12, 10])
    if "completeness" in s:
        _sheet(book, "Data check", ["Day", "Weekday", "Site reports confirmed", "Sites", "Attendance recorded",
                                    "Weather"],
               [[d["date"], d["weekday"], d["reports"], d["sites"], d["attendance"], d.get("weather")]
                for d in s["completeness"]["days"]], [12, 10, 22, 8, 20, 14])
    if report["needs_you"]:
        _sheet(book, "Needs you", ["Level", "What", "Detail"],
               [[n["level"], n["title"], n.get("detail")] for n in report["needs_you"]], [8, 60, 60])
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def portfolio_workbook(brief: dict[str, Any]) -> bytes:
    """The owner's brief (RPT-01): Summary, then one row per project with every figure as a number."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    book = Workbook()
    cover = book.active
    cover.title = "Summary"
    p = brief["period"]
    cover.append([f"All projects: {p['label']} ({p['range']})"])
    cover["A1"].font = Font(bold=True, size=13)
    cover.append([" ".join([brief["headline"]["lead"], *brief["headline"]["facts"]])])
    cover.append([])
    for k in brief["kpis"]:
        cover.append([k["label"], k["value"], k.get("note") or ""])
    cover.column_dimensions["A"].width = 24
    cover.column_dimensions["B"].width = 16
    cover.column_dimensions["C"].width = 60
    money = bool(brief.get("sees_money"))
    head = ["Project", "Client", "Status", "Done to date %", "Plan to date %", "Done this period %",
            "Planned this period %", "Forecast finish", "Days late", "Man-days", "Open issues", "Serious issues",
            "Needs you", "Top item"]
    if money:
        head += ["Spent", "Billed", "Received", "Clients owe", "Over 30 days", "Labour colour"]
    rows = []
    for r in brief["projects"]:
        row = [r["name"], r.get("client"), r["word"], r.get("progress_to_date"), _n(r.get("expected_to_date")),
               _n(r.get("done_pct")), _n(r.get("plan_pct")), r.get("forecast_finish"), r.get("slip_days"),
               _n(r.get("man_days")), r["open_issues"], r["serious_issues"], r["needs"], r.get("top")]
        if money:
            row += [_n(r.get("spent")), _n(r.get("billed")), _n(r.get("received")), _n(r.get("owed")),
                    _n(r.get("overdue")), r.get("labour_colour")]
        rows.append(row)
    _sheet(book, "Projects", head, rows, [28, 18, 12, 12, 12, 14, 14, 14, 10, 10, 10, 10, 10, 44, 12, 12, 12, 12, 12, 12])
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()
