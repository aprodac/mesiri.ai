"""Cost control as an Excel workbook (CC-21), for the CA or the MD.

Four sheets from the reads the pages use, never a second calculation: Summary (per kind: budget, earned, spent,
committed, forecast), BOQ lines (planned, done, left, budget, earned, labour spent, labour against earned), Green-red
(the period's lines worst first, and each day), Materials (against the BOQ). Money and quantities are written as
numbers (Excel adds them up), a figure that is not known stays empty, never 0.
"""

from __future__ import annotations

import io
from decimal import Decimal
from typing import Any

_HEAD_FILL = "FFE08A"
_COLOUR_FILL = {"green": "C6EFCE", "amber": "FFE5B4", "red": "FFC7CE"}


def _n(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value not in (None, "") else None


def _sheet(book, title: str, header: list[str], rows: list[list[Any]], widths: list[int], colour_col: int | None = None):
    from openpyxl.styles import Font, PatternFill

    sheet = book.create_sheet(title)
    sheet.append(header)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor=_HEAD_FILL)
    for row in rows:
        sheet.append(row)
        if colour_col is not None and row[colour_col] in _COLOUR_FILL:
            sheet.cell(row=sheet.max_row, column=colour_col + 1).fill = PatternFill(
                "solid", fgColor=_COLOUR_FILL[row[colour_col]])
    for i, width in enumerate(widths):
        sheet.column_dimensions[chr(ord("A") + i)].width = width
    sheet.freeze_panes = "A2"
    return sheet


def workbook(project: str, budget: dict, variance: dict, materials: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    book = Workbook()
    cover = book.active
    cover.title = "Summary"
    cover.append([f"{project}: cost control"])
    cover["A1"].font = Font(bold=True, size=13)
    cover.append([f"Budget vs actual from {budget['date_from']} to {budget['date_to']}. "
                  f"Green / red from {variance['date_from']} to {variance['date_to']}."])
    cover.append([])
    cover.append(["Kind", "Budget", "Earned", "Spent", "Earned - spent", "Committed", "Forecast at completion",
                  "Budget - forecast"])
    for cell in cover[4]:
        cell.font = Font(bold=True)
    for k in budget["kinds"]:
        cover.append([k["label"], _n(k["budget"]), _n(k["earned"]), _n(k["actual"]), _n(k["difference"]),
                      _n(k.get("committed")), _n(k.get("forecast")), _n(k.get("forecast_difference"))])
    cover.append([])
    cover.append(["Total spent (all cost centres)", _n(budget["total_spent"])])
    for o in budget["other_spending"]:
        cover.append([f"  of which {o['label']} (no BOQ rate)", _n(o["amount"])])
    cover.append(["Labour not on a BOQ line", _n(budget["labour_not_on_a_line"]["cost"])])
    cover.append(["Work not on a BOQ line (records)", budget["work_not_on_a_line"]])
    for i, width in enumerate((34, 14, 14, 14, 15, 14, 22, 18)):
        cover.column_dimensions[chr(ord("A") + i)].width = width

    lines = [(s["name"], ln) for s in budget["boq"]["sections"] for ln in s["lines"]]
    _sheet(book, "BOQ lines",
           ["Section", "Code", "Work", "Unit", "Planned", "Done", "Left", "% done", "Budget", "Earned", "Labour man-days",
            "Labour spent", "Labour earned - spent"],
           [[sec, ln.get("boq_code"), ln["work"], ln["unit"], _n(ln["planned_quantity"]), _n(ln["done_quantity"]),
             _n(ln["remaining_quantity"]), _n(ln.get("percent_done")), _n(ln.get("budget_cost")), _n(ln.get("earned")),
             _n(ln.get("labour_man_days")), _n(ln.get("labour_cost")), _n(ln.get("labour_difference"))]
            for sec, ln in lines],
           [22, 8, 40, 7, 11, 11, 11, 8, 14, 14, 10, 14, 16])

    gr = _sheet(book, "Green-red",
                ["Colour", "Why", "Work", "Unit", "Done", "Labour rate", "Earned", "Labour spent", "Earned - spent",
                 "Cost per unit"],
                [[v["colour"], v["reason"].replace("_", " "), v["work"], v["unit"], _n(v["done_quantity"]),
                  _n(v["labour_rate"]), _n(v["earned_labour"]), _n(v["labour_cost"]), _n(v["difference"]),
                  _n(v["cost_per_unit"])] for v in variance["lines"]],
                [10, 18, 40, 7, 11, 11, 13, 13, 14, 12], colour_col=0)
    gr.append([])
    gr.append(["Day", "Colour", "Earned", "Labour spent", "Attendance cost", "Labour on no line"])
    for d in variance["days"]:
        gr.append([d["date"], d["colour"], _n(d["earned_labour"]), _n(d["labour_cost"]), _n(d["attendance_cost"]),
                   _n(d["not_on_a_line_cost"])])

    _sheet(book, "Materials",
           ["Colour", "Material", "Unit", "BOQ needs", "Work done needed", "Received", "Used", "Used beyond the work",
            "On hand", "On order", "Still needed", "Short to finish"],
           [[m["colour"], m["material"], m["unit"], _n(m["required_total"]), _n(m["should_have_used"]), _n(m["received"]),
             _n(m["used"]), _n(m["used_over_work"]), _n(m["on_hand"]), _n(m["on_order"]), _n(m["still_needed"]),
             _n(m["short_by"])] for m in materials["materials"]],
           [10, 26, 7, 11, 15, 11, 11, 17, 11, 11, 12, 14], colour_col=0)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
