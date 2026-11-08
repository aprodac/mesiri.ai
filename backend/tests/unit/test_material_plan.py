"""MP-02: the material plan's maths (domains/materials/plan.py)."""

from __future__ import annotations

import datetime
from decimal import Decimal

from mesiri.domains.materials import plan

D = datetime.date
MON = D(2026, 11, 9)  # a Monday
CEMENT = {"material_id": "c", "material": "Cement", "unit": "bags", "per_unit": "8", "wastage_pct": "5"}


def _line(**kw):
    base = {"id": "l1", "work": "M20 in slab", "unit": "cum", "planned": "30", "done": "10",
            "start": D(2026, 11, 11), "end": D(2026, 11, 24), "finished": False, "norms": [CEMENT]}
    return {**base, **kw}


def test_worked_example_spreads_the_rest_over_the_days_to_come_and_finds_the_short_week():
    out = plan.build([_line()], {"c": {"unit": "bags", "on_hand": "100", "on_order": "0"}}, D(2026, 11, 10), weeks=4)
    assert out["weeks"] == [MON, D(2026, 11, 16), D(2026, 11, 23), D(2026, 11, 30)]
    row = out["materials"][0]
    assert row["required"] == Decimal("252.000")  # 30 × 8 × 1.05
    assert row["still_needed"] == Decimal("168.000")  # 20 × 8 × 1.05
    assert row["weeks"] == [Decimal("60.000"), Decimal("84.000"), Decimal("24.000"), Decimal("0.000")]
    assert row["short_from"] == D(2026, 11, 16) and row["short_by"] == Decimal("68.000")
    assert row["lines"][0]["need"] == Decimal("168.000") and row["lines"][0]["late"] is False


def test_enough_stock_or_on_order_is_not_short():
    out = plan.build([_line()], {"c": {"unit": "bags", "on_hand": "100", "on_order": "70"}}, D(2026, 11, 10), weeks=4)
    row = out["materials"][0]
    assert row["short_from"] is None and row["short_by"] == 0


def test_late_activity_needs_the_rest_in_the_next_week():
    out = plan.build([_line(start=D(2026, 10, 1), end=D(2026, 10, 31))], {}, D(2026, 11, 10), weeks=2)
    row = out["materials"][0]
    # 168 bags over 10-16 Nov: 6 days in this week (10-15), 1 day in the next (16).
    assert row["weeks"] == [Decimal("144.000"), Decimal("24.000")]
    assert row["lines"][0]["late"] is True
    assert row["short_from"] == MON  # nothing in stock


def test_finished_done_and_unscheduled_lines():
    lines = [
        _line(id="a", finished=True),
        _line(id="b", done="35"),  # more done than planned: nothing left, never negative
        _line(id="c", start=None, end=None),
    ]
    row = plan.build(lines, {}, D(2026, 11, 10), weeks=2)["materials"][0]
    assert row["required"] == Decimal("756.000")
    assert row["still_needed"] == row["unscheduled"] == Decimal("168.000")
    assert row["weeks"] == [0, 0] and row["short_from"] is None
    assert [ln["line_id"] for ln in row["lines"]] == ["c"]


def test_need_beyond_the_weeks_shown_is_later_and_a_future_start_waits():
    out = plan.build([_line(start=D(2026, 11, 23), end=D(2026, 12, 6))], {}, D(2026, 11, 10), weeks=2)
    row = out["materials"][0]
    assert row["weeks"] == [0, 0] and row["later"] == Decimal("168.000") and row["short_from"] is None


def test_stock_in_another_unit_is_not_counted_and_said():
    out = plan.build([_line()], {"c": {"unit": "kg", "on_hand": "5000", "on_order": "0"}}, D(2026, 11, 10), weeks=4)
    row = out["materials"][0]
    assert row["stock_unit_differs"] is True and row["on_hand"] == 0 and row["short_from"] == MON


def test_materials_add_up_across_lines_and_sort_short_soonest_first():
    sand = {"material_id": "s", "material": "M-sand", "unit": "cft", "per_unit": "15", "wastage_pct": "0"}
    steel = {"material_id": "t", "material": "Steel", "unit": "kg", "per_unit": "100", "wastage_pct": "0"}
    lines = [_line(norms=[CEMENT, sand]), _line(id="l2", work="M20 in beams", norms=[CEMENT, steel])]
    stock = {"c": {"unit": "bags", "on_hand": "1000"}, "t": {"unit": "kg", "on_hand": "0"}, "s": {"unit": "cft", "on_hand": "0"}}
    rows = plan.build(lines, stock, D(2026, 11, 10), weeks=4)["materials"]
    assert [r["material"] for r in rows] == ["M-sand", "Steel", "Cement"]
    assert rows[2]["still_needed"] == Decimal("336.000") and rows[2]["short_from"] is None
    assert len(rows[2]["lines"]) == 2
