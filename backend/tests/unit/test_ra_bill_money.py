"""NXT-02: an RA bill's money (domains/billing/ra.py)."""

from __future__ import annotations

from decimal import Decimal

from mesiri.domains.billing import ra

TERMS = {"retention_pct": "5", "advance_recovery_pct": "10", "gst_pct": "18", "tds_pct": "2"}
LINES = [{"quantity": "120", "client_rate": "6500"}, {"quantity": "800", "client_rate": "420"}]


def test_worked_example():
    t = ra.totals(LINES, TERMS, Decimal("850000"))
    assert t == {"gross": Decimal("1116000.00"), "retention": Decimal("55800.00"),
                 "advance_recovery": Decimal("111600.00"), "gst": Decimal("200880.00"), "tds": Decimal("22320.00"),
                 "net": Decimal("1127160.00")}


def test_recovery_stops_at_the_advance_left_and_never_goes_negative():
    assert ra.totals(LINES, TERMS, Decimal("40000"))["advance_recovery"] == Decimal("40000.00")
    assert ra.totals(LINES, TERMS, Decimal("-5"))["advance_recovery"] == Decimal("0.00")
    no_terms = ra.totals(LINES, {}, Decimal("0"))
    assert no_terms["net"] == no_terms["gross"] == Decimal("1116000.00")


def test_paisa_rounding_and_suggested_quantity():
    t = ra.totals([{"quantity": "0.333", "client_rate": "100.01"}], {"gst_pct": "18"}, Decimal(0))
    assert t["gross"] == Decimal("33.30") and t["gst"] == Decimal("5.99")
    assert ra.suggested(Decimal("50"), Decimal("30")) == Decimal("20")
    assert ra.suggested(Decimal("25"), Decimal("30")) == Decimal("0")  # measured less than billed: nothing more
