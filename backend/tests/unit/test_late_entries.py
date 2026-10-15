"""BE-13: late-entry rules and how the report shows them (no database)."""

from __future__ import annotations

import datetime as dt

import pytest

from mesiri.application.dpr import late_entries
from mesiri.application.dpr.assembly import build_site_report_payload


@pytest.mark.parametrize(
    ("status", "sent", "expected"),
    [
        ("APPROVED", False, late_entries.REOPENED),
        ("APPROVED", True, late_entries.REVISED),
        ("PUBLISHED", False, late_entries.REVISED),
        ("PUBLISHED", True, late_entries.REVISED),
    ],
)
def test_reopen_only_while_the_report_has_not_gone_out(status, sent, expected) -> None:
    assert late_entries.outcome_for(day_status=status, sent=sent) == expected


def _payload(**extra):
    return build_site_report_payload(
        project_name="Green Towers",
        site_name="Block A",
        report_date=dt.date(2026, 10, 16),
        activity_rows=[],
        quantities_by_activity={},
        evidence_count_by_activity={},
        issue_rows=[],
        **extra,
    )


def test_payload_lists_late_entries_and_defaults_to_none() -> None:
    assert _payload()["late_entries"] == []
    entries = [
        {"report_date": "2026-10-15", "summary": "Received 20 bags Cement", "outcome": "revised"}
    ]
    assert _payload(late_entries=entries)["late_entries"] == entries


def test_fallback_pdf_shows_the_late_entries_section() -> None:
    pytest.importorskip("fpdf")
    from mesiri.domains.dpr.pdf import render_dpr_pdf_bytes

    payload = _payload(
        late_entries=[
            {
                "report_date": "2026-10-15",
                "summary": "Received 20 bags Cement",
                "outcome": "revised",
            }
        ]
    )
    pdf = render_dpr_pdf_bytes(
        code="DPR-1",
        report_date="2026-10-16",
        project_name="Green Towers",
        site_name="Block A",
        workflow_status="DRAFT",
        payload=payload,
    )
    assert pdf.startswith(b"%PDF")
