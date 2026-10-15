"""DPR PDF document shaping/rendering -- #16 Daily Report Generation.

Covers data.py's payload -> DprDocumentData mapping (pure) and template.py's
Jinja2 render (pure, no Playwright/no live browser needed -- render.py's
Playwright driving is untestable without a headless browser and is not
covered here, same convention as channel/receipt/render.py).
"""

from __future__ import annotations

import pytest

from channel.dpr_document.data import build_document_data

# render_html needs jinja2, which -- like playwright -- lives behind the
# "receipt" extra and is intentionally absent from the core CI install
# (see pyproject.toml's comment on that group and channel/receipt/template.py,
# which is untested for the same reason). build_document_data is pure and
# needs no such guard.
jinja2 = pytest.importorskip("jinja2")
from channel.dpr_document.template import render_html  # noqa: E402


def _payload(**overrides):
    base = {
        "project_name": "Skyline Towers",
        "site_name": "Block A",
        "report_date": "2026-07-27",
        "activities": [],
        "activity_count": 0,
        "issues": [],
        "open_issue_count": 0,
        "evidence_count": 0,
    }
    base.update(overrides)
    return base


def test_build_document_data_maps_project_and_site_names():
    data = build_document_data(code="DPR-20260727-AB12", payload=_payload())
    assert data.code == "DPR-20260727-AB12"
    assert data.project_name == "Skyline Towers"
    assert data.site_name == "Block A"
    assert data.report_date == "2026-07-27"


def test_build_document_data_formats_quantities_as_readable_text():
    payload = _payload(
        activities=[
            {
                "work_type": "plastering",
                "narrative": "180 sqm done",
                "status": "IN_PROGRESS",
                "contractor": "ABC Contractors",
                "quantities": [{"work_type": "plastering", "quantity": "180", "unit": "sqm"}],
                "evidence_count": 2,
            }
        ],
        activity_count=1,
    )
    data = build_document_data(code="DPR-1", payload=payload)
    activity = data.activities[0]
    assert activity.work_type == "Plastering"
    assert "180" in activity.quantities
    assert "sqm" in activity.quantities
    assert activity.evidence_count == 2


def test_build_document_data_missing_fields_degrade_to_placeholders():
    payload = _payload(
        activities=[
            {"work_type": None, "narrative": None, "status": None, "contractor": None,
             "quantities": [], "evidence_count": 0}
        ],
        activity_count=1,
    )
    data = build_document_data(code="DPR-1", payload=payload)
    activity = data.activities[0]
    assert activity.narrative == "—"
    assert activity.contractor == "—"
    assert activity.quantities == "—"


def test_render_html_includes_project_site_and_code():
    data = build_document_data(code="DPR-20260727-AB12", payload=_payload())
    html = render_html(data)
    assert "Skyline Towers" in html
    assert "Block A" in html
    assert "DPR-20260727-AB12" in html


def test_render_html_shows_empty_state_for_no_activities_or_issues():
    data = build_document_data(code="DPR-1", payload=_payload())
    html = render_html(data)
    assert "No activities logged" in html
    assert "No issues reported" in html


def test_build_document_data_maps_labour_and_materials():
    payload = _payload(
        labour={
            "headcount": 13,
            "named_count": 1,
            "trades": [{"trade": "mason", "headcount": 1}, {"trade": "helper", "headcount": 12}],
            "total_cost": "8000",
        },
        materials=[{"material_name": "cement", "unit": "bags", "received": "50", "used": "20"}],
    )
    data = build_document_data(code="DPR-1", payload=payload)
    assert data.headcount == 13
    assert data.labour_cost == "8000"
    assert {t.trade: t.headcount for t in data.trades} == {"Mason": 1, "Helper": 12}
    assert data.materials[0].material_name == "Cement"
    assert data.materials[0].received == "50"
    assert data.materials[0].used == "20"


def test_build_document_data_defaults_labour_and_materials_when_absent():
    """A payload built before this feature has neither key at all."""
    data = build_document_data(code="DPR-1", payload=_payload())
    assert data.headcount == 0
    assert data.labour_cost == "0"
    assert data.trades == []
    assert data.materials == []


def test_render_html_shows_labour_and_materials_sections():
    payload = _payload(
        labour={
            "headcount": 13,
            "trades": [{"trade": "mason", "headcount": 1}],
            "total_cost": "8000",
        },
        materials=[{"material_name": "cement", "unit": "bags", "received": "50", "used": "20"}],
    )
    data = build_document_data(code="DPR-1", payload=payload)
    html = render_html(data)
    assert "Mason" in html
    assert "Cement" in html
    assert "8000" in html


def test_render_html_shows_empty_state_for_no_labour_or_materials():
    data = build_document_data(code="DPR-1", payload=_payload())
    html = render_html(data)
    assert "No attendance recorded" in html
    assert "No material movements recorded" in html


# --- PROJECT-level (ADR-D9/P8) ----------------------------------------------


def _project_payload(**overrides):
    base = {
        "level": "PROJECT",
        "project_name": "Skyline Towers",
        "report_date": "2026-07-27",
        "sites": [
            {"site_name": "Block A", "reported": True, "activity_count": 3,
             "open_issue_count": 1, "headcount": 10},
            {"site_name": "Block B", "reported": False, "activity_count": 0,
             "open_issue_count": 0, "headcount": 0},
        ],
        "reported_site_count": 1,
        "total_site_count": 2,
        "activity_count": 3,
        "open_issue_count": 1,
        "evidence_count": 0,
        "issues": [
            {"site_name": "block_a", "issue_type": "material_shortage", "severity": "high",
             "narrative": "Out of cement", "status": "open"}
        ],
        "labour": {"headcount": 10, "total_cost": "5000", "trades": []},
        "materials": [],
    }
    base.update(overrides)
    return base


def test_build_document_data_sets_is_project_from_payload_level():
    data = build_document_data(code="DPR-P-1", payload=_project_payload())
    assert data.is_project is True
    assert build_document_data(code="DPR-1", payload=_payload()).is_project is False


def test_build_document_data_maps_site_breakdown():
    data = build_document_data(code="DPR-P-1", payload=_project_payload())
    assert data.reported_site_count == 1
    assert data.total_site_count == 2
    site_a = next(s for s in data.sites if s.site_name == "Block A")
    assert site_a.reported is True
    assert site_a.activity_count == 3
    site_b = next(s for s in data.sites if s.site_name == "Block B")
    assert site_b.reported is False


def test_build_document_data_tags_issues_with_site_name_at_project_level():
    data = build_document_data(code="DPR-P-1", payload=_project_payload())
    assert data.issues[0].site_name == "Block A"


def test_build_document_data_issue_site_name_defaults_to_placeholder_at_site_level():
    payload = _payload(
        issues=[{"issue_type": "WEATHER", "severity": "HIGH", "narrative": "rain", "status": "OPEN"}]
    )
    data = build_document_data(code="DPR-1", payload=payload)
    assert data.issues[0].site_name == "—"


def test_render_html_shows_sites_table_and_site_column_for_project_level():
    data = build_document_data(code="DPR-P-1", payload=_project_payload())
    html = render_html(data)
    assert "Sites Reporting" in html
    assert "1/2" in html
    assert "Block A" in html
    assert "Block B" in html
    assert "Not reported" in html


def test_render_html_shows_activities_not_sites_for_site_level():
    data = build_document_data(code="DPR-1", payload=_payload())
    html = render_html(data)
    assert "Sites Reporting" not in html


def test_render_html_lists_each_activity_and_issue():
    payload = _payload(
        activities=[
            {"work_type": "excavation", "narrative": "trench dug", "status": "COMPLETED",
             "contractor": "XYZ Co", "quantities": [], "evidence_count": 1}
        ],
        activity_count=1,
        issues=[
            {"issue_type": "WEATHER", "severity": "HIGH", "narrative": "heavy rain",
             "status": "OPEN"}
        ],
        open_issue_count=1,
    )
    data = build_document_data(code="DPR-1", payload=payload)
    html = render_html(data)
    assert "trench dug" in html
    assert "XYZ Co" in html
    assert "heavy rain" in html
    assert "severity-high" in html


def test_site_conditions_are_shown_and_tomorrows_plan_is_escaped():
    """BE-14: weather / site working / hours lost / tomorrow's plan. The plan
    is free text typed by a person, so it must not reach the renderer as HTML."""
    data = build_document_data(
        code="DPR-1",
        payload={
            "level": "SITE",
            "conditions": {
                "weather": "rainy",
                "site_working": "half",
                "hours_lost": "2.0",
                "tomorrow_plan": "<b>Rebar</b>",
            },
        },
    )
    assert (data.weather, data.site_working, data.hours_lost) == ("Rain", "Half day", "2.0 h")

    html = render_html(data)
    assert "Tomorrow&#39;s Plan" in html or "Tomorrow's Plan" in html
    assert "&lt;b&gt;Rebar&lt;/b&gt;" in html


def test_conditions_default_to_not_set():
    data = build_document_data(code="DPR-1", payload={"level": "SITE"})
    assert (data.weather, data.site_working, data.hours_lost, data.tomorrow_plan) == (
        "Not set",
        "Not set",
        "—",
        "",
    )


def test_render_html_flags_usage_beyond_known_stock():
    payload = _payload(
        materials=[
            {"material_name": "cement", "unit": "bags", "received": "0", "used": "50",
             "closing": "-50", "beyond_stock": True},
            {"material_name": "steel", "unit": "kg", "received": "10", "used": "5",
             "closing": "5", "beyond_stock": False},
        ],
    )
    html = render_html(build_document_data(code="DPR-1", payload=payload))
    assert "more Cement used than the site&#39;s known stock" in html or (
        "more Cement used than the site's known stock" in html
    )
    assert "more Steel used" not in html


def test_reports_stored_before_be12_have_no_stock_flag():
    payload = _payload(materials=[{"material_name": "cement", "unit": "bags",
                                   "received": "50", "used": "20"}])
    data = build_document_data(code="DPR-1", payload=payload)
    assert data.materials[0].beyond_stock is False
    assert "known stock" not in render_html(data)
