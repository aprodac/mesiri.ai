"""NXT-11 / NXT-13: what a hired machine earns, its state on the board, service due, and the hire check."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from mesiri.domains.equipment import rules

D = datetime.date
P, S1, S2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _m(**kw) -> dict:
    return {"ownership": "hired", "rate": Decimal("1100"), "rate_unit": "hour", "min_hours_per_day": None,
            "status": "active", "site_id": S1, "project_id": P, "on_hire_from": None, "off_hire_on": None, **kw}


def _log(day: int, worked=None, idle=None, broke=None, site=S1, **kw) -> dict:
    return {"event_type": "day_log", "occurred_date": D(2026, 11, day), "duration_hours": worked, "idle_hours": idle,
            "breakdown_hours": broke, "project_id": P, "site_id": site, "voided_at": None, **kw}


def test_per_hour_charges_the_minimum_on_a_day_on_site_never_breakdown() -> None:
    m = _m(min_hours_per_day=Decimal(8))
    logs = [_log(1, worked=6, broke=2), _log(2, worked=10), _log(3, broke=8), _log(4, idle=8)]
    lines = rules.hire_lines(m, logs, D(2026, 11, 1), D(2026, 11, 30), D(2026, 11, 4))
    assert [(x["date"].day, x["hours"], x["amount"]) for x in lines] == [
        (1, 8, Decimal(8800)), (2, 10, Decimal(11000)), (4, 8, Decimal(8800))]  # day 3 only broken: nothing


def test_per_day_and_owned_and_voided() -> None:
    lines = rules.hire_lines(_m(rate=Decimal(9000), rate_unit="day"), [_log(1, worked=2), _log(2, broke=8)],
                             D(2026, 11, 1), D(2026, 11, 30), D(2026, 11, 30))
    assert [(x["date"].day, x["amount"]) for x in lines] == [(1, Decimal(9000))]
    assert rules.hire_lines(_m(ownership="owned"), [_log(1, worked=8)], D(2026, 11, 1), D(2026, 11, 2), D(2026, 11, 2)) == []
    voided = _log(1, worked=8, voided_at=datetime.datetime(2026, 11, 1, tzinfo=datetime.UTC))
    assert rules.hire_lines(_m(), [voided], D(2026, 11, 1), D(2026, 11, 2), D(2026, 11, 2)) == []


def test_per_month_every_calendar_day_on_hire_on_the_last_logged_site() -> None:
    m = _m(rate=Decimal(60000), rate_unit="month", on_hire_from=D(2026, 11, 3))
    lines = rules.hire_lines(m, [_log(4, worked=5, site=S2)], D(2026, 11, 1), D(2026, 11, 30), D(2026, 11, 6))
    assert [x["date"].day for x in lines] == [3, 4, 5, 6]  # not before on hire, not after today
    assert all(x["amount"] == Decimal(2000) for x in lines)
    assert [x["site_id"] for x in lines] == [S1, S2, S2, S2]  # before the log: the machine's site


def test_state_and_service() -> None:
    assert rules.state(_m(), None) == "not_logged"
    assert rules.state(_m(site_id=None), None) == "no_site"
    assert rules.state(_m(status="off_hire"), None) == "off_hire"
    assert rules.state(_m(), _log(1, broke=3)) == "breakdown"
    assert rules.state(_m(), _log(1, worked=2, broke=3)) == "working"
    assert rules.state(_m(), _log(1, idle=8)) == "idle"
    assert rules.service(_m(), Decimal(10)) is None
    every = _m(service_every_hours=Decimal(250))
    assert [rules.service(every, Decimal(h))["status"] for h in (100, 230, 250, 400)] == ["ok", "soon", "due", "due"]
    assert rules.service(every, Decimal(400))["left"] == "0"


def test_hire_check_flags_more_than_recorded_and_days_without_a_log() -> None:
    m = _m(min_hours_per_day=Decimal(8))
    logs = [_log(1, worked=6), _log(2, worked=9)]
    bill = {"period_from": D(2026, 11, 1), "period_to": D(2026, 11, 3), "billed_hours": Decimal(24),
            "billed_days": Decimal(3), "amount": Decimal(26400)}
    c = rules.hire_check(m, logs, bill, D(2026, 11, 10))
    assert (c["status"], c["recorded"]["charged_hours"], c["recorded"]["expected"], c["difference"]) == (
        "over", "17", "18700.00", "7700.00")
    assert c["days_not_logged"] == 1 and len(c["flags"]) == 4
    fair = {**bill, "billed_hours": Decimal(17), "billed_days": Decimal(2), "amount": Decimal(18700),
            "period_to": D(2026, 11, 2)}
    assert rules.hire_check(m, logs, fair, D(2026, 11, 10))["status"] == "ok"
    assert rules.hire_check(_m(rate=None, min_hours_per_day=Decimal(8)), logs, fair, D(2026, 11, 10))["status"] == "check"


def test_billed_days_only_with_an_expense_for_cost() -> None:
    bills = [{"period_from": D(2026, 11, 1), "period_to": D(2026, 11, 5), "expense_id": None}]
    assert rules.billed(D(2026, 11, 2), bills) is not None
    assert rules.billed(D(2026, 11, 2), bills, with_expense_only=True) is None
    assert rules.utilisation(Decimal(6), Decimal(0), Decimal(2)) == Decimal("0.750")
    assert rules.num(Decimal("6.00")) == "6" and rules.ref(7) == "EQ-0007"


def test_rupees_in_indian_grouping_whole_rupees() -> None:
    assert [rules.inr(Decimal(x)) for x in ("80300", "143000", "999.6", "12345678", "-4200")] == [
        "₹80,300", "₹1,43,000", "₹1,000", "₹1,23,45,678", "-₹4,200"]
