"""PRC-48 / PRC-49: count differences and stock value rules (no database)."""

from __future__ import annotations

import datetime
from decimal import Decimal

from mesiri.domains.materials.stock_count import difference, due_message, pick_top, review
from mesiri.domains.materials.valuation import summarise, value_rows, weighted

D = Decimal


def test_weighted_average_is_by_quantity_at_what_each_unit_cost() -> None:
    rows = [{"material_id": "c", "quantity": D(100), "unit_cost": D(400), "gst_percent": D(18), "rate_includes_gst": False,
             "vendor_gstin": "32AAA"},
            {"material_id": "c", "quantity": D(50), "unit_cost": D(400), "gst_percent": D(18), "rate_includes_gst": False,
             "vendor_gstin": None}]
    assert weighted(rows) == {"c": D(424)}


def test_value_skips_nothing_held_flags_slow_and_never_prices_the_unpriced_at_zero() -> None:
    summary = [{"site_id": "s", "project_id": "p", "material_id": "c", "material_name": "Cement", "unit": "bags",
                "closing": "120", "used": "30", "main_category": "Structural"},
               {"site_id": "s", "project_id": "p", "material_id": "t", "material_name": "TMT", "unit": "kg",
                "closing": "500", "used": "0", "main_category": "Structural"},
               {"site_id": "s", "project_id": "p", "material_id": "w", "material_name": "Wire", "unit": "kg",
                "closing": "10", "used": "0", "main_category": None},
               {"site_id": "s", "project_id": "p", "material_id": "x", "material_name": "Gone", "unit": "nos",
                "closing": "0", "used": "4", "main_category": None}]
    rows = value_rows(summary, {"c": D(424), "t": D(60)})
    assert [(r["material"], r["value"], r["slow_moving"]) for r in rows] == [
        ("Cement", "50880.00", False), ("TMT", "30000.00", True), ("Wire", None, True)]
    s = summarise(rows)
    assert (s["total"], s["unpriced"], s["slow_moving"], s["slow_moving_value"]) == ("80880.00", 1, 2, "30000.00")
    assert rows[0]["material"] == "Cement" and s["by_category"][0] == {"category": "Structural", "value": "80880.00"}


def test_count_differences_and_rupees_not_counted_left_out() -> None:
    lines = [{"book_qty": D(100), "counted_qty": D(92), "rate": D(400)},
             {"book_qty": D(2000), "counted_qty": D(2100), "rate": D(60)},
             {"book_qty": D(5), "counted_qty": None, "rate": D(10)},
             {"book_qty": D(7), "counted_qty": D(7), "rate": None}]
    assert difference(lines[0]) == {"difference": D(-8), "difference_value": D(-3200)}
    assert difference(lines[2]) == {"difference": None, "difference_value": None}
    r = review(lines)
    assert (r["counted"], r["not_counted"], r["differing"], r["net_value"], r["gross_value"]) == (3, 1, 2, D(2800), D(9200))


def test_top_is_by_value_and_the_due_note_names_never_counted() -> None:
    rows = [{"material_id": m, "closing": q} for m, q in (("a", "10"), ("b", "1"), ("c", "100"))]
    assert [r["material_id"] for r in pick_top(rows, {"a": D(5), "b": D(1000)}, n=2)] == ["b", "a"]
    text = due_message("Villa", [{"name": "Block A", "last": None},
                                 {"name": "Yard", "last": datetime.datetime(2026, 9, 1)}])
    assert "Block A: never counted" in text and "Yard: last counted 01 Sep" in text
    assert due_message("Villa", []) is None
