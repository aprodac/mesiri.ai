"""What clients owe (NXT-03). Pure, no I/O.

A bill sent to the client (``submitted`` or ``certified``) is owed its **net payable** (gross + GST - retention -
advance recovery - TDS, stored when it was submitted, ``ra.py``). Money received settles it:

- a receipt **against the bill** settles that bill;
- a receipt **on account** settles the project's oldest open bills first (the way a client's part payment is read);
  what is left over waits for the next bill (``unapplied``);
- a **mobilisation advance** is never applied to a bill: each bill already recovers it through its own advance
  recovery, so applying it again would count it twice. It is shown apart (``advance_received``).

A bill paid beyond what it asked shows nothing owed and the extra as unapplied, never a negative balance. Age is days
since the bill's date, in the supplier ledger's buckets (0-30, 31-60, 61-90, 90+), so both sides read alike.

Worked example: RA-01 ₹11,27,160 (1 Sep), RA-02 ₹6,40,000 (1 Oct). ₹10,00,000 against RA-01 and ₹5,00,000 on account:
RA-01 is settled (₹1,27,160 of the ₹5,00,000), RA-02 has ₹2,67,160 left.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

_ZERO = Decimal(0)
BUCKETS = ((0, 30, "0_30"), (31, 60, "31_60"), (61, 90, "61_90"), (91, None, "90_plus"))
OWED_STATUSES = ("submitted", "certified")


def bucket(days: int) -> str:
    for low, high, key in BUCKETS:
        if days >= low and (high is None or days <= high):
            return key
    return "0_30"


def settle(bills: Iterable[Mapping[str, Any]], receipts: Iterable[Mapping[str, Any]],
           today: datetime.date) -> dict[str, Any]:
    """Per bill: due, received, left, age; per project: on account not used and advance received.

    ``bills``: id, project_id, bill_date, net, status. ``receipts`` (confirmed only): kind, ra_bill_id, project_id,
    amount."""
    owed = sorted((b for b in bills if b["status"] in OWED_STATUSES), key=lambda b: (b["bill_date"], b.get("number", 0)))
    direct: dict[Any, Decimal] = defaultdict(Decimal)
    on_account: dict[Any, Decimal] = defaultdict(Decimal)
    advance: dict[Any, Decimal] = defaultdict(Decimal)
    for r in receipts:
        amount = Decimal(r["amount"])
        if r["kind"] == "bill":
            direct[r["ra_bill_id"]] += amount
        elif r["kind"] == "on_account":
            on_account[r["project_id"]] += amount
        else:
            advance[r["project_id"]] += amount
    out_bills = []
    unapplied: dict[Any, Decimal] = defaultdict(Decimal)
    for b in owed:
        due = Decimal(b["net"])
        got = direct.get(b["id"], _ZERO)
        if got > due:
            unapplied[b["project_id"]] += got - due
        left = max(due - got, _ZERO)
        pool = on_account[b["project_id"]]
        used = min(pool, left)
        on_account[b["project_id"]] = pool - used
        left -= used
        days = (today - b["bill_date"]).days
        out_bills.append({**b, "due": due, "received": got + used, "on_account_applied": used, "left": left,
                          "days": days, "bucket": bucket(days) if left > 0 else None})
    for project_id, pool in on_account.items():
        unapplied[project_id] += pool
    return {"bills": out_bills, "unapplied": {p: v for p, v in unapplied.items() if v > 0},
            "advance_received": dict(advance)}


def by_client(settled: dict[str, Any], clients: Mapping[Any, Mapping[str, Any]], project_client: Mapping[Any, Any]
              ) -> list[dict[str, Any]]:
    """Per client: outstanding, the age buckets, open bills, unapplied money and advances; most owed first.

    ``project_client``: project_id -> client_id (the project's contract), for money not tied to a bill."""
    rows: dict[Any, dict[str, Any]] = {}

    def row(client_id: Any) -> dict[str, Any]:
        c = clients.get(client_id) or {}
        return rows.setdefault(client_id, {
            "client_id": client_id, "client": c.get("name") or "No client set", "outstanding": _ZERO,
            "buckets": {key: _ZERO for _, _, key in BUCKETS}, "open_bills": [], "unapplied": _ZERO,
            "advance_received": _ZERO})

    for b in settled["bills"]:
        r = row(b.get("client_id") or project_client.get(b["project_id"]))
        if b["left"] > 0:
            r["outstanding"] += b["left"]
            r["buckets"][b["bucket"]] += b["left"]
            r["open_bills"].append(b)
    for key, field in (("unapplied", "unapplied"), ("advance_received", "advance_received")):
        for project_id, amount in settled[key].items():
            if amount:
                row(project_client.get(project_id))[field] += amount
    return sorted(rows.values(), key=lambda r: (-r["outstanding"], r["client"]))
