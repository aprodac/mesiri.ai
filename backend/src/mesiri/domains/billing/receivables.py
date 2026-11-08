"""What a client still owes (END-02): pure, no I/O. Nothing here is stored; it is worked out from the bills and the
payments every time.

- A bill's **due** is what the client agreed to pay for it: the certified amount once the client's engineer has
  certified it, until then the net payable worked out when it was submitted. A draft or a withdrawn bill is never
  due.
- A bill's **outstanding** = due − payments recorded against it. **Age** = days since the bill's date.
- **Retention held** = the retention on every submitted or certified bill − retention the client has released
  (payments of kind ``retention``). It falls due when the defect period ends: the handover day + the contract's
  defect liability months.
- **Advance to receive** = the contract's mobilisation advance − advance payments recorded (never below zero).

Worked example: RA-01 net ₹11,27,160, certified ₹11,00,000, ₹6,00,000 received → ₹5,00,000 outstanding; RA-02 net
₹4,20,000 submitted, nothing received → ₹4,20,000 outstanding; total ₹9,20,000. Retention on the two bills ₹55,800
+ ₹21,000 = ₹76,800 held; handed over 15 Jan 2027 with 12 months' defect liability → due 15 Jan 2028.
"""

from __future__ import annotations

import calendar
import datetime
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from mesiri.domains.billing.ra import money
from mesiri.domains.equipment.rules import inr

_ZERO = Decimal(0)
DUE_STATUSES = ("submitted", "certified")


def bill_due(bill: Mapping[str, Any]) -> Decimal:
    """What the client owes for this bill before any payment (0 for a draft or a withdrawn bill)."""
    if bill["status"] not in DUE_STATUSES:
        return _ZERO
    if bill["status"] == "certified" and bill.get("certified_amount") is not None:
        return money(Decimal(bill["certified_amount"]))
    return money(Decimal(bill.get("net") or 0))


def add_months(day: datetime.date, months: int) -> datetime.date:
    """``day`` + ``months`` calendar months; the 31st becomes the month's last day (31 Jan + 1 = 28/29 Feb)."""
    m = day.month - 1 + months
    year, month = day.year + m // 12, m % 12 + 1
    return datetime.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def defects_end(handed_over_on: datetime.date | None, months: int | None) -> datetime.date | None:
    """The day the defect liability period ends (retention falls due), or None while either is not known."""
    if handed_over_on is None or months is None:
        return None
    return add_months(handed_over_on, int(months))


def project_receivable(bills: Iterable[Mapping[str, Any]], payments: Iterable[Mapping[str, Any]],
                       today: datetime.date, advance: Any = None, handed_over_on: datetime.date | None = None,
                       defect_months: int | None = None) -> dict[str, Any]:
    """One project's money from the client: each due bill with what was received and what is left, retention held
    and when it is due, the advance still to come, and the totals. Bills oldest first (the order to chase them)."""
    paid_by_bill: dict[Any, Decimal] = {}
    kinds = {"bill": _ZERO, "advance": _ZERO, "retention": _ZERO, "other": _ZERO}
    for p in payments:
        amount = Decimal(p["amount"])
        kinds[p["kind"]] += amount
        if p["kind"] == "bill":
            paid_by_bill[p["ra_bill_id"]] = paid_by_bill.get(p["ra_bill_id"], _ZERO) + amount
    rows = []
    retention_held = _ZERO
    for b in sorted(bills, key=lambda b: (b["bill_date"], b["number"])):
        if b["status"] not in DUE_STATUSES:
            continue
        due = bill_due(b)
        received = money(paid_by_bill.get(b["id"], _ZERO))
        retention_held += Decimal(b.get("retention") or 0)
        rows.append({"id": b["id"], "ref": b["ref"], "status": b["status"], "bill_date": b["bill_date"],
                     "due": due, "received": received, "outstanding": money(due - received),
                     "age_days": (today - b["bill_date"]).days, "retention": money(Decimal(b.get("retention") or 0))})
    retention_left = money(retention_held - kinds["retention"])
    due_on = defects_end(handed_over_on, defect_months)
    advance_left = max(money(Decimal(advance or 0) - kinds["advance"]), _ZERO)
    outstanding = money(sum((r["outstanding"] for r in rows if r["outstanding"] > 0), _ZERO))
    return {
        "bills": rows,
        "billed": money(sum((r["due"] for r in rows), _ZERO)),
        "received": money(sum(kinds.values(), _ZERO)),
        "received_on_bills": money(kinds["bill"]),
        "outstanding": outstanding,
        "oldest_days": max((r["age_days"] for r in rows if r["outstanding"] > 0), default=None),
        "retention_held": money(retention_held),
        "retention_released": money(kinds["retention"]),
        "retention_left": retention_left,
        "retention_due_on": due_on,
        "retention_due_now": bool(due_on and today >= due_on and retention_left > 0),
        "advance": money(Decimal(advance or 0)),
        "advance_received": money(kinds["advance"]),
        "advance_left": advance_left,
        "other_received": money(kinds["other"]),
    }


def payment_problem(kind: str, amount: Decimal, *, bill: Mapping[str, Any] | None = None,
                    bill_outstanding: Decimal | None = None, retention_left: Decimal | None = None,
                    advance_left: Decimal | None = None) -> str | None:
    """Why this payment can't be recorded as said, in words for the person, or None. A payment never makes a bill,
    the retention or the advance go below zero: more than is owed is a different kind of money (or a typo)."""
    if kind == "bill":
        if bill is None:
            return "Which bill was this for?"
        if bill["status"] not in DUE_STATUSES:
            return f"{bill['ref']} is {bill['status']}: only a submitted or certified bill is paid"
        if bill_outstanding is not None and amount > bill_outstanding:
            return (f"That is more than the {inr(bill_outstanding)} still due on {bill['ref']}: record the extra as "
                    "an advance or other")
    if kind == "retention" and retention_left is not None and amount > retention_left:
        return f"Only {inr(retention_left)} of retention is held on this project's bills"
    if kind == "advance" and advance_left is not None and amount > advance_left:
        return f"The contract's advance still to come is {inr(advance_left)}: record the rest as other"
    # advance_left is None when the contract names no advance: then any advance the client gives is recorded.
    return None
