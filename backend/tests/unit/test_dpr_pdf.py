"""domains/dpr/pdf.py -- pure fpdf2 rendering, no I/O.

Fixes the gap where a rendered DPR PDF already existed in R2
(daily_report_versions.rendered_object_key) but nothing in the backend or
dashboard could ever reach it, and there was no fallback for a report whose
version hasn't been picked up by the nightly Playwright cron yet
(runtime/render_pending_dpr_pdfs.py). This module is that fallback: a plain
tabular PDF built directly from the same payload shape
(application/dpr/assembly.py::build_site_report_payload), using fpdf2
instead of adding Playwright to the backend process (ADR-D8).
"""

from __future__ import annotations

from mesiri.domains.dpr.pdf import render_dpr_pdf_bytes

_FULL_PAYLOAD = {
    "project_name": "Skyline Towers",
    "site_name": "Site A",
    "report_date": "2026-07-20",
    "activities": [
        {
            "work_type": "Plastering",
            "narrative": "Second floor east wing plastering completed.",
            "status": "COMPLETED",
            "contractor": "ABC Contractors",
            "quantities": [{"quantity": "120", "unit": "sqm"}],
            "evidence_count": 3,
        }
    ],
    "activity_count": 1,
    "issues": [
        {
            "issue_type": "MATERIAL_SHORTAGE",
            "severity": "HIGH",
            "narrative": "Cement delivery delayed by 2 days.",
            "status": "OPEN",
            "delay_duration_minutes": 240,
        }
    ],
    "open_issue_count": 1,
    "evidence_count": 3,
}

_EMPTY_PAYLOAD = {
    "project_name": None,
    "site_name": None,
    "report_date": "2026-07-20",
    "activities": [],
    "activity_count": 0,
    "issues": [],
    "open_issue_count": 0,
    "evidence_count": 0,
}


def test_renders_valid_pdf_bytes_for_a_populated_payload():
    pdf_bytes = render_dpr_pdf_bytes(
        code="DPR-001",
        report_date="2026-07-20",
        project_name="Skyline Towers",
        site_name="Site A",
        workflow_status="approved",
        payload=_FULL_PAYLOAD,
    )
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500


def test_renders_without_error_for_an_empty_payload():
    """A report with no activities/issues yet (freshly created) must still
    produce a valid PDF -- not raise on empty lists or None project/site."""
    pdf_bytes = render_dpr_pdf_bytes(
        code=None,
        report_date="2026-07-20",
        project_name=None,
        site_name=None,
        workflow_status="draft",
        payload=_EMPTY_PAYLOAD,
    )
    assert pdf_bytes.startswith(b"%PDF")


def test_renders_labour_and_material_sections_when_present():
    payload = dict(
        _EMPTY_PAYLOAD,
        labour={
            "headcount": 13,
            "named_count": 1,
            "trades": [{"trade": "Mason", "headcount": 1}, {"trade": "Helper", "headcount": 12}],
            "total_cost": "8000",
        },
        materials=[{"material_name": "Cement", "unit": "bags", "received": "50", "used": "20"}],
    )
    pdf_bytes = render_dpr_pdf_bytes(
        code="DPR-003",
        report_date="2026-07-20",
        project_name="Skyline Towers",
        site_name="Site A",
        workflow_status="draft",
        payload=payload,
    )
    assert pdf_bytes.startswith(b"%PDF")


def test_renders_without_error_when_labour_and_materials_keys_are_absent():
    """Pre-existing payloads (created before this feature) never had these
    keys at all -- must still render, not KeyError."""
    pdf_bytes = render_dpr_pdf_bytes(
        code="DPR-004",
        report_date="2026-07-20",
        project_name="Skyline Towers",
        site_name="Site A",
        workflow_status="draft",
        payload=_EMPTY_PAYLOAD,
    )
    assert pdf_bytes.startswith(b"%PDF")


def test_handles_missing_optional_fields_in_activity_and_issue_rows():
    """quantities/contractor/narrative etc. are all optional per
    build_site_report_payload -- a row with only the required keys must not
    crash the renderer."""
    payload = {
        "project_name": "P",
        "site_name": "S",
        "report_date": "2026-07-20",
        "activities": [{"work_type": None, "quantities": []}],
        "activity_count": 1,
        "issues": [{"issue_type": None}],
        "open_issue_count": 0,
        "evidence_count": 0,
    }
    pdf_bytes = render_dpr_pdf_bytes(
        code="DPR-002",
        report_date="2026-07-20",
        project_name="P",
        site_name="S",
        workflow_status="in_review",
        payload=payload,
    )
    assert pdf_bytes.startswith(b"%PDF")


_PROJECT_PAYLOAD = {
    "level": "PROJECT",
    "project_name": "Skyline Towers",
    "report_date": "2026-07-20",
    "sites": [
        {"site_name": "Block A", "reported": True, "activity_count": 3,
         "open_issue_count": 1, "headcount": 10, "labour_cost": "5000"},
        {"site_name": "Block B", "reported": False, "activity_count": 0,
         "open_issue_count": 0, "headcount": 0, "labour_cost": "0"},
    ],
    "reported_site_count": 1,
    "total_site_count": 2,
    "activity_count": 3,
    "open_issue_count": 1,
    "evidence_count": 2,
    "issues": [
        {"site_name": "Block A", "issue_type": "MATERIAL_SHORTAGE", "severity": "HIGH",
         "narrative": "Out of cement", "status": "OPEN"}
    ],
    "labour": {"headcount": 10, "total_cost": "5000", "trades": []},
    "materials": [{"material_name": "Cement", "unit": "bags", "received": "50", "used": "20"}],
}


def test_renders_a_project_level_pdf_with_sites_table():
    pdf_bytes = render_dpr_pdf_bytes(
        code="DPR-P-1",
        report_date="2026-07-20",
        project_name="Skyline Towers",
        site_name=None,
        workflow_status="draft",
        payload=_PROJECT_PAYLOAD,
    )
    assert pdf_bytes.startswith(b"%PDF")


def test_renders_a_project_level_pdf_with_no_sites_yet():
    payload = dict(_PROJECT_PAYLOAD, sites=[], reported_site_count=0, total_site_count=0, issues=[])
    pdf_bytes = render_dpr_pdf_bytes(
        code="DPR-P-2",
        report_date="2026-07-20",
        project_name="Skyline Towers",
        site_name=None,
        workflow_status="draft",
        payload=payload,
    )
    assert pdf_bytes.startswith(b"%PDF")


def test_renders_a_stock_flag_for_usage_beyond_known_stock():
    payload = {
        **_FULL_PAYLOAD,
        "materials": [
            {"material_name": "Cement", "unit": "bags", "received": "0", "used": "50",
             "closing": "-50", "beyond_stock": True},
        ],
    }
    pdf_bytes = render_dpr_pdf_bytes(
        code="DPR-001",
        report_date="2026-10-15",
        project_name="Skyline Towers",
        site_name="Site A",
        workflow_status="approved",
        payload=payload,
    )
    assert pdf_bytes.startswith(b"%PDF")


def test_renders_a_possible_duplicate_line():
    activity = {**_FULL_PAYLOAD["activities"][0], "possible_duplicate": True}
    payload = {**_FULL_PAYLOAD, "activities": [_FULL_PAYLOAD["activities"][0], activity]}
    pdf_bytes = render_dpr_pdf_bytes(
        code="DPR-001",
        report_date="2026-10-15",
        project_name="Skyline Towers",
        site_name="Site A",
        workflow_status="in_review",
        payload=payload,
    )
    assert pdf_bytes.startswith(b"%PDF")


def _pdf_text(pdf_bytes: bytes) -> str:
    """The page content streams, decompressed (fpdf2 deflates them)."""
    import re
    import zlib

    streams = re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf_bytes, re.S)
    out = []
    for raw in streams:
        try:
            out.append(zlib.decompress(raw).decode("latin-1"))
        except zlib.error:
            continue
    return "".join(out)


def test_prints_the_ai_summary_under_the_header():
    # BE-18. Curly quotes and dashes from the AI must not break the core font.
    pdf_bytes = render_dpr_pdf_bytes(
        code="DPR-001",
        report_date="2026-10-19",
        project_name="Skyline Towers",
        site_name="Site A",
        workflow_status="approved",
        payload=_FULL_PAYLOAD,
        summary="Plastering was completed — the “east wing”. 18 workers were on site.",
    )
    text = _pdf_text(pdf_bytes)
    assert "Summary" in text
    assert "18 workers were on site." in text
    assert text.index("Summary") < text.index("Activities Logged")


def test_no_summary_heading_without_a_summary():
    pdf_bytes = render_dpr_pdf_bytes(
        code="DPR-001",
        report_date="2026-10-19",
        project_name="Skyline Towers",
        site_name="Site A",
        workflow_status="approved",
        payload=_FULL_PAYLOAD,
    )
    assert "(Summary)" not in _pdf_text(pdf_bytes)


def _render(payload):
    return render_dpr_pdf_bytes(
        code="DPR-001", report_date="2026-07-20", project_name="P", site_name="S",
        workflow_status="approved", payload=payload,
    )


def test_dpr06_labour_heading_has_no_total_cost_of_zero(monkeypatch):
    """DPR-06: V1 records no wages, so a cost of 0 is not printed."""
    from fpdf import FPDF

    cells: list[str] = []
    real_cell = FPDF.cell

    def spy(self, *args, **kwargs):
        cells.append(str(kwargs.get("text", args[2] if len(args) > 2 else "")))
        return real_cell(self, *args, **kwargs)

    monkeypatch.setattr(FPDF, "cell", spy)
    payload = {**_FULL_PAYLOAD, "labour": {"headcount": 13, "trades": [], "total_cost": "0"}}
    _render(payload)
    assert "Labour" in cells
    assert not any("Total cost" in c for c in cells)

    cells.clear()
    payload["labour"]["total_cost"] = "8000"
    _render(payload)
    assert "Labour (Total cost: 8000)" in cells
