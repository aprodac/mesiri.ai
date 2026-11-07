"""PRC-27: what is still to come on open orders counts for "running low" (it is not "what to order")."""

from decimal import Decimal

from mesiri.domains.materials.stock_summary import finish_row


def _row(closing: str, used_recently: str) -> dict:
    return {"opening": closing, "closing": closing, "received": "0", "used": "0", "used_recently": used_recently}


def test_ordered_stock_is_not_running_low() -> None:
    low = finish_row(_row("10", "70"))  # 10 a day, 1 day left
    assert low["running_low"] and low["on_order"] == 0
    covered = finish_row(_row("10", "70"), Decimal("50"))  # 60 with what is coming: 6 days
    assert not covered["running_low"] and covered["on_order"] == Decimal("50")
    assert covered["days_left"] == 1  # what the site holds now, honestly


def test_out_of_stock_with_an_order_coming_is_not_out() -> None:
    assert finish_row(_row("0", "0"))["running_low"]
    assert not finish_row(_row("0", "0"), Decimal("100"))["running_low"]


def test_guard_too_little_coming_is_still_low() -> None:
    assert finish_row(_row("10", "70"), Decimal("5"))["running_low"]  # 15 at 10 a day: under 3 days
