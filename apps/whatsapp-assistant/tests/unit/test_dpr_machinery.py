"""NXT-11 (WA-68): the DPR's Machinery section -- each machine's day at the site, in the site and project report.

A report without machines looks as it did (no empty section). A site that only logged machines counts as reported."""

from __future__ import annotations

import datetime

from channel.dpr_document.data import build_document_data
from channel.dpr_document.template import render_html
from mesiri.application.dpr import assembly

JCB = {"machine": "JCB", "ref": "EQ-0001", "type": "Backhoe loader", "ownership": "Hired", "site_name": "Tower 1",
       "worked": "6", "idle": "0", "breakdown": "2", "breakdown_reason": "hydraulic leak", "fuel": "30",
       "operator": "Suresh", "trips": None}


def _site(machinery: list[dict]) -> dict:
    return assembly.build_site_report_payload(
        project_name="Skyline", site_name="Tower 1", report_date=datetime.date(2026, 11, 8), activity_rows=[],
        quantities_by_activity={}, evidence_count_by_activity={}, issue_rows=[], machinery_rows=machinery)


def test_the_site_report_shows_each_machine_and_a_site_with_only_machines_is_reported() -> None:
    payload = _site([JCB])
    assert payload["machinery"] == [JCB] and assembly.has_saved_entries(payload)
    html = render_html(build_document_data(code="DPR-1", payload=payload), None)
    assert "Machinery" in html and "hydraulic leak" in html and "30 L" in html and "Operator Suresh" in html


def test_no_machines_no_section_and_the_rest_unchanged() -> None:
    payload = _site([])
    assert not assembly.has_saved_entries(payload)
    html = render_html(build_document_data(code="DPR-1", payload=payload), None)
    assert "Machinery" not in html and "Materials" in html


def test_the_project_report_lists_machines_with_their_site() -> None:
    project = assembly.build_project_report_payload(
        project_name="Skyline", report_date=datetime.date(2026, 11, 8),
        site_payloads=[("Tower 1", _site([JCB])), ("Tower 2", None)])
    assert [m["site_name"] for m in project["machinery"]] == ["Tower 1"]
    html = render_html(build_document_data(code="DPR-P", payload=project), None)
    assert "Machinery" in html and "Tower 1" in html
