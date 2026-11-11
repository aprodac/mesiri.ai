"""PRC-51: the price list's rules -- when a quote is live, and one row per material from quotes and deliveries."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from mesiri.domains.procurement import price_list

TODAY = datetime.date(2026, 11, 11)
CEMENT, SAND = uuid.uuid4(), uuid.uuid4()


def _quote(material=CEMENT, *, valid_until=None, quoted_days_ago=1, name="Cement"):
    return {"material_id": material, "material_name": name, "unit": "bags", "quote_line_id": uuid.uuid4(),
            "rate": Decimal("472"), "gst_percent": Decimal("28"), "rate_includes_gst": True, "brand": None,
            "vendor_gstin": "32ABCDE1234F1Z5", "valid_until": valid_until,
            "quoted_at": datetime.datetime.combine(TODAY - datetime.timedelta(days=quoted_days_ago), datetime.time(9),
                                                   tzinfo=datetime.UTC),
            "rfq_id": uuid.uuid4(), "rfq_number": 3, "project_id": uuid.uuid4(), "site_id": uuid.uuid4()}


def _paid(material, rate, day, name):
    return {"material_id": material, "material_name": name, "unit": "cft", "unit_cost": Decimal(rate),
            "gst_percent": None, "rate_includes_gst": None, "vendor_gstin": None, "occurred_date": day,
            "order_id": None, "order_number": None}


def test_a_dated_quote_is_live_until_its_last_day_then_expired():
    assert price_list.is_live(_quote(valid_until=TODAY), TODAY)
    assert not price_list.is_live(_quote(valid_until=TODAY - datetime.timedelta(days=1)), TODAY)


def test_an_undated_quote_is_live_for_thirty_days():
    assert price_list.is_live(_quote(quoted_days_ago=price_list.UNDATED_DAYS), TODAY)
    assert not price_list.is_live(_quote(quoted_days_ago=price_list.UNDATED_DAYS + 1), TODAY)


def test_one_row_per_material_live_quotes_first_last_delivery_wins():
    rows = price_list.build(
        [_quote(valid_until=TODAY)],
        [_paid(SAND, "60", TODAY - datetime.timedelta(days=9), "Sand"), _paid(SAND, "65", TODAY, "Sand")],
        TODAY)
    assert [r["material_name"] for r in rows] == ["Cement", "Sand"]
    cement, sand = rows
    assert (cement["quoted"]["rate"], cement["quoted"]["rate_entered"], cement["quoted"]["rfq_ref"]) == (
        "368.75", "472.00", "RFQ-0003")  # costs before GST: the supplier has a GSTIN
    assert cement["paid"] is None and sand["quoted"] is None and sand["paid"]["rate"] == "65.00"
