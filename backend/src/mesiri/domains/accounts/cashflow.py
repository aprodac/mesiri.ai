"""ACC-18 / MP-06: cash flow for the coming weeks, from what the company already records. No table of its own.

Money in:

- ``client_bills``: RA bills sent to the client and not fully paid (``billing/receivables.settle``), expected
  ``client_days`` after the bill's date (the contract has no payment term yet: 30 by default, changeable on the page).
- ``to_bill``: measured work on no bill yet (``billing/bills.unbilled_lines``), as if billed today: expected
  ``client_days`` from today. Off by default on the page ("if you bill it now").

Money out:

- ``supplier_bills``: supplier and subcontractor bills not paid (``vendors/ledger``; a subcontract bill only once
  checked, never its retention), due their date + the supplier's credit days (``supplier_days`` when not set).
  Money already paid to a supplier on account is taken off that supplier's earliest bills first.
- ``delivered``: deliveries the supplier has not billed yet, due the delivery's date + credit days.
- ``orders``: what is still to come on open purchase orders, at the order's rates, due the expected date (a week
  from today when none) + credit days.
- ``wages_due``: wage sheets with something left to pay, this week (the week after the sheet ends).
- ``wages_ahead``: an estimate for each coming week with no wage sheet yet: the last four weeks' wages a week.

Anything due before today is counted in this week and marked ``overdue``; weeks start on Monday; after the last
week shown it is ``later``. Opening cash is every cash box and bank account today; with a project picked it is left
out (a bank account is the company's, not a project's).

Worked example: today Wed 18 Nov, ₹4,00,000 in the bank. RA-03 ₹6,00,000 billed 1 Nov (client 30 days) → in, week
of 30 Nov. Cement bill ₹80,000 dated 10 Nov, supplier 15 days → out, week of 23 Nov. Wages ₹1,20,000 approved for
9-15 Nov, nothing paid → out this week. Week of 16 Nov: 4,00,000 − 1,20,000 = 2,80,000; 23 Nov: 2,00,000;
30 Nov: 8,00,000.
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

_ZERO = Decimal(0)
PAISA = Decimal("0.01")

IN_KINDS = ("client_bills", "to_bill")
OUT_KINDS = ("supplier_bills", "delivered", "orders", "wages_due", "wages_ahead")
#: On unless the person turns them off; ``to_bill`` is money only if they bill now.
DEFAULT_ON = ("client_bills", "supplier_bills", "delivered", "orders", "wages_due", "wages_ahead")
WAGE_WEEKS = 4


def money(v: Decimal) -> Decimal:
    return Decimal(v).quantize(PAISA)


def week_start(day: datetime.date) -> datetime.date:
    return day - datetime.timedelta(days=day.weekday())


def place(items: Iterable[dict[str, Any]], today: datetime.date, weeks: int) -> list[dict[str, Any]]:
    """Each item's week: 0 is this week (and anything overdue), ``None`` after the last week shown."""
    first = week_start(today)
    out = []
    for it in items:
        day = it["date"]
        overdue = day < today
        index = 0 if overdue else (week_start(day) - first).days // 7
        out.append({**it, "overdue": overdue, "week": index if index < weeks else None})
    return out


def totals(items: Iterable[Mapping[str, Any]], today: datetime.date, weeks: int, opening: Decimal | None,
           kinds: Iterable[str] = DEFAULT_ON) -> dict[str, Any]:
    """Per week: in, out, net and (with opening cash) the balance at the week's end; then ``later``."""
    on = set(kinds)
    first = week_start(today)
    rows = [{"start": first + datetime.timedelta(days=7 * i), "in": _ZERO, "out": _ZERO} for i in range(weeks)]
    later = {"in": _ZERO, "out": _ZERO}
    for it in items:
        if it["kind"] not in on:
            continue
        side = "in" if it["kind"] in IN_KINDS else "out"
        target = rows[it["week"]] if it["week"] is not None else later
        target[side] += Decimal(it["amount"])
    balance = opening
    lowest: tuple[Decimal, datetime.date] | None = None
    for r in rows:
        r["net"] = r["in"] - r["out"]
        if balance is not None:
            balance += r["net"]
            r["balance"] = balance
            if lowest is None or balance < lowest[0]:
                lowest = (balance, r["start"])
    return {"weeks": rows, "later": later, "lowest": {"balance": lowest[0], "week": lowest[1]} if lowest else None,
            "first_short": next((r["start"] for r in rows if r.get("balance") is not None and r["balance"] < 0), None)}


def take_off_advances(bills: list[dict[str, Any]], advance: Decimal) -> list[dict[str, Any]]:
    """Money paid ahead to a supplier pays their earliest bills first; what it covers is not owed again."""
    left = Decimal(advance)
    out = []
    for b in sorted(bills, key=lambda b: b["date"]):
        amount = Decimal(b["amount"])
        used = min(left, amount)
        left -= used
        if amount - used > 0:
            out.append({**b, "amount": amount - used})
    return out


def wage_estimate(sheets: Iterable[Mapping[str, Any]], today: datetime.date) -> Decimal:
    """A week's wages, from the sheets that ended in the last four weeks (all of them, paid or not)."""
    since = today - datetime.timedelta(days=7 * WAGE_WEEKS)
    total = sum((Decimal(s["net"]) for s in sheets if since <= s["period_to"] < today), _ZERO)
    return money(total / WAGE_WEEKS)


def _iso(d: Any) -> datetime.date:
    return d if isinstance(d, datetime.date) else datetime.date.fromisoformat(str(d)[:10])


def _to_bill_title(lines: list[dict]) -> str:
    """Work on BOQ lines, or (FB-01, lump sum) payment stages reached, not billed yet."""
    n = len(lines)
    if lines and lines[0]["line"].get("payment_stage_id") is not None:
        return f"{n} payment stage{'s' if n != 1 else ''} reached, not billed"
    return f"Work done on {n} BOQ line{'s' if n != 1 else ''}, not billed"


async def gather(conn: AsyncConnection, org: uuid.UUID, project_ids: set | None, today: datetime.date, *,
                 client_days: int, supplier_days: int, weeks: int) -> list[dict[str, Any]]:
    """Every expected payment in or out, each with kind, date, amount, who, project and a link to its page."""
    from mesiri.domains.billing import bills as bill_store
    from mesiri.domains.billing import ra, receipts
    from mesiri.domains.procurement import orders as order_store
    from mesiri.domains.vendors import ledger
    from mesiri.domains.workforce import pay_store

    items: list[dict[str, Any]] = []
    days = datetime.timedelta

    # In: client bills still owed.
    from mesiri.domains.billing import contracts

    owed = await receipts.owed(conn, org, project_ids, today)
    client_name = {c["id"]: c.get("name") for c in await contracts.list_clients(conn, org)}
    for b in owed["bills"]:
        if Decimal(b["left"]) <= 0:
            continue
        items.append({"kind": "client_bills", "date": _iso(b["bill_date"]) + days(days=client_days),
                      "amount": money(b["left"]), "title": b.get("ref") or "RA bill",
                      "who": client_name.get(b.get("client_id")),
                      "project_id": str(b["project_id"]), "project": b.get("project"),
                      "link": f"/billing/ra-bills?bill={b['id']}&project={b['project_id']}"})

    # In: work done, on no bill yet (if billed today).
    rows = await bill_store.billable_projects(conn, org)
    for p in rows:
        if project_ids is not None and p.id not in project_ids:
            continue
        lines = await bill_store.unbilled_lines(conn, org, p.id)
        amount = sum((ra.line_amount(ln["quantity"], ln["line"]["client_rate"]) for ln in lines), _ZERO)
        if amount > 0:
            items.append({"kind": "to_bill", "date": today + days(days=client_days), "amount": money(amount),
                          "title": _to_bill_title(lines),
                          "who": None, "project_id": str(p.id), "project": p.name,
                          "link": f"/billing/ra-bills?project={p.id}"})

    # Out: suppliers and subcontractors (bills, then deliveries not billed), less money paid ahead.
    entries, state = await ledger.fetch_entries(conn, org, vendor_id=None, projects=project_ids)
    for v in state["vendors"].values():
        s = ledger.summarise(v, entries, state, today)
        credit = v.get("credit_days")
        lag = days(days=credit if credit is not None else supplier_days)
        mine: list[dict[str, Any]] = []
        for b in s["open_bills"]:
            if Decimal(b["payable"]) <= 0:
                continue
            mine.append({"kind": "supplier_bills", "date": _iso(b["date"]) + lag, "amount": Decimal(b["payable"]),
                         "title": b.get("bill_number") and f"Bill {b['bill_number']}" or b.get("description") or "Bill",
                         "who": v["name"], "project_id": b.get("project_id"), "project": b.get("project"),
                         "link": f"/finance/vendors/{v['id']}"})
        for e in entries:
            if e["vendor_id"] == v["id"] and e["kind"] == "delivery" and Decimal(e["owe"]) > 0:
                mine.append({"kind": "delivered", "date": e["date"] + lag, "amount": Decimal(e["owe"]),
                             "title": e["title"], "who": v["name"],
                             "project_id": str(e["project_id"]) if e["project_id"] else None, "project": e["project"],
                             "link": f"/finance/vendors/{v['id']}"})
        for it in take_off_advances(mine, Decimal(s["advance_left"])):
            items.append({**it, "amount": money(it["amount"]), "assumed": credit is None})

    # Out: what is still to come on open orders.
    credit_of = {vid: v.get("credit_days") for vid, v in state["vendors"].items()}
    all_orders = await order_store.fetch_orders(conn, org, project_ids=project_ids)
    for o in order_store.describe(all_orders, today=today, with_money=True, all_orders=all_orders):
        if o["status"] not in ("open", "part"):
            continue
        left = Decimal(o["value"] or 0) - Decimal(o["value_received"] or 0)
        if left <= 0:
            continue
        credit = credit_of.get(uuid.UUID(o["vendor_id"]))
        arrives = _iso(o["expected_date"]) if o["expected_date"] else today + days(days=7)
        items.append({"kind": "orders", "date": max(arrives, today) + days(days=credit if credit is not None else supplier_days),
                      "amount": money(left), "title": o["ref"], "who": o["vendor_name"], "project_id": o["project_id"],
                      "project": o["project_name"], "link": f"/procurement/orders?id={o['id']}",
                      "assumed": credit is None or not o["expected_date"] or not o["value_complete"]})

    # Out: wages owed on sheets, then an estimate for the weeks with no sheet yet.
    sheets = await pay_store.list_sheets(conn, org, project_ids)
    by_project: dict[Any, list] = defaultdict(list)
    for sh in sheets:
        by_project[(sh["project_id"], sh["project_name"])].append(sh)
        due = Decimal(sh["net"]) - Decimal(sh["paid"])
        if due <= 0:
            continue
        place_on = max(_iso(sh["period_to"]) + days(days=1), today) if _iso(sh["period_to"]) >= today - days(days=7) \
            else _iso(sh["period_to"]) + days(days=1)
        items.append({"kind": "wages_due", "date": place_on, "amount": money(due),
                      "title": f"Wages {sh['period_from']:%d %b}–{sh['period_to']:%d %b}"
                               + (" (not approved)" if sh["status"] != "approved" else ""),
                      "who": sh.get("site_name"), "project_id": str(sh["project_id"]), "project": sh["project_name"],
                      "link": f"/labour/wages?{'at=' + str(sh['site_id']) + '&' if sh['site_id'] else ''}week={sh['period_from']}"})
    first = week_start(today)
    for (pid, pname), mine in by_project.items():
        per_week = wage_estimate(mine, today)
        if per_week <= 0:
            continue
        covered = {week_start(_iso(sh["period_to"])) for sh in mine}
        for i in range(weeks):
            start = first + days(days=7 * i)
            if start in covered:
                continue
            items.append({"kind": "wages_ahead", "date": max(start + days(days=6), today), "amount": per_week,
                          "title": "Wages (estimate: last 4 weeks)", "who": None, "project_id": str(pid),
                          "project": pname, "link": "/labour/wages", "assumed": True})
    for it in items:
        it.setdefault("assumed", False)
    return items


async def opening_cash(conn: AsyncConnection, org: uuid.UUID) -> tuple[Decimal, list[dict[str, Any]]]:
    """Every active cash box and bank account with its balance today, and their total."""
    from mesiri.infrastructure.postgres.repositories.finance import PostgresMoneyAccountRepository

    repo = PostgresMoneyAccountRepository(conn)
    out = []
    for acc in await repo.list_accounts(org, account_type=None, status="active"):
        try:
            balance = Decimal(await repo.get_balance(org, acc.id))
        except Exception:  # noqa: BLE001 -- the account list's own fallback (finance/router._account_response)
            balance = Decimal(acc.opening_balance or 0)
        out.append({"id": str(acc.id), "name": acc.name, "type": acc.account_type, "balance": money(balance)})
    return money(sum((a["balance"] for a in out), _ZERO)), out
