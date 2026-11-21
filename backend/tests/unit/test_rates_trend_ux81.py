"""UX-81: a rate that rose earlier in the period and then held reads "up", not "same".

Found filming episode 2 (20 Nov 2026): M sand came at ₹1,650 a cum, then at ₹1,750 for its last several loads;
Rates said "₹1,650–₹1,750 · same" because it compared the last load with the one just before it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from mesiri.domains.procurement.rates import summarise

MAT = uuid.uuid4()


def _row(day: int, rate: str, vendor: str = "Periyar Sand & Aggregates") -> dict:
    return {"material_id": MAT, "material_name": "M Sand", "unit": "cum", "quantity": Decimal("6"),
            "unit_cost": Decimal(rate), "occurred_date": dt.date(2026, 11, day), "supplier": vendor}


def _one(rows: list[dict], before: dict | None = None) -> dict:
    (item,) = summarise(rows, before or {})
    return item


def test_a_rise_that_then_held_is_up_against_the_last_different_rate() -> None:
    item = _one([_row(2, "1650"), _row(5, "1650"), _row(11, "1750"), _row(12, "1750"), _row(14, "1750")])
    assert item["trend"] == "up"
    assert item["change_pct"] == "6.1"
    assert item["previous"]["rate"] == "1650.00" and item["previous"]["date"] == "2026-11-05"


def test_a_rate_that_never_changed_stays_same() -> None:
    item = _one([_row(2, "1450"), _row(9, "1450"), _row(14, "1450")])
    assert item["trend"] == "same" and item["previous"]["rate"] == "1450.00"


def test_a_change_within_the_steady_band_is_not_a_new_rate() -> None:
    # 1% is noise (STEADY_PCT): the rate before it is the one compared, and that is "same".
    item = _one([_row(2, "1000"), _row(9, "1010"), _row(14, "1010")])
    assert item["trend"] == "same"


def test_when_the_whole_period_held_the_rate_before_the_period_is_compared() -> None:
    before = {MAT: _row(1, "1600") | {"occurred_date": dt.date(2026, 10, 20)}}
    item = _one([_row(2, "1750"), _row(14, "1750")], before)
    assert item["trend"] == "up" and item["previous"]["in_period"] is False


def test_one_purchase_against_the_one_before_the_period_as_before() -> None:
    before = {MAT: _row(1, "64") | {"occurred_date": dt.date(2026, 6, 1)}}
    item = _one([_row(14, "60")], before)
    assert item["trend"] == "down"
