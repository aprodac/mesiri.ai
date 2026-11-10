"""PRC-47: the minimum-stock rules (no database)."""

from __future__ import annotations

from decimal import Decimal

from mesiri.domains.materials.stock_levels import below_rows, draft_link, note
from mesiri.domains.materials.stock_summary import finish_row, reorder_quantity, suggest_minimum

D = Decimal


def _row(closing: str, used_recently: str = "0") -> dict:
    return {"site_id": "s1", "material_id": "m1", "opening": closing, "received": "0", "used": "0",
            "closing": closing, "used_recently": used_recently}


def test_below_the_minimum_is_low_and_the_chip_even_with_no_use() -> None:
    row = finish_row(_row("40"), D(0), {"min_qty": D(100), "reorder_qty": None})
    assert (row["below_min"], row["running_low"], row["min_qty"]) == (True, True, D(100))


def test_what_is_coming_lifts_running_low_but_not_the_chip() -> None:
    row = finish_row(_row("40"), D(80), {"min_qty": D(100), "reorder_qty": D(200)})
    assert (row["below_min"], row["running_low"], row["reorder_qty"]) == (True, False, D(200))


def test_guard_no_minimum_keeps_the_days_rule_alone() -> None:
    assert finish_row(_row("300", "7"), D(0))["running_low"] is False
    row = finish_row(_row("2", "7"), D(0))
    assert (row["running_low"], row["below_min"], row["min_qty"]) == (True, False, None)


def test_reorder_quantity_is_the_set_one_else_back_to_twice_the_minimum() -> None:
    assert reorder_quantity(D(40), D(0), D(100), D(250)) == D(250)
    assert reorder_quantity(D(40), D(30), D("100"), None) == D(130)
    assert reorder_quantity(D("40.4"), D(0), D(100), None) == D(160)


def test_suggest_is_a_week_plus_lead_time_of_use() -> None:
    assert suggest_minimum(D(14), 2) == (D(18), D(28))
    assert suggest_minimum(D(10), 0) == (D(10), D(20))  # 1.43 a day rounds up
    assert suggest_minimum(D(0), 3) is None


def _site_rows():
    sites = {"s1": {"name": "Block A", "project_id": "p1", "project_name": "Villa"}}
    materials = {"m1": {"name": "Cement", "unit": "bags", "unit_id": "u1"},
                 "m2": {"name": "Sand", "unit": "cft", "unit_id": "u2"}}
    levels = {("s1", "m1"): {"min_qty": D(100), "reorder_qty": None}, ("s1", "m2"): {"min_qty": D(50), "reorder_qty": None}}
    summary = [{**_row("40"), "on_order": D(0), "days_left": None}]  # sand never held at the site
    return summary, levels, materials, sites


def test_an_item_never_held_is_below_with_nothing_and_a_request_covers_it() -> None:
    summary, levels, materials, sites = _site_rows()
    rows = below_rows(summary, levels, {("s1", "m2"): "REQ-0004"}, materials, sites)
    assert [(r["material"], r["closing"], r["to_order"], r["covered_by"]) for r in rows] == [
        ("Cement", "40", "160", None), ("Sand", "0", "100", "REQ-0004")]


def test_the_note_lists_only_what_nothing_buys_with_both_links() -> None:
    summary, levels, materials, sites = _site_rows()
    text = note("Villa", below_rows(summary, levels, {("s1", "m2"): "REQ-0004"}, materials, sites), "https://app")
    assert text is not None and "1 item below minimum at Block A" in text and "Sand" not in text
    assert "Cement 40 bags (min 100), order 160" in text
    assert draft_link("https://app", "s1", "rfq") in text and draft_link("https://app", "s1", "request") in text
    assert note("Villa", below_rows(summary, levels, {("s1", "m1"): "RFQ-0002", ("s1", "m2"): "x"}, materials, sites),
                "https://app") is None
