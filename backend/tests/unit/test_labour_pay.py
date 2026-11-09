"""LW-03..LW-06: the wage and advance rules (domains/workforce/pay.py) and their posting (accounts/posting.py).

The class guarded: a wage figure must be the same as the labour cost cost-control shows for the same attendance (days
x wage, half days, absences, headcount groups), and money must balance in the books. Siblings: a named worker, a team
member paid through the contractor, a contractor named only in words, a headcount with no names, an unpriced line.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from mesiri.domains.accounts import posting
from mesiri.domains.workforce import pay

D = datetime.date
W1, W2, TEAM = "w-ravi", "w-anil", "v-suresh"


def line(**kw):
    base = {"date": D(2026, 11, 3), "worker_id": None, "worker_name": None, "trade": "mason", "headcount": 1,
            "daily_wage": Decimal("1000"), "contractor": None, "vendor_id": None, "vendor_name": None,
            "attendance_status": "present", "overtime_hours": None}
    return {**base, **kw}


def test_week_ends_on_saturday():
    assert pay.week_of(D(2026, 11, 9)) == (D(2026, 11, 8), D(2026, 11, 14))   # Monday -> Sunday to that Saturday
    assert pay.week_of(D(2026, 11, 14)) == (D(2026, 11, 8), D(2026, 11, 14))  # the pay day itself
    assert pay.week_of(D(2026, 11, 15)) == (D(2026, 11, 15), D(2026, 11, 21))  # Sunday starts the next week


def test_named_worker_half_day_absent_and_overtime():
    rows = pay.build_rows([
        line(worker_id=W1, worker_name="Ravi"),
        line(worker_id=W1, worker_name="Ravi", date=D(2026, 11, 4), attendance_status="half_day"),
        line(worker_id=W1, worker_name="Ravi", date=D(2026, 11, 5), attendance_status="absent"),
        line(worker_id=W1, worker_name="Ravi", date=D(2026, 11, 6), overtime_hours=Decimal(2)),
    ], {})
    r = rows[f"worker:{W1}"]
    assert r["man_days"] == Decimal("2.5")
    assert r["days"] == 3  # the absent day is not a day worked
    assert r["gross"] == Decimal("2500.00")
    assert r["overtime_amount"] == Decimal("250.00")  # 2 h x 1000 / 8 (D-W4)


def test_team_member_and_contractor_lines_are_paid_through_the_contractor():
    rows = pay.build_rows([
        line(worker_id=W2, worker_name="Anil"),  # on the register in Suresh's team
        line(vendor_id=TEAM, vendor_name="Suresh team", headcount=4, trade="helper", daily_wage=Decimal(800)),
    ], {W2: TEAM})
    assert set(rows) == {f"vendor:{TEAM}"}
    r = rows[f"vendor:{TEAM}"]
    assert r["man_days"] == Decimal(5)
    assert r["gross"] == Decimal("4200.00")


def test_words_headcount_and_unpriced_are_kept_not_lost():
    rows = pay.build_rows([
        line(contractor="Babu", headcount=3),
        line(trade="helper", headcount=6, daily_wage=None),
    ], {})
    assert rows["name:babu"]["gross"] == Decimal("3000.00")
    assert rows["headcount:helper"]["unpriced_man_days"] == Decimal(6)
    assert rows["headcount:helper"]["gross"] == Decimal("0.00")


def test_recovery_defaults_to_outstanding_capped_at_earnings():
    row = {"gross": Decimal("3000"), "overtime_amount": Decimal("0"), "deductions": [{"reason": "Damage", "amount": "500"}]}
    assert pay.settle(row, Decimal("1000")) == {"advances_recovered": Decimal("1000.00"), "net": Decimal("1500.00")}
    # More advance than the week earns: take back what it earns, the rest waits (D-W3).
    assert pay.settle(row, Decimal("9000")) == {"advances_recovered": Decimal("2500.00"), "net": Decimal("0.00")}
    # The payer's own figure wins.
    assert pay.settle(row, Decimal("1000"), Decimal("200")) == {"advances_recovered": Decimal("200.00"),
                                                                "net": Decimal("2300.00")}


def test_outstanding_ignores_voided_and_later_advances():
    advances = [{"amount": "500", "given_on": D(2026, 11, 2), "voided_at": None},
                {"amount": "300", "given_on": D(2026, 11, 3), "voided_at": datetime.datetime(2026, 11, 3)},
                {"amount": "700", "given_on": D(2026, 11, 20), "voided_at": None}]
    assert pay.outstanding_advances(advances, Decimal("100"), D(2026, 11, 14)) == Decimal("400.00")


def test_slip_says_what_was_earned_taken_back_and_due():
    text = pay.slip_text({"payee_name": "Suresh team", "man_days": Decimal(48), "trades": "mason", "gross": Decimal(38400),
                          "overtime_amount": 0, "advances_recovered": Decimal(5000), "deductions": [], "net": Decimal(33400),
                          "paid": Decimal(20000)}, D(2026, 11, 2), D(2026, 11, 8), "Villa Kakkanad")
    assert "Days: 48" in text and "₹38,400" in text and "−₹5,000" in text and "To pay: ₹33,400" in text
    assert "still due ₹13,400" in text


def test_labour_postings_balance():
    for entries in (posting.labour_accrual_entries(D(2026, 11, 30), "p", "s", Decimal("12345.5"), "Labour wages"),
                    posting.wage_row_entries(D(2026, 11, 14), "p", "s", "Ravi", Decimal("500"), Decimal("250"),
                                             Decimal("300"))):
        assert entries and all(posting.balanced(e) for e in entries)
    assert posting.labour_accrual_entries(D(2026, 11, 30), "p", "s", 0, "nil") == []


def test_contractor_named_in_words_joins_its_team_and_keeps_the_team_name():
    teams = {"by_id": {TEAM: "Suresh Labour Team"}, "by_name": {"suresh labour team": TEAM}}
    rows = pay.build_rows([
        line(contractor="  Suresh  labour team ", headcount=3, daily_wage=Decimal(800)),  # sent before the team existed
        line(worker_id=W2, worker_name="Anil", daily_wage=Decimal(800)),                 # a member on the register
    ], {W2: TEAM}, teams)
    assert set(rows) == {f"vendor:{TEAM}"}
    assert rows[f"vendor:{TEAM}"]["payee_name"] == "Suresh Labour Team"
    assert rows[f"vendor:{TEAM}"]["man_days"] == Decimal(4)
    # Guard: a contractor in words with no such team stays its own row, never folded into another team.
    other = pay.build_rows([line(contractor="Babu", headcount=2)], {}, teams)
    assert set(other) == {"name:babu"}
