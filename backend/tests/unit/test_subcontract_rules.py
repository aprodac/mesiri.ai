"""NXT-06/07: the subcontract bill check and deductions (pure rules, domains/subcontracts/rules.py)."""

from __future__ import annotations

from decimal import Decimal as D

from mesiri.domains.subcontracts import rules

LINES = {"c": {"description": "Concreting", "unit": "m³", "quantity": D("400"), "rate": D("380")}}


def test_as_measured_at_the_agreed_rate_passes() -> None:
    assert rules.check_bill(LINES, {"c": D("40")}, {}, [{"line_id": "c", "quantity": D("40"), "rate": D("380")}], D("15200")) == []


def test_more_than_measured_a_higher_rate_and_a_wrong_total_are_flagged() -> None:
    flags = rules.check_bill(LINES, {"c": D("40")}, {"c": D("30")}, [{"line_id": "c", "quantity": D("20"), "rate": D("400")}], D("9000"))
    assert [f["code"] for f in flags] == ["over_measured", "rate_above", "total_differs"]
    assert flags[0]["words"] == "billed 10 m³ more than measured on Concreting"


def test_nothing_measured_and_over_the_work_order() -> None:
    assert [f["code"] for f in rules.check_bill(LINES, {}, {}, [{"line_id": "c", "quantity": D("10"), "rate": D("380")}], D("3800"))] == ["not_measured"]
    over = rules.check_bill(LINES, {"c": D("450")}, {"c": D("390")}, [{"line_id": "c", "quantity": D("20"), "rate": D("380")}], D("7600"))
    assert [f["code"] for f in over] == ["over_agreed"]


def test_the_plan_worked_example() -> None:
    pct = rules.recovery_pct(D("20000"), D("152000"), None)
    d = rules.deductions(D("15200"), retention_pct=D("5"), recovery_pct_=pct, advance_outstanding=D("20000"), tds_pct=D("1"))
    assert (d["retention"], d["advance"], d["tds"], d["net"]) == (D("760.00"), D("2000.00"), D("152.00"), D("12288.00"))


def test_advance_never_more_than_outstanding_and_net_never_below_zero() -> None:
    d = rules.deductions(D("1000"), retention_pct=D("5"), recovery_pct_=D("100"), advance_outstanding=D("300"), tds_pct=None)
    assert (d["advance"], d["tds"], d["net"]) == (D("300.00"), D("0.00"), D("650.00"))
    d = rules.deductions(D("1000"), retention_pct=D("50"), recovery_pct_=D("100"), advance_outstanding=D("5000"), tds_pct=D("2"))
    assert d["net"] == D("0.00") and d["advance"] == D("480.00")
