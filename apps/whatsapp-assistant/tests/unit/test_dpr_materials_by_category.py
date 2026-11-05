"""PRC-17c: the daily report document draws a heading row each time the main category changes."""

from __future__ import annotations

from channel.dpr_document.data import build_document_data
from channel.dpr_document.template import render_html


def _material(name: str, main: str | None) -> dict:
    return {"material_name": name, "received": "5", "used": "0", "unit": "nos", "main_category": main}


def test_headings_mark_each_main_category_and_the_rest_is_other() -> None:
    payload = {"materials": [_material("Cement", "Structural"), _material("2-way switch", "Electrical"),
                             _material("Socket", "Electrical"), _material("Nails", None)]}
    data = build_document_data(code="DPR-1", payload=payload)
    assert [m.group for m in data.materials] == ["Structural", "Electrical", None, "Other"]
    html = render_html(data, None)
    assert html.count('<tr class="group">') == 3 and ">Electrical</td>" in html


def test_guard_a_report_without_categories_has_no_headings() -> None:
    payload = {"materials": [_material("Cement", None), _material("Steel", None)]}
    data = build_document_data(code="DPR-1", payload=payload)
    assert all(m.group is None for m in data.materials)
    assert '<tr class="group">' not in render_html(data, None)
