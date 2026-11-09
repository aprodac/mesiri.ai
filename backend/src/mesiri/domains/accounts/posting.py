"""ACC-04: the posting rules. Pure, no I/O: a source record in, balanced journal entries out.

One function per source kind, the rule table of docs/architecture/accounts-posting.md. The sweep (``sweep.py``) reads
the records, resolves the ledgers and writes what these return. Ledgers are named by reference, never by id:

- ``("code", "input_gst")``: a seeded ledger (``chart.LEDGERS``);
- ``("link", "vendor", <id>)``: the ledger linked to a record (supplier, client, money account, expense category,
  member of staff).

**Bank and cash come from the money movements** (``money_transactions``), the same rows Finance › Money adds up, so
an account's balance in the books is its balance in Finance, by construction. The other side of each movement is
what it paid or received: the supplier or staff member a payment paid, the client a receipt came from, the account a
transfer came from, "Funds introduced" for money put in, "Money balance adjustments" for an adjustment.

**What is owed comes from the records**: a confirmed expense is owed to its supplier (or to the member of staff who
paid it from their own pocket, or "Expenses payable"), net of the GST the company can claim (D-CC8, the cost rule);
an RA bill sent is owed by the client. A subcontract bill is an expense (gross), its TDS a payment from the TDS
payable account, its advance recovery an applied advance (no money, nothing posted: the supplier's balance already
holds the advance), its retention what stays owed: the supplier ledger's terms exactly.

**Before a supplier's opening date** (``vendors.opening_balance_date``) their opening balance stands for everything
owed: their bills and payments of earlier dates post to "Opening balance difference" instead of the supplier, so the
supplier's balance is the supplier ledger's and the bank still ties.

Every entry balances; a line of zero is dropped; a negative amount goes to the other side.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

#: Bumped when a rule changes, so every source is re-posted by the next sweep.
RULES_VERSION = "1"

_C = Decimal("0.01")
_ZERO = Decimal(0)
STAFF_PAID = frozenset({"reimbursable", "reimbursed"})

Ref = tuple


def code(key: str) -> Ref:
    return ("code", key)


def link(kind: str, record_id: Any) -> Ref:
    return ("link", kind, str(record_id))


def money(v: Any) -> Decimal:
    return Decimal(v or 0).quantize(_C, rounding=ROUND_HALF_UP)


def line(ledger: Ref, amount: Any, debit: bool, *, project_id: Any = None, site_id: Any = None,
         cost_centre: str | None = None) -> dict[str, Any]:
    amount = money(amount)
    if amount < 0:
        amount, debit = -amount, not debit
    return {"ledger": ledger, "debit": amount if debit else _ZERO, "credit": _ZERO if debit else amount,
            "project_id": str(project_id) if project_id else None, "site_id": str(site_id) if site_id else None,
            "cost_centre": cost_centre}


def entry(part: str, day: datetime.date, voucher_type: str, narration: str, lines: list[dict[str, Any]],
          project_id: Any = None) -> dict[str, Any]:
    kept = [ln for ln in lines if ln["debit"] or ln["credit"]]
    return {"part": part, "date": day, "voucher_type": voucher_type, "narration": narration,
            "project_id": str(project_id) if project_id else None, "lines": kept}


def balanced(e: dict[str, Any]) -> bool:
    return sum((ln["debit"] for ln in e["lines"]), _ZERO) == sum((ln["credit"] for ln in e["lines"]), _ZERO)


def reverse(e: dict[str, Any], part: str, day: datetime.date, narration: str) -> dict[str, Any]:
    """The same lines on the other side, on another day."""
    lines = [{**ln, "debit": ln["credit"], "credit": ln["debit"]} for ln in e["lines"]]
    return {**e, "part": part, "date": day, "narration": narration, "lines": lines}


def fingerprint(entries: list[dict[str, Any]]) -> str:
    """What was posted for a source, so the sweep can tell when the record changed."""
    def plain(x: Any) -> Any:
        if isinstance(x, dict):
            return {k: plain(v) for k, v in sorted(x.items())}
        if isinstance(x, (list, tuple)):
            return [plain(v) for v in x]
        return str(x) if x is not None else None
    raw = json.dumps([RULES_VERSION, plain(entries)], sort_keys=True)
    return hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()


# --- who is owed ---------------------------------------------------------------------------------------------------

def party(vendor_id: Any, payment_status: str | None, staff_id: Any, day: datetime.date | None = None,
          vendor_start: datetime.date | None = None) -> Ref:
    """Who an expense is owed to, and so who its payments pay (the supplier ledger's rule, CC-09): the member of staff
    who paid it from their own pocket; else the supplier (before their opening date: the opening balance difference);
    else "Expenses payable"."""
    if (payment_status or "").lower() in STAFF_PAID and staff_id:
        return link("staff", staff_id)
    if vendor_id:
        if vendor_start is not None and day is not None and day < vendor_start:
            return code("opening_difference")
        return link("vendor", vendor_id)
    return code("expenses_payable")


# --- rules ---------------------------------------------------------------------------------------------------------

def expense_entries(e: dict[str, Any]) -> list[dict[str, Any]]:
    """A confirmed expense: Dr its category (less claimable GST) and Input GST; Cr who is owed it.

    ``e``: id, number, date, amount, claimable_gst, category_id, cost_centre, vendor_id, payment_status, staff_id,
    vendor_start, project_id, site_id, words (narration)."""
    amount = money(e["amount"])
    if amount <= 0:
        return []
    gst = money(e.get("claimable_gst"))
    where = {"project_id": e.get("project_id"), "site_id": e.get("site_id")}
    owed_to = party(e.get("vendor_id"), e.get("payment_status"), e.get("staff_id"), e["date"], e.get("vendor_start"))
    lines = [line(link("expense_category", e["category_id"]), amount - gst, True, cost_centre=e.get("cost_centre"),
                  **where),
             line(code("input_gst"), gst, True, **where),
             line(owed_to, amount, False, **where)]
    kind = "purchase" if e.get("vendor_id") else "journal"
    return [entry("main", e["date"], kind, e.get("words") or "Expense", lines, e.get("project_id"))]


def money_entries(tx: dict[str, Any], counter: dict[str, Any] | None) -> list[dict[str, Any]]:
    """A money movement: the account(s) it moved, against ``counter`` (the ledger on the other side, with its project,
    site and words), worked out by the sweep from what the movement was for. A transfer needs no counter.

    ``tx``: id, type, amount, date, from_account_id, to_account_id, from_project_id, from_site_id, to_project_id,
    to_site_id, description."""
    amount = money(tx["amount"])
    if amount <= 0:
        return []
    frm, to = tx.get("from_account_id"), tx.get("to_account_id")

    def acct(side: str) -> dict[str, Any]:
        return {"project_id": tx.get(f"{side}_project_id"), "site_id": tx.get(f"{side}_site_id")}

    if frm and to:
        lines = [line(link("money_account", to), amount, True, **acct("to")),
                 line(link("money_account", frm), amount, False, **acct("from"))]
        return [entry("main", tx["date"], "contra", tx.get("description") or "Transfer", lines,
                      tx.get("to_project_id") or tx.get("from_project_id"))]
    if counter is None:
        return []
    other = {"project_id": counter.get("project_id"), "site_id": counter.get("site_id")}
    if to:  # money in
        lines = [line(link("money_account", to), amount, True, **(acct("to") if not other["project_id"] else
                                                               {**acct("to"), "project_id": other["project_id"]})),
                 line(counter["ledger"], amount, False, **other)]
        kind = counter.get("voucher_type") or "receipt"
    else:  # money out
        lines = [line(counter["ledger"], amount, True, **other),
                 line(link("money_account", frm), amount, False, **(acct("from") if not other["project_id"] else
                                                                    {**acct("from"), "project_id": other["project_id"]}))]
        kind = counter.get("voucher_type") or "payment"
    words = " · ".join(x for x in (counter.get("words"), tx.get("description")) if x) or "Money movement"
    return [entry("main", tx["date"], kind, words, lines, other["project_id"])]


def ra_bill_entries(b: dict[str, Any]) -> list[dict[str, Any]]:
    """An RA bill sent (submitted or certified): Dr the client its net, TDS receivable, Retention receivable,
    Mobilisation advance received (the recovery); Cr Contract revenue (gross) and Output GST. Gross + GST = net + TDS +
    retention + recovery, so it balances; a stored net that does not (an older bill) puts the rounding on Round off.

    ``b``: id, ref, date, status, client_id, gross, gst, net, tds, retention, advance_recovery, project_id, words."""
    if b.get("status") not in ("submitted", "certified"):
        return []
    p = {k: money(b.get(k)) for k in ("gross", "gst", "net", "tds", "retention", "advance_recovery")}
    if p["gross"] <= 0:
        return []
    where = {"project_id": b.get("project_id")}
    client = link("client", b["client_id"]) if b.get("client_id") else code("no_client")
    lines = [line(client, p["net"], True, **where),
             line(code("tds_receivable"), p["tds"], True, **where),
             line(code("retention_receivable"), p["retention"], True, **where),
             line(code("advance_received"), p["advance_recovery"], True, **where),
             line(code("contract_revenue"), p["gross"], False, **where),
             line(code("output_gst"), p["gst"], False, **where)]
    gap = (p["gross"] + p["gst"]) - (p["net"] + p["tds"] + p["retention"] + p["advance_recovery"])
    if gap:
        lines.append(line(code("round_off"), gap, True, **where))
    return [entry("main", b["date"], "sales", b.get("words") or f"{b['ref']} running bill", lines, b.get("project_id"))]


def opening_account_entries(a: dict[str, Any]) -> list[dict[str, Any]]:
    """A money account's opening balance: Dr the account, Cr Opening balance difference (a negative: the other way).

    ``a``: id, name, opening_balance, opening_balance_date, project_id, site_id."""
    amount = money(a.get("opening_balance"))
    if not amount or not a.get("opening_balance_date"):
        return []
    where = {"project_id": a.get("project_id"), "site_id": a.get("site_id")}
    lines = [line(link("money_account", a["id"]), amount, True, **where),
             line(code("opening_difference"), amount, False, **where)]
    return [entry("main", a["opening_balance_date"], "journal", f"Opening balance · {a.get('name') or 'account'}",
                  lines, a.get("project_id"))]


def opening_vendor_entries(v: dict[str, Any]) -> list[dict[str, Any]]:
    """A supplier's opening balance (what was owed before Mesiri; negative: paid ahead): Cr the supplier, Dr Opening
    balance difference."""
    amount = money(v.get("opening_balance"))
    if not amount or not v.get("opening_balance_date"):
        return []
    lines = [line(code("opening_difference"), amount, True),
             line(link("vendor", v["id"]), amount, False)]
    return [entry("main", v["opening_balance_date"], "journal", f"Opening balance · {v.get('name') or 'supplier'}",
                  lines)]
