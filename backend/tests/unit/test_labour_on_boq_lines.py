"""CC-05: labour put on BOQ lines, shared by man-days (domains/costing/labour.py)."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from mesiri.domains.costing.labour import group_key, labour_by_line, share_group

DAY = datetime.date(2026, 11, 7)
SITE = uuid.uuid4()
PLASTER, BRICK = uuid.uuid4(), uuid.uuid4()


def _group(trade: str, man_days: str, cost: str, priced: str | None = None) -> dict:
    return {"site_id": SITE, "work_date": DAY, "trade_key": trade, "man_days": Decimal(man_days),
            "priced_man_days": Decimal(priced if priced is not None else man_days), "cost": Decimal(cost)}


def _alloc(trade: str, line, man_days: str) -> dict:
    return {"site_id": SITE, "work_date": DAY, "trade_key": trade, "planned_item_id": line, "man_days": Decimal(man_days)}


def test_the_gm_example_masons_split_helpers_left_and_it_adds_up():
    # 4 masons at 1,100 + 2 helpers at 1,000 = 6,400. Masons: 3 on plastering, 1 on brickwork.
    groups = [_group("mason", "4", "4400"), _group("helper", "2", "2000")]
    out = labour_by_line(groups, [_alloc("mason", PLASTER, "3"), _alloc("mason", BRICK, "1")])
    assert out["lines"][PLASTER]["cost"] == Decimal("3300.00") and out["lines"][BRICK]["cost"] == Decimal("1100.00")
    assert out["not_on_a_line"] == {"man_days": Decimal("2"), "cost": Decimal("2000.00"), "unpriced_man_days": 0}
    on_lines = sum((v["cost"] for v in out["lines"].values()), Decimal(0))
    assert on_lines + out["not_on_a_line"]["cost"] == out["total"]["cost"] == Decimal("6400")


def test_shares_round_to_the_paisa_and_the_rest_takes_the_rounding():
    # 3 man-days for 1,000: thirds do not divide; the lines and the rest still add up to 1,000 exactly.
    shared = share_group(_group("mason", "3", "1000"), [{"line_id": PLASTER, "man_days": Decimal("1")},
                                                        {"line_id": BRICK, "man_days": Decimal("1")}])
    assert [p["cost"] for p in shared["on_lines"]] == [Decimal("333.33"), Decimal("333.33")]
    assert shared["not_on_a_line"]["cost"] == Decimal("333.34")


def test_a_corrected_down_day_never_costs_more_than_attendance():
    # 12 masons were split 8 + 4, then the list was re-sent as 10: lines share the 10, said as over-allocated.
    shared = share_group(_group("mason", "10", "10000"), [{"line_id": PLASTER, "man_days": Decimal("8")},
                                                          {"line_id": BRICK, "man_days": Decimal("4")}])
    assert shared["over_allocated"] is True
    assert sum(p["cost"] for p in shared["on_lines"]) == Decimal("10000.00")
    assert sum(p["man_days"] for p in shared["on_lines"]) == Decimal("10")
    assert shared["not_on_a_line"] == {"man_days": 0, "cost": Decimal("0.00")}


def test_no_wage_gives_man_days_but_no_cost_never_zero_rupees():
    out = labour_by_line([_group("helper", "2", "0", priced="0")], [_alloc("helper", PLASTER, "2")])
    assert out["lines"][PLASTER] == {"man_days": Decimal("2"), "cost": 0, "unpriced_man_days": Decimal("2")}
    assert share_group(_group("helper", "2", "0", priced="0"), [])["cost"] is None


def test_a_revised_line_keeps_its_labour_and_a_withdrawn_day_counts_nothing():
    old, new = uuid.uuid4(), uuid.uuid4()
    gone = {**_alloc("mason", PLASTER, "2"), "work_date": DAY - datetime.timedelta(days=1)}  # report withdrawn
    out = labour_by_line([_group("mason", "2", "2000")], [_alloc("mason", old, "2"), gone], current_of={old: new})
    assert set(out["lines"]) == {new} and out["lines"][new]["cost"] == Decimal("2000.00")


def test_the_group_key_is_the_same_however_the_trade_was_typed():
    assert group_key(SITE, DAY, " Mason ") == group_key(str(SITE), "2026-11-07", "mason")
    assert group_key(None, DAY, None) == (None, "2026-11-07", "")
