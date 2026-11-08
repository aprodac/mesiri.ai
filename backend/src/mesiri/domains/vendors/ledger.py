"""CC-09 supplier ledger: what the company owes each supplier, line by line, with a running balance.

A read model over what already exists (cost-control-plan D-CC3), no ledger table:

- **Opening balance** (``vendors.opening_balance`` on ``opening_balance_date``): what was owed before Mesiri (negative:
  paid ahead). Its date is where the ledger starts: older bills, deliveries and payments are inside that figure and are
  not listed again, so a company that kept no payments in Mesiri starts clean from the day it says.
- **Delivered, not billed** (+): a priced delivery from this supplier with no bill yet (``rates.BILLED_SQL``). When the
  bill comes it replaces the delivery (the delivery is "on the bill"), so nothing is owed twice.
- **Bill** (+): a confirmed expense with this supplier. A bill paid by a member of staff from their own pocket
  (``reimbursable``) is settled with the supplier and owed to the staff member instead: the same line is shown as
  paid by them.
- **Payment** (−): money paid from an account (``expense_payments`` with money: a bill payment, or an on-account
  payment, CC-10). Parts of an on-account payment applied to bills (``advance_id``) move no money and are not listed
  again; they only decide which bills are paid.

Balance = what we owe them; below zero, they hold our money (an advance).
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.procurement.orders import ref as order_ref
from mesiri.domains.procurement.rates import BILLED_SQL

_C = Decimal("0.01")
#: Age buckets for unpaid bills and unbilled deliveries, in days since their date.
BUCKETS = ((0, 30, "0_30"), (31, 60, "31_60"), (61, 90, "61_90"), (91, None, "90_plus"))
_KIND_ORDER = {"opening": 0, "delivery": 1, "bill": 2, "staff_paid": 3, "payment": 4}


def money(v: Decimal | int | None) -> str:
    return str(Decimal(v or 0).quantize(_C, rounding=ROUND_HALF_UP))


def _qty(v) -> str:
    return format(Decimal(v).normalize(), "f")


def _bucket(days: int) -> str:
    for low, high, key in BUCKETS:
        if days >= low and (high is None or days <= high):
            return key
    return "0_30"


async def vendors_of(conn: AsyncConnection, org: uuid.UUID, vendor_id: uuid.UUID | None = None) -> dict:
    sql = ("SELECT id, name, code, status, phone, gstin, address, kind, credit_days, opening_balance, "
           "opening_balance_date, contact_person, notes FROM vendors WHERE organization_id = :org")
    params: dict = {"org": org}
    if vendor_id is not None:
        sql += " AND id = :v"
        params["v"] = vendor_id
    return {r["id"]: dict(r) for r in (await conn.execute(text(sql), params)).mappings()}


def _scope(sql: str, params: dict, column: str, projects: set[uuid.UUID] | None) -> str:
    if projects is None:
        return sql
    params["projects"] = list(projects)
    return sql + f" AND {column} = ANY(:projects)"


async def fetch_entries(
    conn: AsyncConnection, org: uuid.UUID, *, vendor_id: uuid.UUID | None, projects: set[uuid.UUID] | None,
    until: datetime.date | None = None,
) -> tuple[list[dict], dict]:
    """Every ledger line (all vendors when ``vendor_id`` is None), oldest first, plus the bill and advance state.

    ``projects`` None: the whole company (with opening balances and payments not tied to a project). Otherwise only
    lines of those projects: a project's view of the account, without the company-level opening balance.
    Returns ``(entries, state)``; ``state`` holds ``bills`` (id -> amount, paid, left) and ``advances``.
    """
    vfilter = " AND {col} = :v" if vendor_id is not None else " AND {col} IS NOT NULL"
    base: dict = {"org": org}
    if vendor_id is not None:
        base["v"] = vendor_id
    if until is not None:
        base["until"] = until

    # Deliveries with a price, not billed.
    p = dict(base)
    sql = (
        "SELECT r.id, r.vendor_id, r.occurred_date AS d, r.created_at, r.quantity, r.unit_cost, r.total_cost, "
        "mc.name AS material, COALESCE(u.code, r.unit) AS unit, r.project_id, pr.name AS project, s.name AS site, "
        "po.id AS order_id, po.number AS order_number, r.invoice_id "
        "FROM material_receipts r JOIN materials_catalog mc ON mc.id = r.material_id "
        "LEFT JOIN units_of_measure u ON u.id = mc.default_unit_id "
        "LEFT JOIN projects pr ON pr.id = r.project_id LEFT JOIN sites s ON s.id = r.site_id "
        "LEFT JOIN purchase_order_lines pol ON pol.id = r.purchase_order_line_id "
        "LEFT JOIN purchase_orders po ON po.id = pol.purchase_order_id "
        "WHERE r.organization_id = :org" + vfilter.format(col="r.vendor_id") +
        " AND (r.unit_cost IS NOT NULL OR r.total_cost IS NOT NULL) AND r.quantity > 0 "
        "AND r.movement_reason = 'RECEIVED' AND r.transfer_id IS NULL AND r.reverses_movement_id IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM material_usage x WHERE x.reverses_movement_id = r.id) "
        "AND NOT EXISTS (SELECT 1 FROM material_receipts y WHERE y.reverses_movement_id = r.id) "
        "AND NOT " + BILLED_SQL
    )
    if until is not None:
        sql += " AND r.occurred_date <= :until"
    sql = _scope(sql, p, "r.project_id", projects)
    deliveries = (await conn.execute(text(sql), p)).mappings().all()

    # Bills: confirmed expenses with a vendor.
    p = dict(base)
    sql = (
        "SELECT e.id, e.vendor_id, e.occurred_date AS d, e.created_at, e.amount, e.expense_number, e.description, "
        "e.payment_status, e.tax_amount, e.project_id, pr.name AS project, s.name AS site, c.name AS category, "
        "cb.full_name AS recorded_by, "
        "(SELECT string_agg(DISTINCT i.invoice_number, ', ') FROM material_invoices i WHERE i.expense_id = e.id) "
        "AS bill_number, "
        "(SELECT COUNT(*) FROM material_receipts mr JOIN material_invoices mi ON mi.id = mr.invoice_id "
        " WHERE mi.expense_id = e.id) AS deliveries, "
        # PRC-11: deliveries on this bill whose quantity or rate differs from what the bill said.
        "(SELECT COUNT(*) FROM material_receipts mr JOIN material_invoices mi ON mi.id = mr.invoice_id "
        " WHERE mi.expense_id = e.id AND ((mr.billed_quantity IS NOT NULL AND mr.billed_quantity <> mr.quantity) "
        " OR (mr.billed_rate IS NOT NULL AND mr.unit_cost IS NOT NULL AND mr.billed_rate <> mr.unit_cost))) AS mismatches "
        "FROM expenses e LEFT JOIN projects pr ON pr.id = e.project_id LEFT JOIN sites s ON s.id = e.site_id "
        "LEFT JOIN expense_categories c ON c.id = e.category_id LEFT JOIN users cb ON cb.id = e.created_by "
        "WHERE e.organization_id = :org AND e.workflow_status = 'confirmed'" + vfilter.format(col="e.vendor_id")
    )
    if until is not None:
        sql += " AND e.occurred_date <= :until"
    sql = _scope(sql, p, "e.project_id", projects)
    bills = (await conn.execute(text(sql), p)).mappings().all()

    # Payments (confirmed), with or without money of their own.
    p = dict(base)
    sql = (
        "SELECT p.id, COALESCE(p.vendor_id, e.vendor_id) AS vendor_id, p.expense_id, p.advance_id, p.paid_date AS d, "
        "p.created_at, p.amount, p.reference_number, p.payment_method, a.id AS account_id, a.name AS account, "
        "a.account_type, COALESCE(p.project_id, e.project_id) AS project_id, pr.name AS project, "
        "e.expense_number, u.full_name AS recorded_by "
        "FROM expense_payments p LEFT JOIN expenses e ON e.id = p.expense_id "
        "JOIN money_accounts a ON a.id = p.account_id LEFT JOIN projects pr ON pr.id = COALESCE(p.project_id, e.project_id) "
        "LEFT JOIN users u ON u.id = p.created_by "
        "WHERE p.organization_id = :org AND p.status = 'confirmed'" + vfilter.format(col="COALESCE(p.vendor_id, e.vendor_id)")
    )
    if until is not None:
        sql += " AND p.paid_date <= :until"
    sql = _scope(sql, p, "COALESCE(p.project_id, e.project_id)", projects)
    payments = (await conn.execute(text(sql), p)).mappings().all()

    vendors = await vendors_of(conn, org, vendor_id)
    start = {vid: v["opening_balance_date"] for vid, v in vendors.items() if v["opening_balance_date"]}

    def after_start(vid, d) -> bool:
        s = start.get(vid)
        return s is None or d >= s

    entries: list[dict] = []
    if projects is None:
        for vid, v in vendors.items():
            ob = Decimal(v["opening_balance"] or 0)
            if v["opening_balance_date"] and ob and (until is None or v["opening_balance_date"] <= until):
                entries.append({
                    "id": f"opening:{vid}", "vendor_id": vid, "date": v["opening_balance_date"], "created_at": None,
                    "kind": "opening", "title": "Opening balance",
                    "detail": "Owed before Mesiri" if ob > 0 else "Paid ahead before Mesiri",
                    "owe": max(ob, Decimal(0)), "paid": max(-ob, Decimal(0)), "project_id": None, "project": None,
                    "site": None, "ref": None, "links": {},
                })

    for r in deliveries:
        if not after_start(r["vendor_id"], r["d"]):
            continue
        amount = Decimal(r["total_cost"]) if r["total_cost"] is not None else Decimal(r["unit_cost"]) * Decimal(r["quantity"])
        rate = f" @ ₹{money(r['unit_cost'])}" if r["unit_cost"] is not None else ""
        entries.append({
            "id": f"delivery:{r['id']}", "vendor_id": r["vendor_id"], "date": r["d"], "created_at": r["created_at"],
            "kind": "delivery", "title": f"{r['material']} · {_qty(r['quantity'])} {r['unit'] or ''}".strip(),
            "detail": f"Delivered, not billed yet{rate}", "owe": amount, "paid": Decimal(0),
            "project_id": r["project_id"], "project": r["project"], "site": r["site"],
            "ref": order_ref(r["order_number"]) if r["order_number"] else None,
            "links": {"receipt_id": str(r["id"]), **({"order_id": str(r["order_id"])} if r["order_id"] else {})},
        })

    # A bill paid by staff from their own pocket is settled with the supplier; payments on it repay the staff member,
    # not the supplier, so they are not supplier payments (8 Nov 2026).
    staff_bills = {r["id"] for r in bills if (r["payment_status"] or "") in ("reimbursable", "reimbursed")}
    payments = [r for r in payments if r["expense_id"] not in staff_bills]
    paid_on: dict = defaultdict(Decimal)
    applied_of: dict = defaultdict(Decimal)
    for r in payments:
        if r["expense_id"] is not None:
            paid_on[r["expense_id"]] += Decimal(r["amount"])
        if r["advance_id"] is not None:
            applied_of[r["advance_id"]] += Decimal(r["amount"])

    # NXT-06/07: a subcontract bill is payable only once checked, and never its retention held.
    from mesiri.domains.subcontracts.store import fetch_bills as wo_bills

    wo = {uuid.UUID(b["expense_id"]): b for b in await wo_bills(conn, org, expense_ids=[r["id"] for r in bills])} if bills else {}
    bill_state: dict = {}
    for r in bills:
        amount = Decimal(r["amount"])
        own_pocket = r["id"] in staff_bills
        paid = amount if own_pocket else min(amount, paid_on.get(r["id"], Decimal(0)))
        bill_state[r["id"]] = {
            "id": str(r["id"]), "vendor_id": r["vendor_id"], "date": r["d"], "number": r["expense_number"],
            "bill_number": r["bill_number"], "description": r["description"], "amount": amount, "paid": paid,
            "left": amount - paid, "project_id": r["project_id"], "project": r["project"], "site": r["site"],
            "payment_status": r["payment_status"], "deliveries": int(r["deliveries"] or 0),
            "mismatches": int(r["mismatches"] or 0),
            "payable": (min(amount - paid, Decimal(wo[r["id"]]["payable_now"])) if r["id"] in wo else amount - paid),
            "work_order": ({"ref": wo[r["id"]]["wo_ref"], "bill": wo[r["id"]]["ref"], "id": wo[r["id"]]["work_order_id"],
                            "check_status": wo[r["id"]]["check_status"], "retention_held": wo[r["id"]]["retention_held"]}
                           if r["id"] in wo else None),
            "in_window": after_start(r["vendor_id"], r["d"]),
        }
        if not after_start(r["vendor_id"], r["d"]):
            continue
        title = r["description"] or r["category"] or "Bill"
        entries.append({
            "id": f"bill:{r['id']}", "vendor_id": r["vendor_id"], "date": r["d"], "created_at": r["created_at"],
            "kind": "bill", "title": title,
            "detail": " · ".join(x for x in (
                f"Bill {r['bill_number']}" if r["bill_number"] else None, r["category"],
                f"GST ₹{money(r['tax_amount'])}" if r["tax_amount"] else None,
                f"{r['deliveries']} deliveries" if r["deliveries"] else None,
                f"⚠ {r['mismatches']} not as delivered" if r["mismatches"] else None) if x),
            "owe": amount, "paid": Decimal(0), "project_id": r["project_id"], "project": r["project"],
            "site": r["site"], "ref": r["expense_number"], "links": {"expense_id": str(r["id"])},
            "bill_left": money(amount - paid), "mismatches": int(r["mismatches"] or 0),
        })
        if own_pocket:
            who = r["recorded_by"] or "staff"
            entries.append({
                "id": f"staff:{r['id']}", "vendor_id": r["vendor_id"], "date": r["d"], "created_at": r["created_at"],
                "kind": "staff_paid", "title": f"Paid by {who}",
                "detail": f"From their own pocket; owed to {who.split(' ')[0]}, not to the supplier",
                "owe": Decimal(0), "paid": amount, "project_id": r["project_id"], "project": r["project"],
                "site": r["site"], "ref": r["expense_number"], "links": {"expense_id": str(r["id"])},
            })

    advances: list[dict] = []
    for r in payments:
        if r["advance_id"] is not None:
            continue  # applied part of an on-account payment: the money was listed with that payment
        if not after_start(r["vendor_id"], r["d"]):
            continue
        on_account = r["expense_id"] is None
        amount = Decimal(r["amount"])
        left = amount - applied_of.get(r["id"], Decimal(0)) if on_account else Decimal(0)
        if on_account:
            advances.append({"id": str(r["id"]), "vendor_id": r["vendor_id"], "date": r["d"], "amount": amount,
                             "left": left, "account": r["account"], "project": r["project"],
                             "reference": r["reference_number"]})
        detail = " · ".join(x for x in (
            f"from {r['account']}", r["payment_method"], f"ref {r['reference_number']}" if r["reference_number"] else None,
            (f"for {r['expense_number']}" if r["expense_number"] else "for a bill") if not on_account
            else ("on account" if left == amount else f"₹{money(left)} not used on a bill yet" if left else "used on bills"),
        ) if x)
        entries.append({
            "id": f"payment:{r['id']}", "vendor_id": r["vendor_id"], "date": r["d"], "created_at": r["created_at"],
            "kind": "payment", "title": "Paid on account" if on_account else "Paid",
            "detail": detail, "owe": Decimal(0), "paid": amount, "project_id": r["project_id"], "project": r["project"],
            "site": None, "ref": r["reference_number"],
            "links": {"payment_id": str(r["id"]), **({"expense_id": str(r["expense_id"])} if r["expense_id"] else {}),
                      "account_id": str(r["account_id"])},
            "on_account": on_account, "advance_left": money(left) if on_account else None,
            "recorded_by": r["recorded_by"],
        })

    entries.sort(key=lambda e: (e["date"], _KIND_ORDER[e["kind"]],
                                e["created_at"] or datetime.datetime.min.replace(tzinfo=datetime.UTC)))
    return entries, {"bills": bill_state, "advances": advances, "vendors": vendors}


def summarise(vendor: dict, entries: list[dict], state: dict, today: datetime.date) -> dict:
    """One supplier's position: balance, unbilled, open bills (with due date and age), unused advances, buckets."""
    vid = vendor["id"]
    mine = [e for e in entries if e["vendor_id"] == vid]
    owed = sum((e["owe"] for e in mine), Decimal(0))
    paid = sum((e["paid"] for e in mine), Decimal(0))
    unbilled = [e for e in mine if e["kind"] == "delivery"]
    credit = vendor.get("credit_days")
    open_bills = []
    buckets = {key: Decimal(0) for *_, key in BUCKETS}
    overdue = Decimal(0)
    for b in state["bills"].values():
        if b["vendor_id"] != vid or b["left"] <= 0 or not b["in_window"]:
            continue
        due = b["date"] + datetime.timedelta(days=credit) if credit is not None else None
        age = (today - b["date"]).days
        late = due is not None and today > due
        if late:
            overdue += b["payable"]
        buckets[_bucket(age)] += b["left"]
        open_bills.append({**{k: v for k, v in b.items() if k not in ("vendor_id", "in_window", "amount", "paid", "left",
                                                                      "project_id", "payable")},
                           "payable": money(b["payable"]),
                           "project_id": str(b["project_id"]) if b["project_id"] else None,
                           "date": b["date"].isoformat(), "amount": money(b["amount"]), "paid": money(b["paid"]),
                           "left": money(b["left"]), "due": due.isoformat() if due else None, "age_days": age,
                           "overdue_days": (today - due).days if late else 0})
    for d in unbilled:
        buckets[_bucket((today - d["date"]).days)] += d["owe"]
    open_bills.sort(key=lambda b: b["date"])
    adv = [a for a in state["advances"] if a["vendor_id"] == vid and a["left"] > 0]
    pays = [e for e in mine if e["kind"] == "payment"]
    last = max(pays, key=lambda e: e["date"]) if pays else None
    return {
        "balance": money(owed - paid),
        "owed": money(owed),
        "paid": money(paid),
        "unbilled": money(sum((d["owe"] for d in unbilled), Decimal(0))),
        "unbilled_count": len(unbilled),
        "oldest_unbilled": min((d["date"] for d in unbilled), default=None),
        "bills_open": len(open_bills),
        "bills_left": money(sum((Decimal(b["left"]) for b in open_bills), Decimal(0))),
        "overdue": money(overdue),
        "advance_left": money(sum((a["left"] for a in adv), Decimal(0))),
        "buckets": {k: money(v) for k, v in buckets.items()},
        "last_payment": {"date": last["date"].isoformat(), "amount": money(last["paid"])} if last else None,
        "open_bills": open_bills,
        "advances": [{**a, "vendor_id": str(a["vendor_id"]), "date": a["date"].isoformat(), "amount": money(a["amount"]),
                      "left": money(a["left"])} for a in adv],
        "lines": len(mine),
    }


def entry_out(e: dict, balance: Decimal) -> dict:
    return {
        "id": e["id"], "date": e["date"].isoformat(), "kind": e["kind"], "title": e["title"], "detail": e["detail"],
        "owe": money(e["owe"]) if e["owe"] else None, "paid": money(e["paid"]) if e["paid"] else None,
        "balance": money(balance), "project_id": str(e["project_id"]) if e["project_id"] else None,
        "project": e["project"], "site": e["site"], "ref": e["ref"], "links": e["links"],
        **({"bill_left": e["bill_left"], "mismatches": e.get("mismatches", 0)} if "bill_left" in e else {}),
        **({"on_account": e["on_account"], "advance_left": e["advance_left"], "recorded_by": e.get("recorded_by")}
           if e["kind"] == "payment" else {}),
    }


def vendor_out(v: dict) -> dict:
    return {
        "id": str(v["id"]), "name": v["name"], "code": v["code"], "status": v["status"], "phone": v["phone"],
        "gstin": v["gstin"], "address": v["address"], "kind": v["kind"], "credit_days": v["credit_days"],
        "opening_balance": money(v["opening_balance"]) if v["opening_balance"] is not None else None,
        "opening_balance_date": v["opening_balance_date"].isoformat() if v["opening_balance_date"] else None,
        "contact_person": v["contact_person"], "notes": v["notes"],
    }
