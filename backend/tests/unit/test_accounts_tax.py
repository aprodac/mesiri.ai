"""ACC-10/11: place of supply, GST summary and TDS due dates, pure (domains/accounts/tax.py)."""

from __future__ import annotations

import datetime
from decimal import Decimal

from mesiri.domains.accounts.tax import pan_of, split, state_of, summarise_gst, tds_due

D = Decimal
DAY = datetime.date(2026, 10, 10)


def test_place_of_supply_splits_within_a_state_and_not_across():
    assert split(D("1800"), "32", "32") == {"igst": D(0), "cgst": D("900.00"), "sgst": D("900.00"), "unknown": D(0)}
    assert split(D("1800.01"), "32", "32")["sgst"] == D("900.00")  # the halves still add up
    assert split(D("1800"), "32", "29") == {"igst": D("1800.00"), "cgst": D(0), "sgst": D(0), "unknown": D(0)}
    assert split(D("1800"), None, "29")["unknown"] == D("1800.00")
    assert state_of("32AAAAA0000A1Z5") == "32" and state_of("bad") is None
    assert pan_of("32AAAAA0000A1Z5") == "AAAAA0000A" and pan_of(None) is None


def test_tds_is_due_on_the_seventh_and_march_by_the_thirtieth_of_april():
    assert tds_due(datetime.date(2026, 10, 1)) == datetime.date(2026, 11, 7)
    assert tds_due(datetime.date(2026, 12, 1)) == datetime.date(2027, 1, 7)
    assert tds_due(datetime.date(2027, 3, 1)) == datetime.date(2027, 4, 30)


def _p(gst, claimable, reason=None, gstin="32AAAAA0000A1Z5", supplier="Malabar"):
    return {"date": DAY, "gst": D(gst), "taxable": D(gst) * 5, "claimable": claimable, "reason": reason, "gstin": gstin,
            "supplier": supplier, **split(D(gst), "32", "32" if gstin else None)}


def test_gst_summary_nets_output_against_claimable_input_and_lists_what_was_missed():
    sales = [{"date": DAY, "gst": D(18000), "taxable": D(100000), "gstin": None, **split(D(18000), "32", None)}]
    purchases = [_p(1800, True), _p(500, False, "no_gstin", gstin=None, supplier="Local hardware"),
                 _p(90, False, "not_included")]
    out = summarise_gst(sales, purchases)
    assert out["output"]["gst"] == D(18000) and out["input"]["gst"] == D(1800) and out["payable"] == D(16200)
    assert out["missed"] == D(590)
    assert out["months"] == [{"month": "2026-10", "output": D(18000), "input": D(1800), "missed": D(590), "payable": D(16200)}]
    assert {w["key"] for w in out["warnings"]} == {"supplier_no_gstin", "gst_not_included", "client_no_gstin"}
    assert out["by_supplier"][0]["supplier"] == "Malabar" and out["by_supplier"][0]["claimable"] == D(1800)
