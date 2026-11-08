"""END-02 receivables maths and END-03 handover checklist steps: pure, no database."""

from __future__ import annotations

import datetime
from decimal import Decimal

from mesiri.domains.billing import receivables
from mesiri.domains.closeout import handover

D = Decimal
TODAY = datetime.date(2027, 3, 1)


def _bill(number, status, net, *, certified=None, retention="0", day=datetime.date(2027, 1, 1)):
    return {"id": f"b{number}", "ref": f"RA-{number:02d}", "number": number, "status": status, "bill_date": day,
            "net": D(net) if net is not None else None, "certified_amount": D(certified) if certified else None,
            "retention": D(retention)}


def test_due_is_certified_once_certified_else_net_and_never_a_draft() -> None:
    assert receivables.bill_due(_bill(1, "submitted", "1127160")) == D("1127160.00")
    assert receivables.bill_due(_bill(1, "certified", "1127160", certified="1100000")) == D("1100000.00")
    assert receivables.bill_due(_bill(1, "draft", None)) == 0
    assert receivables.bill_due(_bill(1, "cancelled", "5000")) == 0


def test_the_worked_example_in_the_module_docstring() -> None:
    bills = [_bill(1, "certified", "1127160", certified="1100000", retention="55800"),
             _bill(2, "submitted", "420000", retention="21000", day=datetime.date(2027, 2, 1)),
             _bill(3, "draft", None)]
    pays = [{"kind": "bill", "amount": D("600000"), "ra_bill_id": "b1"}]
    r = receivables.project_receivable(bills, pays, TODAY, handed_over_on=datetime.date(2027, 1, 15), defect_months=12)
    assert [b["ref"] for b in r["bills"]] == ["RA-01", "RA-02"]  # oldest first, draft left out
    assert r["bills"][0]["outstanding"] == D("500000.00") and r["bills"][1]["outstanding"] == D("420000.00")
    assert r["outstanding"] == D("920000.00") and r["oldest_days"] == 59
    assert r["retention_held"] == D("76800.00") and r["retention_left"] == D("76800.00")
    assert r["retention_due_on"] == datetime.date(2028, 1, 15) and not r["retention_due_now"]


def test_retention_released_and_due_now() -> None:
    bills = [_bill(1, "submitted", "100000", retention="5000")]
    pays = [{"kind": "bill", "amount": D("100000"), "ra_bill_id": "b1"},
            {"kind": "retention", "amount": D("2000"), "ra_bill_id": None}]
    r = receivables.project_receivable(bills, pays, TODAY, handed_over_on=datetime.date(2026, 1, 31), defect_months=12)
    assert r["outstanding"] == 0 and r["oldest_days"] is None
    assert r["retention_left"] == D("3000.00") and r["retention_due_now"]
    assert r["received"] == D("102000.00") and r["received_on_bills"] == D("100000.00")


def test_advance_left_never_below_zero() -> None:
    pays = [{"kind": "advance", "amount": D("900000"), "ra_bill_id": None}]
    r = receivables.project_receivable([], pays, TODAY, advance=D("850000"))
    assert r["advance_left"] == 0 and r["advance_received"] == D("900000.00")


def test_months_added_to_the_last_day_of_a_short_month() -> None:
    assert receivables.add_months(datetime.date(2027, 1, 31), 1) == datetime.date(2027, 2, 28)
    assert receivables.add_months(datetime.date(2027, 11, 30), 3) == datetime.date(2028, 2, 29)
    assert receivables.defects_end(None, 12) is None and receivables.defects_end(TODAY, None) is None


def test_a_payment_never_takes_a_bill_retention_or_advance_below_zero() -> None:
    bill = _bill(3, "submitted", "100000")
    assert "more than" in receivables.payment_problem("bill", D("100001"), bill=bill, bill_outstanding=D("100000"))
    assert receivables.payment_problem("bill", D("100000"), bill=bill, bill_outstanding=D("100000")) is None
    assert "Which bill" in receivables.payment_problem("bill", D("1"))
    assert "draft" in receivables.payment_problem("bill", D("1"), bill=_bill(4, "draft", None))
    assert "retention" in receivables.payment_problem("retention", D("6000"), retention_left=D("5000"))
    assert receivables.payment_problem("advance", D("1"), advance_left=None) is None  # no advance in the contract
    assert "advance" in receivables.payment_problem("advance", D("2"), advance_left=D("1"))
    assert receivables.payment_problem("other", D("99999999")) is None


def _facts(**over):
    f = {"progress": 100, "snags": {"open": 0, "fixed": 0, "closed": 4, "total": 4, "defects_pending": 0},
         "snags_overdue": 0, "work_orders_open": 0, "subcontract_bills_waiting": 0, "handed_over_on": None,
         "defect_liability_months": 12, "defects_end": None, "unbilled_lines": 0,
         "money": {"bills": [{"ref": "RA-01"}], "outstanding": D(0), "oldest_days": None, "retention_held": D("5000"),
                   "retention_left": D("5000"), "retention_due_now": False}}
    f.update(over)
    return f


def test_money_steps_are_left_out_for_a_role_that_may_not_see_client_money() -> None:
    keys = [s["key"] for s in handover.steps(_facts(), TODAY, money=False)]
    assert keys == ["work", "snags", "subcontracts", "handover"]
    keys = [s["key"] for s in handover.steps(_facts(), TODAY, money=True)]
    assert keys == ["work", "snags", "subcontracts", "final_bill", "paid", "handover"]


def test_no_snags_raised_is_not_snags_cleared() -> None:
    f = _facts(snags={"open": 0, "fixed": 0, "closed": 0, "total": 0, "defects_pending": 0})
    snag = next(s for s in handover.steps(f, TODAY, money=False) if s["key"] == "snags")
    assert not snag["done"] and "Walk every room" in snag["detail"]


def test_after_handover_the_defect_period_and_retention_steps_appear() -> None:
    f = _facts(handed_over_on=datetime.date(2026, 1, 31), defects_end=datetime.date(2027, 1, 31),
               snags={"open": 1, "fixed": 0, "closed": 4, "total": 5, "defects_pending": 1})
    steps = {s["key"]: s for s in handover.steps(f, TODAY, money=True)}
    assert not steps["defects"]["done"] and "1 defects the client raised still open" in steps["defects"]["detail"]
    assert not steps["retention"]["done"] and "₹5,000 held" in steps["retention"]["detail"]
    f["snags"] = {"open": 0, "fixed": 0, "closed": 5, "total": 5, "defects_pending": 0}
    f["money"]["retention_left"] = D(0)
    steps = {s["key"]: s for s in handover.steps(f, TODAY, money=True)}
    assert steps["defects"]["done"] and steps["retention"]["done"]
