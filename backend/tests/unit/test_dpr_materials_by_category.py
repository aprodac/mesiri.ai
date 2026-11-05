"""PRC-17c: the daily report's materials, grouped by main category; a company without categories is unchanged."""

from __future__ import annotations

from mesiri.application.dpr.assembly import _material_summary


def _row(material_id: str, name: str, main: str | None, order: int | None, kind: str = "RECEIPT") -> dict:
    return {"material_id": material_id, "material_name": name, "unit": "nos", "movement_type": kind,
            "quantity": "5", "movement_reason": None, "main_category": main, "main_category_order": order}


def test_materials_come_grouped_in_the_companys_category_order() -> None:
    rows = [
        _row("a", "Socket 16A", "Electrical", 20),
        _row("b", "Cement", "Structural", 10),
        _row("c", "Nails", None, None),
        _row("d", "2-way switch", "Electrical", 20),
    ]
    out = _material_summary(rows)
    assert [(m["main_category"], m["material_name"]) for m in out] == [
        ("Structural", "Cement"), ("Electrical", "2-way switch"), ("Electrical", "Socket 16A"), (None, "Nails"),
    ]


def test_guard_without_categories_the_order_is_as_before() -> None:
    rows = [_row("a", "Steel", None, None), _row("b", "Cement", None, None)]
    assert [m["material_name"] for m in _material_summary(rows)] == ["Steel", "Cement"]
