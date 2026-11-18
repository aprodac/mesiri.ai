"""ACC-18 / MP-06: the cash flow forecast's week maths (domains/accounts/cashflow.py), no database."""

from __future__ import annotations

import datetime
from decimal import Decimal

from mesiri.domains.accounts import cashflow

D = datetime.date
TODAY = D(2026, 11, 18)  # a Wednesday; its week starts Monday 16 Nov


def _item(kind: str, day: D, amount: str) -> dict:
    return {"kind": kind, "date": day, "amount": Decimal(amount)}


def test_weeks_start_on_monday_and_overdue_counts_this_week() -> None:
    placed = cashflow.place([_item("supplier_bills", D(2026, 11, 2), "100"),   # overdue
                             _item("supplier_bills", D(2026, 11, 22), "100"),  # Sunday: this week
                             _item("supplier_bills", D(2026, 11, 23), "100"),  # next Monday
                             _item("supplier_bills", D(2027, 3, 1), "100")],   # after 8 weeks
                            TODAY, 8)
    assert [(p["week"], p["overdue"]) for p in placed] == [(0, True), (0, False), (1, False), (None, False)]


def test_the_worked_example_in_the_module_docstring() -> None:
    items = cashflow.place([
        _item("client_bills", D(2026, 12, 1), "600000"),     # RA-03 billed 1 Nov, client 30 days
        _item("supplier_bills", D(2026, 11, 25), "80000"),   # cement bill 10 Nov, 15 days
        _item("wages_due", D(2026, 11, 18), "120000"),       # 9-15 Nov sheet, nothing paid
    ], TODAY, 4)
    t = cashflow.totals(items, TODAY, 4, Decimal("400000"))
    assert [w["balance"] for w in t["weeks"]] == [Decimal("280000"), Decimal("200000"), Decimal("800000"),
                                                  Decimal("800000")]
    assert t["lowest"] == {"balance": Decimal("200000"), "week": D(2026, 11, 23)}
    assert t["first_short"] is None


def test_first_week_short_of_cash_is_named() -> None:
    items = cashflow.place([_item("orders", D(2026, 11, 26), "500000")], TODAY, 4)
    t = cashflow.totals(items, TODAY, 4, Decimal("100000"))
    assert t["first_short"] == D(2026, 11, 23)


def test_work_not_billed_is_counted_only_when_asked() -> None:
    items = cashflow.place([_item("to_bill", D(2026, 11, 20), "50000")], TODAY, 4)
    assert cashflow.totals(items, TODAY, 4, Decimal(0))["weeks"][0]["in"] == 0
    on = cashflow.totals(items, TODAY, 4, Decimal(0), kinds=(*cashflow.DEFAULT_ON, "to_bill"))
    assert on["weeks"][0]["in"] == Decimal("50000")


def test_without_opening_cash_there_is_no_balance() -> None:
    t = cashflow.totals(cashflow.place([_item("client_bills", TODAY, "10")], TODAY, 4), TODAY, 4, None)
    assert "balance" not in t["weeks"][0] and t["lowest"] is None


def test_money_paid_ahead_settles_the_earliest_bills_first() -> None:
    bills = [_item("supplier_bills", D(2026, 11, 10), "300"), _item("delivered", D(2026, 11, 1), "200")]
    left = cashflow.take_off_advances(bills, Decimal("250"))
    assert [(b["date"], b["amount"]) for b in left] == [(D(2026, 11, 10), Decimal("250"))]


def test_wage_estimate_is_the_last_four_weeks_a_week() -> None:
    sheets = [{"period_to": D(2026, 11, 15), "net": "100000"}, {"period_to": D(2026, 11, 8), "net": "80000"},
              {"period_to": D(2026, 10, 1), "net": "999999"}]  # older than four weeks: left out
    assert cashflow.wage_estimate(sheets, TODAY) == Decimal("45000.00")
