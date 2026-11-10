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


def labour_accrual_entries(day: datetime.date, project_id: Any, site_id: Any, amount: Any, words: str) -> list[dict[str, Any]]:
    """LW-06: a month's attendance at its wage on a site: Dr Labour wages (the labour cost, as cost control counts it),
    Cr Wages payable. Paying the wages (a money movement) clears the payable."""
    amount = money(amount)
    if amount <= 0:
        return []
    lines = [line(code("labour_wages"), amount, True, project_id=project_id, site_id=site_id, cost_centre="labour"),
             line(code("wages_payable"), amount, False, project_id=project_id, site_id=site_id)]
    return [entry("main", day, "journal", words, lines, project_id)]


def wage_row_entries(day: datetime.date, project_id: Any, site_id: Any, payee: str, recovered: Any = 0,
                     overtime: Any = 0, deducted: Any = 0) -> list[dict[str, Any]]:
    """LW-06: what an approved wage sheet row adds to the attendance accrual, so Wages payable ends at what is still
    owed: overtime earned (Dr Labour wages, Cr Wages payable), deductions kept back (Dr Wages payable, Cr Labour wages:
    the cost is that much less) and the advance taken back (Dr Wages payable, Cr Advances to labour)."""
    at = {"project_id": project_id, "site_id": site_id}
    out = []
    if money(overtime) > 0:
        out.append(entry("overtime", day, "journal", f"Overtime · {payee}", [
            line(code("labour_wages"), overtime, True, cost_centre="labour", **at),
            line(code("wages_payable"), overtime, False, **at)], project_id))
    if money(deducted) > 0:
        out.append(entry("deductions", day, "journal", f"Deducted from {payee}'s wages", [
            line(code("wages_payable"), deducted, True, **at),
            line(code("labour_wages"), deducted, False, cost_centre="labour", **at)], project_id))
    if money(recovered) > 0:
        out.append(entry("main", day, "journal", f"Advance taken back from {payee}'s wages", [
            line(code("wages_payable"), recovered, True, **at),
            line(code("labour_advances"), recovered, False, **at)], project_id))
    return out


def overhead_entries(month_end: datetime.date, head_office: Decimal, shares: dict[str, Decimal],
                     basis: str, from_project: Any = None) -> list[dict[str, Any]]:
    """ACC-23: a month's head-office costs shared over the projects by ``basis`` (their cost or their billing that
    month): Dr "Head office overheads allocated" on each project, Cr the same ledger on the head-office project (or no
    project). Nil for the company; each project's P&L carries its share. The last project takes the rounding."""
    head_office = money(head_office)
    weights = {p: Decimal(w) for p, w in shares.items() if Decimal(w) > 0}
    total = sum(weights.values(), _ZERO)
    if head_office <= 0 or total <= 0:
        return []
    lines, given = [], _ZERO
    ordered = sorted(weights)
    for i, p in enumerate(ordered):
        part = head_office - given if i == len(ordered) - 1 else money(head_office * weights[p] / total)
        given += part
        lines.append(line(code("overheads_allocated"), part, True, project_id=p))
    lines.append(line(code("overheads_allocated"), head_office, False, project_id=from_project))
    words = f"Head office costs of {month_end:%B %Y} shared over projects by their {basis}"
    return [entry("main", month_end, "journal", words, lines)]


def ledger_id(value: Any) -> Ref:
    """A ledger named by its id: a line the accountant chose (a manual voucher, a bank line booked)."""
    return ("id", str(value))


def voucher_entries(v: dict[str, Any]) -> list[dict[str, Any]]:
    """ACC-12: a manual voucher posted as it was typed (a cancelled one posts nothing, so the sweep takes it out).

    ``v``: id, date, status, narration, lines [{ledger_id, debit, credit, project_id, site_id, cost_centre}]."""
    if v.get("status") != "posted":
        return []
    lines = []
    for ln in v["lines"]:
        debit = money(ln.get("debit"))
        lines.append(line(ledger_id(ln["ledger_id"]), debit if debit else money(ln.get("credit")), bool(debit),
                          project_id=ln.get("project_id"), site_id=ln.get("site_id"), cost_centre=ln.get("cost_centre")))
    projects = {ln["project_id"] for ln in lines}
    return [entry("main", v["date"], "journal", v["narration"], lines, next(iter(projects)) if len(projects) == 1 else None)]


def accrual_entries(month_end: datetime.date, parts: list[dict[str, Any]], words: str) -> list[dict[str, Any]]:
    """ACC-15 (D-ACC5): deliveries on site at a month's end whose bill has not come: Dr "Materials received, bill
    awaited" (the month's cost, as cost control counts a delivery), Cr "Goods received not invoiced", per project and
    site; reversed on the 1st of the next month, when the bill (or the next month's accrual) takes over.

    ``parts``: [{project_id, site_id, amount}]."""
    lines = []
    for p in parts:
        at = {"project_id": p.get("project_id"), "site_id": p.get("site_id")}
        lines += [line(code("materials_unbilled"), p["amount"], True, cost_centre="materials", **at),
                  line(code("grni"), p["amount"], False, **at)]
    main = entry("main", month_end, "journal", words, lines)
    if not main["lines"]:
        return []
    nxt = month_end + datetime.timedelta(days=1)
    return [main, reverse(main, "reverse", nxt, f"Reversed: {words}")]


def asset_entries(a: dict[str, Any], years: list[dict[str, Any]], ledger: str) -> list[dict[str, Any]]:
    """ACC-16: a fixed asset in the books. ``years``: its depreciation schedule (``depreciation.schedule``); ``ledger``:
    its class's ledger code.

    - **Cost**: bought through an expense: Dr the class ledger, Cr the expense's category (the bill stays as it is,
      only its ledger changes from cost to asset), on the bill's date; owned before the books: Dr the class ledger,
      Cr "Opening balance difference", at its value at the start of that year.
    - **Depreciation**, each year once it is over: Dr Depreciation, Cr the class ledger.
    - **Sold or scrapped**: Cr the class ledger its book value, Dr "Assets sold, money to receive" what it fetched,
      the difference to "Loss or gain on assets sold".

    ``a``: id, name, cost, opening_depreciation, acquired_on, books_from, expense_id, expense_date,
    expense_category_id, project_id, site_id, disposed_on, disposal_value."""
    at = {"project_id": a.get("project_id"), "site_id": a.get("site_id")}
    out = []
    if a.get("expense_id") and a.get("expense_category_id"):
        out.append(entry("cost", a["expense_date"], "journal", f"{a['name']} bought: to fixed assets", [
            line(code(ledger), a["cost"], True, **at),
            line(link("expense_category", a["expense_category_id"]), a["cost"], False, **at)], a.get("project_id")))
    else:
        opening = money(a["cost"]) - money(a.get("opening_depreciation"))
        out.append(entry("cost", a.get("books_from") or a["acquired_on"], "journal",
                         f"Opening value · {a['name']}", [
                             line(code(ledger), opening, True, **at),
                             line(code("opening_difference"), opening, False, **at)], a.get("project_id")))
    for y in years:
        if not y["posted"]:
            continue
        out.append(entry(f"dep:{y['financial_year']}", y["post_on"], "journal",
                         f"Depreciation {y['financial_year']} · {a['name']}", [
                             line(code("depreciation"), y["depreciation"], True, **at),
                             line(code(ledger), y["depreciation"], False, **at)], a.get("project_id")))
    if a.get("disposed_on") is not None:
        last = years[-1] if years and years[-1].get("disposed_on") else None
        book = last["closing"] if last else money(a["cost"]) - money(a.get("opening_depreciation"))
        sold = money(a.get("disposal_value"))
        out.append(entry("disposal", a["disposed_on"], "journal", f"{a['name']} sold or scrapped", [
            line(code(ledger), book, False, **at),
            line(code("asset_sale_receivable"), sold, True, **at),
            line(code("asset_disposal"), book - sold, True, **at)], a.get("project_id")))
    return [e for e in out if e["lines"]]
