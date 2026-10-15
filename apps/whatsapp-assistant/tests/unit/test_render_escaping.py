"""BE-36: text people typed on WhatsApp never reaches the PDF/receipt renderer as HTML."""

from __future__ import annotations

import pytest

from channel.dpr_document.data import build_document_data
from channel.locked_page import new_locked_page
from channel.receipt.data import (
    ReceiptCorrection,
    ReceiptData,
    ReceiptField,
    ReceiptLocationRow,
)

jinja2 = pytest.importorskip("jinja2")
from channel.dpr_document.template import render_html as render_dpr  # noqa: E402
from channel.receipt.template import render_html as render_receipt  # noqa: E402

EVIL = '<script>fetch("http://169.254.169.254/")</script><img src=x onerror=alert(1)>'
ESCAPED = "&lt;script&gt;"


def _assert_inert(html: str) -> None:
    # Lower-cased: the DPR title-cases names ("<Script>").
    html = html.lower()
    assert "<script>" not in html
    assert "<img src=x" not in html
    assert "onerror=alert(1)>" not in html  # only ever as escaped text
    assert ESCAPED in html


def test_dpr_escapes_every_user_field_at_site_level() -> None:
    data = build_document_data(
        code="DPR-1",
        payload={
            "level": "SITE",
            "project_name": EVIL,
            "site_name": EVIL,
            "report_date": "2026-10-15",
            "activities": [
                {
                    "work_type": "plastering",
                    "narrative": EVIL,
                    "status": "IN_PROGRESS",
                    "contractor": EVIL,
                    "quantities": [{"work_type": "x", "quantity": "1", "unit": EVIL}],
                    "evidence_count": 0,
                }
            ],
            "activity_count": 1,
            "issues": [
                {"issue_type": "WEATHER", "severity": "HIGH", "narrative": EVIL, "status": "OPEN"}
            ],
            "open_issue_count": 1,
            "labour": {"headcount": 3, "trades": [{"trade": EVIL, "headcount": 3}]},
            "materials": [{"material_name": EVIL, "unit": EVIL, "received": "2", "used": "1"}],
            "conditions": {"tomorrow_plan": EVIL},
        },
    )
    html = render_dpr(data)
    _assert_inert(html)
    # Every narrative, contractor and name made it through as text.
    assert html.lower().count(ESCAPED) >= 5


def test_dpr_escapes_site_names_at_project_level() -> None:
    data = build_document_data(
        code="DPR-2",
        payload={
            "level": "PROJECT",
            "project_name": "Skyline",
            "sites": [{"site_name": EVIL, "reported": True, "activity_count": 1}],
            "issues": [],
        },
    )
    _assert_inert(render_dpr(data))


def test_dpr_ordinary_text_is_unchanged() -> None:
    data = build_document_data(
        code="DPR-3",
        payload={
            "level": "SITE",
            "project_name": "Green Villa",
            "site_name": "Block A",
            "activities": [
                {
                    "work_type": "masonry",
                    "narrative": "2nd floor slab — 40 bags cement",
                    "status": "COMPLETED",
                    "contractor": "Biju & Sons",
                    "quantities": [],
                    "evidence_count": 1,
                }
            ],
            "activity_count": 1,
        },
    )
    html = render_dpr(data)
    assert "2nd floor slab — 40 bags cement" in html
    assert "Biju &amp; Sons" in html  # & is escaped, as HTML requires


def _receipt(**overrides) -> ReceiptData:
    fields = {
        "brand": "Mesiri",
        "category": "Material",
        "value": EVIL,
        "subtitle": EVIL,
        "location": [ReceiptLocationRow(icon="building", text=EVIL)],
        "date": "15 Oct",
        "time": "10:30",
        "sections": [[ReceiptField(icon="hash", label=EVIL, value=EVIL)]],
        "id_label": "ID",
        "record_id": EVIL,
        "saved_at": "10:30",
        "logo_text": "M",
        "correction": ReceiptCorrection(old_value=EVIL, new_value=EVIL),
        "template_variant": "activity",
    }
    fields.update(overrides)
    return ReceiptData(**fields)


def test_receipt_escapes_values_and_keeps_icons() -> None:
    html = render_receipt(_receipt())
    _assert_inert(html)
    # The built-in icons are still real SVG, not escaped text.
    assert "<svg" in html and "&lt;svg" not in html


# -- the locked-down browser page ---------------------------------------------------


class _Page:
    def __init__(self) -> None:
        self.routes = []

    async def route(self, pattern, handler) -> None:
        self.routes.append((pattern, handler))


class _Browser:
    def __init__(self) -> None:
        self.options = None
        self.page = _Page()

    async def new_page(self, **options):
        self.options = options
        return self.page


class _Route:
    def __init__(self) -> None:
        self.aborted = False

    async def abort(self) -> None:
        self.aborted = True


async def test_locked_page_has_no_javascript_and_no_network() -> None:
    browser = _Browser()
    page = await new_locked_page(browser, viewport={"width": 680, "height": 800})
    assert browser.options == {
        "java_script_enabled": False,
        "viewport": {"width": 680, "height": 800},
    }
    pattern, handler = page.routes[0]
    assert pattern == "**/*"
    route = _Route()
    await handler(route)
    assert route.aborted
