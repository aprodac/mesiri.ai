"""On-demand DPR PDF rendering, backend-native (no Playwright).

The nightly cron (apps/whatsapp-assistant/src/runtime/render_pending_dpr_pdfs.py)
already renders a polished Playwright/Jinja PDF from the same `payload` JSON
and stores it at `daily_report_versions.rendered_object_key` -- that stays the
canonical artifact whenever it exists (best fidelity, matches what WhatsApp
sees). This module exists for the gap before that cron run catches up, or for
a report whose PDF generation is wanted synchronously from the dashboard: a
plain-tabular PDF built directly from the same payload shape
(application/dpr/assembly.py::build_site_report_payload), using fpdf2 (pure
Python, no headless browser) rather than reversing ADR-D8's decision to keep
Playwright out of the backend process.

Pure function, no I/O -- unit-testable without a live database, same
reasoning as application/dpr/assembly.py itself. fpdf2 is imported lazily so
the core test suite runs without it installed (mirrors channel/receipt/
render.py's lazy Playwright import).
"""

from __future__ import annotations

from typing import Any

_PAGE_WIDTH_MM = 210 - 2 * 15  # A4 minus 15mm margins each side


def _truncate(text: str | None, max_len: int) -> str:
    if not text:
        return "-"
    return text if len(text) <= max_len else text[: max_len - 1] + '...'


_WEATHER_LABELS = {
    "sunny": "Sunny",
    "cloudy": "Cloudy",
    "rainy": "Rain",
    "windy": "Windy",
    "extreme_heat": "Extreme heat",
}
_SITE_WORKING_LABELS = {"full": "Full day", "half": "Half day", "none": "No work"}


def _conditions_line(conditions: dict) -> str:
    weather = _WEATHER_LABELS.get(conditions.get("weather") or "", "Not set")
    working = _SITE_WORKING_LABELS.get(conditions.get("site_working") or "", "Not set")
    hours = conditions.get("hours_lost")
    lost = f"{hours} h" if hours is not None else "-"
    return f"Weather: {weather}  |  Site working: {working}  |  Hours lost: {lost}"


def render_dpr_pdf_bytes(
    *,
    code: str | None,
    report_date: str,
    project_name: str | None,
    site_name: str | None,
    workflow_status: str,
    payload: dict[str, Any],
) -> bytes:
    """Render one DPR version's payload to PDF bytes.

    `payload` is the dict shape `build_site_report_payload` produces:
    project_name/site_name/report_date, activities[] (work_type, narrative,
    status, contractor, quantities[], evidence_count), activity_count,
    issues[] (issue_type, severity, narrative, status,
    delay_duration_minutes), open_issue_count, evidence_count.
    """
    from fpdf import FPDF

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    # Header
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 8, "Daily Progress Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 6, f"{code or 'DPR'}  |  {report_date}  |  {workflow_status.upper()}", new_x="LMARGIN", new_y="NEXT")
    location = " / ".join(part for part in [project_name, site_name] if part)
    if location:
        pdf.cell(0, 6, location, new_x="LMARGIN", new_y="NEXT")
    is_project = payload.get("level") == "PROJECT"

    # Site conditions (BE-14) -- one line under the header, site level only.
    conditions = payload.get("conditions") or {}
    if not is_project and conditions:
        pdf.cell(0, 6, _conditions_line(conditions), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    # Meta tiles
    activities = payload.get("activities") or []
    issues = payload.get("issues") or []
    labour = payload.get("labour") or {}
    materials = payload.get("materials") or []
    sites = payload.get("sites") or []
    tiles = (
        [
            ("Sites Reporting", f"{payload.get('reported_site_count', 0)}/{payload.get('total_site_count', len(sites))}"),
            ("Open Issues", str(payload.get("open_issue_count", 0))),
            ("Workers Today", str(labour.get("headcount", 0))),
        ]
        if is_project
        else [
            ("Activities Logged", str(payload.get("activity_count", len(activities)))),
            ("Open Issues", str(payload.get("open_issue_count", 0))),
            ("Evidence Photos", str(payload.get("evidence_count", 0))),
            ("Workers Today", str(labour.get("headcount", 0))),
        ]
    )
    tile_w = _PAGE_WIDTH_MM / len(tiles)
    pdf.set_font("Helvetica", "B", 12)
    for label, value in tiles:
        x = pdf.get_x()
        y = pdf.get_y()
        pdf.rect(x, y, tile_w - 4, 16)
        pdf.set_xy(x, y + 3)
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(tile_w - 4, 6, value, align="C")
        pdf.set_xy(x, y + 10)
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(tile_w - 4, 5, label, align="C")
        pdf.set_xy(x + tile_w, y)
    pdf.ln(20)

    if is_project:
        # Sites table -- replaces the per-activity table at project level;
        # each site's own activity/issue/labour figures are already signed
        # off on its own SITE report (ADR-D9/P8), this is the roll-up view.
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Sites", new_x="LMARGIN", new_y="NEXT")
        site_col_widths = [50, 30, 30, 30, 30]
        site_headers = ["Site", "Reported", "Activities", "Open Issues", "Workers"]
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(230, 230, 230)
        for header, width in zip(site_headers, site_col_widths, strict=False):
            pdf.cell(width, 7, header, border=1, fill=True)
        pdf.ln()
        pdf.set_font("Helvetica", "", 8)
        if not sites:
            pdf.cell(sum(site_col_widths), 7, "No active sites under this project.", border=1)
            pdf.ln()
        for site in sites:
            row = [
                _truncate(site.get("site_name"), 30),
                "Yes" if site.get("reported") else "Not reported",
                str(site.get("activity_count") or 0),
                str(site.get("open_issue_count") or 0),
                str(site.get("headcount") or 0),
            ]
            for value, width in zip(row, site_col_widths, strict=False):
                pdf.cell(width, 7, value, border=1)
            pdf.ln()
    else:
        # Activities table
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Activities", new_x="LMARGIN", new_y="NEXT")
        col_widths = [30, 55, 25, 30, 40]
        headers = ["Work Type", "Narrative", "Status", "Contractor", "Quantities"]
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(230, 230, 230)
        for header, width in zip(headers, col_widths, strict=False):
            pdf.cell(width, 7, header, border=1, fill=True)
        pdf.ln()
        pdf.set_font("Helvetica", "", 8)
        if not activities:
            pdf.cell(sum(col_widths), 7, "No activities recorded for this date.", border=1)
            pdf.ln()
        for activity in activities:
            quantities = activity.get("quantities") or []
            qty_text = ", ".join(
                f"{q.get('quantity')} {q.get('unit') or ''}".strip() for q in quantities
            ) or "-"
            row = [
                _truncate(activity.get("work_type"), 18),
                _truncate(activity.get("narrative"), 34),
                _truncate(activity.get("status"), 14),
                _truncate(activity.get("contractor"), 18),
                _truncate(qty_text, 24),
            ]
            for value, width in zip(row, col_widths, strict=False):
                pdf.cell(width, 7, value, border=1)
            pdf.ln()

    pdf.ln(4)

    # Site issues table -- a "Site" column is added at project level (each
    # issue was tagged with its source site by build_project_report_payload)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Site Issues", new_x="LMARGIN", new_y="NEXT")
    if is_project:
        issue_col_widths = [30, 25, 15, 55, 25]
        issue_headers = ["Site", "Type", "Severity", "Narrative", "Status"]
    else:
        issue_col_widths = [32, 20, 65, 25, 38]
        issue_headers = ["Type", "Severity", "Narrative", "Status", "Delay (min)"]
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(230, 230, 230)
    for header, width in zip(issue_headers, issue_col_widths, strict=False):
        pdf.cell(width, 7, header, border=1, fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 8)
    if not issues:
        pdf.cell(sum(issue_col_widths), 7, "No site issues recorded for this date.", border=1)
        pdf.ln()
    for issue in issues:
        if is_project:
            row = [
                _truncate(issue.get("site_name"), 24),
                _truncate(issue.get("issue_type"), 18),
                _truncate(issue.get("severity"), 12),
                _truncate(issue.get("narrative"), 42),
                _truncate(issue.get("status"), 14),
            ]
        else:
            row = [
                _truncate(issue.get("issue_type"), 20),
                _truncate(issue.get("severity"), 12),
                _truncate(issue.get("narrative"), 42),
                _truncate(issue.get("status"), 14),
                str(issue.get("delay_duration_minutes") or "-"),
            ]
        for value, width in zip(row, issue_col_widths, strict=False):
            pdf.cell(width, 7, value, border=1)
        pdf.ln()

    pdf.ln(4)

    # Labour table
    pdf.set_font("Helvetica", "B", 12)
    labour_subtitle = f" (Total cost: {labour.get('total_cost', '0')})" if labour.get("headcount") else ""
    pdf.cell(0, 8, f"Labour{labour_subtitle}", new_x="LMARGIN", new_y="NEXT")
    trade_col_widths = [80, 40]
    trade_headers = ["Trade", "Headcount"]
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(230, 230, 230)
    for header, width in zip(trade_headers, trade_col_widths, strict=False):
        pdf.cell(width, 7, header, border=1, fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 8)
    trades = labour.get("trades") or []
    if not trades:
        pdf.cell(sum(trade_col_widths), 7, "No attendance recorded for this date.", border=1)
        pdf.ln()
    for trade in trades:
        pdf.cell(trade_col_widths[0], 7, _truncate(trade.get("trade"), 44), border=1)
        pdf.cell(trade_col_widths[1], 7, str(trade.get("headcount") or 0), border=1)
        pdf.ln()

    pdf.ln(4)

    # Materials table
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Materials", new_x="LMARGIN", new_y="NEXT")
    material_col_widths = [70, 35, 35, 35]
    material_headers = ["Material", "Received", "Used", "Unit"]
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(230, 230, 230)
    for header, width in zip(material_headers, material_col_widths, strict=False):
        pdf.cell(width, 7, header, border=1, fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 8)
    if not materials:
        pdf.cell(sum(material_col_widths), 7, "No material movements recorded for this date.", border=1)
        pdf.ln()
    for material in materials:
        row = [
            _truncate(material.get("material_name"), 46),
            str(material.get("received") or "0"),
            str(material.get("used") or "0"),
            str(material.get("unit") or "-"),
        ]
        for value, width in zip(row, material_col_widths, strict=False):
            pdf.cell(width, 7, value, border=1)
        pdf.ln()
    # BE-12: usage beyond known stock is recorded, not blocked -- say so here.
    for material in materials:
        if material.get("beyond_stock"):
            pdf.set_text_color(170, 30, 30)
            pdf.multi_cell(
                0,
                5,
                _truncate(
                    f"Check: more {material.get('material_name')} used than the site's known stock "
                    f"(stock now {material.get('closing')} {material.get('unit') or ''}). "
                    "A delivery or opening stock may be missing.",
                    300,
                ),
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.set_text_color(0, 0, 0)

    if not is_project and conditions.get("tomorrow_plan"):
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Tomorrow's Plan", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, _truncate(conditions["tomorrow_plan"], 600), new_x="LMARGIN", new_y="NEXT")

    # Footer -- auto_page_break must be off here: moving to within 20mm of
    # the bottom margin with it still on triggers fpdf2 to start a fresh
    # page before drawing the cell (the exact break-margin math it uses for
    # in-flow content), leaving the footer alone on a near-blank page 2.
    pdf.set_auto_page_break(auto=False)
    pdf.set_y(-20)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 10, "Generated on-demand by Mesiri", align="C")

    return bytes(pdf.output())
