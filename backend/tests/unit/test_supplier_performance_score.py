"""PRC-50: the supplier score maths -- each measure to 0-5, weights (D-P2-5), missing measures, too little history."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from mesiri.domains.vendors import performance as perf

TODAY = datetime.date(2026, 11, 11)


def _grn(day: datetime.date, expected: datetime.date | None, accepted="10", rejected="0", reason=None):
    return {"id": uuid.uuid4(), "number": 1, "received_on": day, "order_id": uuid.uuid4(), "order_number": 4,
            "expected_date": expected,
            "lines": [{"accepted": Decimal(accepted), "rejected": Decimal(rejected), "reason": reason,
                       "material": "Cement", "unit": "bags"}]}


def test_weights_add_up_to_100_and_quote_response_is_not_one():
    assert sum(perf.WEIGHTS.values()) == 100
    assert perf.WEIGHTS == {"on_time": 35, "complete": 20, "quality": 25, "price": 20}


def test_each_measure_to_0_5():
    assert perf._part("on_time", Decimal(100)) == 5 and perf._part("on_time", Decimal(50)) == Decimal("2.5")
    assert perf._part("quality", Decimal(0)) == 5 and perf._part("quality", Decimal(5)) == Decimal("2.5")
    assert perf._part("quality", Decimal(40)) == 0  # never below 0
    assert perf._part("price", Decimal("0.90")) == 5 and perf._part("price", Decimal("1.05")) == Decimal("2.5")
    assert perf._part("price", Decimal("1.30")) == 0


def test_the_weighted_score_and_a_missing_measure_is_left_out_not_zero():
    full, parts = perf.score({"on_time": Decimal(100), "complete": Decimal(100), "quality": Decimal(0),
                              "price": Decimal("1.15")})
    assert full == Decimal(4) and parts["price"] == 0  # 80 of 100 weight at 5, price at 0
    no_price, parts = perf.score({"on_time": Decimal(100), "complete": Decimal(100), "quality": Decimal(0),
                                  "price": None})
    assert no_price == 5 and "price" not in parts
    assert perf.score({"on_time": None, "complete": None, "quality": None, "price": None}) == (None, {})


def test_too_little_history_shows_no_score_but_the_measures():
    grns = [_grn(TODAY, TODAY), _grn(TODAY, TODAY)]
    out = perf.build("v", grns=grns, orders=[], rate_items=[], quotes={}, rating=None, today=TODAY)
    assert out["enough"] is False and out["score"] is None and out["measures"]["on_time"]["pct"] == "100.0"
    out = perf.build("v", grns=[*grns, _grn(TODAY, TODAY)], orders=[], rate_items=[], quotes={}, rating=None, today=TODAY)
    assert out["enough"] is True and out["score"] == "5.0"


def test_late_and_rejected_count_against_and_are_listed_as_problems():
    late = _grn(TODAY, TODAY - datetime.timedelta(days=2))
    torn = _grn(TODAY - datetime.timedelta(days=1), None, accepted="8", rejected="2", reason="torn bags")
    out = perf.build("v", grns=[late, torn, _grn(TODAY, TODAY)], orders=[], rate_items=[],
                     quotes={"asked": 4, "quoted": 3}, rating=None, today=TODAY)
    m = out["measures"]
    assert (m["on_time"]["pct"], m["on_time"]["of"]) == ("50.0", 2)  # the GRN with no expected date is not counted
    assert m["rejected"]["pct"] == "6.7"  # (0 + 20 + 0) / 3
    assert m["quote_response"] == {"pct": "75.0", "quoted": 3, "asked": 4}
    assert [p["kind"] for p in out["problems"]] == ["late", "rejected"]
    assert out["problems"][0]["what"] == "2 days late" and "torn bags" in out["problems"][1]["what"]


def test_price_index_only_on_items_someone_else_also_delivered():
    items = [
        {"avg_rate": "400", "vendors": [{"vendor_id": "v", "quantity": "100", "avg_rate": "380"},
                                        {"vendor_id": "w", "quantity": "100", "avg_rate": "420"}]},
        {"avg_rate": "60", "vendors": [{"vendor_id": "v", "quantity": "500", "avg_rate": "60"}]},
    ]
    index, n = perf.price_index(items, "v")
    assert (index, n) == (Decimal("0.95"), 1)
    assert perf.price_index(items[1:], "v") == (None, 0)


def test_trend_has_six_months_and_a_month_without_deliveries_is_empty():
    out = perf.build("v", grns=[_grn(TODAY, TODAY)], orders=[], rate_items=[], quotes={}, rating=None, today=TODAY)
    assert [t["month"] for t in out["trend"]] == ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"]
    assert out["trend"][-1]["score"] == "5.0" and out["trend"][0]["score"] is None
