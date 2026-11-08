"""NXT-03: what clients owe (domains/billing/receivables.py)."""

from __future__ import annotations

import datetime
from decimal import Decimal

from mesiri.domains.billing.receivables import by_client, settle

TODAY = datetime.date(2026, 11, 8)


def _bill(i, net, day, status="submitted", project="p1", client="c1"):
    return {"id": i, "number": int(i[-1]), "project_id": project, "client_id": client, "bill_date": day,
            "net": Decimal(net), "status": status}


def _r(kind, amount, bill=None, project="p1"):
    return {"kind": kind, "amount": Decimal(amount), "ra_bill_id": bill, "project_id": project}


def test_the_worked_example_on_account_settles_the_oldest_bill_first():
    bills = [_bill("b1", "1127160", datetime.date(2026, 9, 1)), _bill("b2", "640000", datetime.date(2026, 10, 1))]
    s = settle(bills, [_r("bill", "1000000", "b1"), _r("on_account", "500000")], TODAY)
    b1, b2 = s["bills"]
    assert (b1["left"], b1["on_account_applied"]) == (Decimal(0), Decimal("127160"))
    assert (b2["left"], b2["bucket"], b2["days"]) == (Decimal("267160"), "31_60", 38)
    assert s["unapplied"] == {}


def test_an_advance_is_never_applied_to_a_bill_and_drafts_or_cancelled_bills_are_not_owed():
    bills = [_bill("b1", "500000", datetime.date(2026, 10, 1)), _bill("b2", "999", datetime.date(2026, 10, 2), "draft"),
             _bill("b3", "999", datetime.date(2026, 10, 3), "cancelled")]
    s = settle(bills, [_r("advance", "850000")], TODAY)
    assert [b["id"] for b in s["bills"]] == ["b1"] and s["bills"][0]["left"] == Decimal("500000")
    assert s["advance_received"] == {"p1": Decimal("850000")}


def test_overpaying_a_bill_owes_nothing_and_the_extra_is_unapplied_never_negative():
    s = settle([_bill("b1", "100", datetime.date(2026, 11, 1))], [_r("bill", "150", "b1"), _r("on_account", "20")], TODAY)
    assert s["bills"][0]["left"] == 0 and s["bills"][0]["bucket"] is None
    assert s["unapplied"] == {"p1": Decimal("70")}


def test_per_client_most_owed_first_with_buckets():
    bills = [_bill("b1", "300", datetime.date(2026, 7, 1), client="c1"), _bill("b2", "900", datetime.date(2026, 11, 1),
             project="p2", client="c2")]
    rows = by_client(settle(bills, [_r("advance", "50", project="p2")], TODAY),
                     {"c1": {"name": "Thomas"}, "c2": {"name": "Joseph"}}, {"p1": "c1", "p2": "c2"})
    assert [(r["client"], r["outstanding"]) for r in rows] == [("Joseph", Decimal("900")), ("Thomas", Decimal("300"))]
    assert rows[1]["buckets"]["90_plus"] == Decimal("300") and rows[0]["advance_received"] == Decimal("50")
