"""Subcontracts: reading and writing work orders, measurements and bills (SQL here; rules in ``rules.py``).

A work order's progress is always computed from the records, never stored: measured (confirmed measurements), billed
(lines of bills not rejected whose expense stands), paid (payments on those bills), retention held (retention on
payable bills less what was released), advance given (on-account payments to the subcontractor tagged with the work
order) and recovered (applied to its bills).
"""

from __future__ import annotations

import datetime
import json
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.subcontracts import rules

STATUSES = ("draft", "issued", "completed", "closed", "cancelled")
PAYABLE = ("passed", "approved")
TDS_ACCOUNT = "TDS payable (194C)"


def ref(number: int) -> str:
    return f"WO-{number:04d}"


def bill_ref(number: int) -> str:
    return f"RA-{number}"


def _m(v: Any) -> str:
    return str(rules.money(v))


async def next_number(conn: AsyncConnection, org: uuid.UUID) -> int:
    await conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('work_orders:' || :org))"), {"org": str(org)})
    return int((await conn.execute(text("SELECT COALESCE(MAX(number), 0) + 1 FROM work_orders WHERE organization_id = :org"),
                                   {"org": org})).scalar())


async def log(conn: AsyncConnection, org: uuid.UUID, wo_id: Any, kind: str, what: str, user_id: Any = None,
              name: str | None = None) -> None:
    await conn.execute(text(
        "INSERT INTO work_order_events (organization_id, work_order_id, kind, what, by_user, by_name) "
        "VALUES (:org, :wo, :k, :w, :u, :n)"), {"org": org, "wo": wo_id, "k": kind, "w": what, "u": user_id, "n": name})


async def fetch(conn: AsyncConnection, org: uuid.UUID, *, project_ids: set[uuid.UUID] | None = None,
                vendor_id: uuid.UUID | None = None, wo_id: uuid.UUID | None = None) -> list[dict]:
    """Work orders with their lines and progress, newest first."""
    where, p = ["w.organization_id = :org"], {"org": org}
    if project_ids is not None:
        where.append("w.project_id = ANY(:projects)")
        p["projects"] = list(project_ids)
    if vendor_id is not None:
        where.append("w.vendor_id = :v")
        p["v"] = vendor_id
    if wo_id is not None:
        where.append("w.id = :id")
        p["id"] = wo_id
    rows = [dict(r) for r in (await conn.execute(text(
        "SELECT w.*, v.name AS vendor_name, v.phone AS vendor_phone, v.gstin AS vendor_gstin, v.tds_pct AS vendor_tds_pct, "
        "v.kind AS vendor_kind, p.name AS project_name, s.name AS site_name, u.full_name AS created_by_name "
        "FROM work_orders w JOIN vendors v ON v.id = w.vendor_id JOIN projects p ON p.id = w.project_id "
        "LEFT JOIN sites s ON s.id = w.site_id LEFT JOIN users u ON u.id = w.created_by "
        f"WHERE {' AND '.join(where)} ORDER BY w.number DESC"), p)).mappings()]  # noqa: S608
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    lines = defaultdict(list)
    for r in (await conn.execute(text(
        "SELECT l.*, pi.boq_code, pi.work_type AS boq_work, pi.planned_quantity AS boq_quantity, "
        "pi.subcontract_rate AS boq_rate FROM work_order_lines l "
        "LEFT JOIN work_package_planned_items pi ON pi.id = l.planned_item_id "
        "WHERE l.work_order_id = ANY(:ids) ORDER BY l.position, l.description"), {"ids": ids})).mappings():
        lines[r["work_order_id"]].append(dict(r))
    measured = {r["line_id"]: (Decimal(r["confirmed"] or 0), Decimal(r["proposed"] or 0), r["last"]) for r in (await conn.execute(text(
        "SELECT line_id, SUM(quantity) FILTER (WHERE status = 'confirmed') AS confirmed, "
        "SUM(quantity) FILTER (WHERE status = 'proposed') AS proposed, MAX(measured_on) FILTER (WHERE status = 'confirmed') AS last "
        "FROM work_order_measurements WHERE work_order_id = ANY(:ids) GROUP BY line_id"), {"ids": ids})).mappings()}
    billed = {r["line_id"]: (Decimal(r["q"]), Decimal(r["a"])) for r in (await conn.execute(text(
        "SELECT bl.line_id, SUM(bl.quantity) AS q, SUM(bl.quantity * bl.rate) AS a FROM work_order_bill_lines bl "
        "JOIN work_order_bills b ON b.id = bl.bill_id JOIN expenses e ON e.id = b.expense_id "
        "WHERE b.work_order_id = ANY(:ids) AND b.check_status <> 'rejected' "
        "AND e.workflow_status IN ('confirmed', 'pending_confirmation') "
        "GROUP BY bl.line_id"), {"ids": ids})).mappings()}
    bills = await fetch_bills(conn, org, wo_ids=ids)
    advance = {r["work_order_id"]: Decimal(r["given"] or 0) for r in (await conn.execute(text(
        "SELECT work_order_id, SUM(amount) AS given FROM expense_payments WHERE work_order_id = ANY(:ids) "
        "AND expense_id IS NULL AND status = 'confirmed' GROUP BY work_order_id"), {"ids": ids})).mappings()}
    out = []
    for r in rows:
        wo_bills = [b for b in bills if b["work_order_id"] == str(r["id"])]
        out.append(_describe(r, lines[r["id"]], measured, billed, wo_bills, advance.get(r["id"], Decimal(0))))
    return out


def _describe(r: dict, lines: list[dict], measured: dict, billed: dict, bills: list[dict], advance_given: Decimal) -> dict:
    out_lines, value, done_value, billed_value = [], Decimal(0), Decimal(0), Decimal(0)
    for line in lines:
        q, rate = Decimal(line["quantity"]), Decimal(line["rate"])
        m, proposed, last = measured.get(line["id"], (Decimal(0), Decimal(0), None))
        bq, ba = billed.get(line["id"], (Decimal(0), Decimal(0)))
        value += q * rate
        done_value += min(m, q) * rate
        billed_value += ba
        out_lines.append({
            "id": str(line["id"]), "planned_item_id": str(line["planned_item_id"]) if line["planned_item_id"] else None,
            "boq_code": line.get("boq_code"), "description": line["description"], "unit": line["unit"],
            "quantity": rules.qty(q), "rate": _m(rate), "amount": _m(q * rate),
            "measured": rules.qty(m), "proposed": rules.qty(proposed), "last_measured": last.isoformat() if last else None,
            "billed": rules.qty(bq), "billed_amount": _m(ba),
            "to_bill": rules.qty(max(m - bq, Decimal(0))), "remaining": rules.qty(max(q - m, Decimal(0))),
            "over_measured": bq > m, "over_agreed": max(m, bq) > q,
        })
    payable = [b for b in bills if b["check_status"] in PAYABLE]
    recovered = sum((Decimal(b["advance_recovered"]) for b in payable), Decimal(0))
    held = sum((Decimal(b["retention_amount"]) - Decimal(b["retention_released"]) for b in payable), Decimal(0))
    paid = sum((Decimal(b["paid_cash"]) for b in bills), Decimal(0))
    return {
        "id": str(r["id"]), "number": r["number"], "ref": ref(r["number"]), "status": r["status"], "title": r["title"],
        "vendor_id": str(r["vendor_id"]), "vendor_name": r["vendor_name"], "vendor_phone": r["vendor_phone"],
        "vendor_gstin": r["vendor_gstin"], "vendor_tds_pct": _m(r["vendor_tds_pct"]) if r["vendor_tds_pct"] is not None else None,
        "project_id": str(r["project_id"]), "project_name": r["project_name"],
        "site_id": str(r["site_id"]) if r["site_id"] else None, "site_name": r["site_name"],
        "start_date": _d(r["start_date"]), "end_date": _d(r["end_date"]), "completed_on": _d(r["completed_on"]),
        "retention_pct": _m(r["retention_pct"]), "defect_days": r["defect_days"],
        "advance_agreed": _m(r["advance_agreed"]) if r["advance_agreed"] is not None else None,
        "advance_recovery_pct": _m(r["advance_recovery_pct"]) if r["advance_recovery_pct"] is not None else None,
        "tds_pct": _m(r["tds_pct"]) if r["tds_pct"] is not None else None,
        "their_ref": r["their_ref"], "terms": r["terms"], "notes": r["notes"], "status_note": r["status_note"],
        "created_by_name": r["created_by_name"], "created_at": r["created_at"].isoformat(),
        "issued_at": r["issued_at"].isoformat() if r["issued_at"] else None,
        "lines": out_lines,
        "totals": {
            "value": _m(value), "measured_value": _m(done_value), "billed": _m(billed_value),
            "approved": _m(sum((Decimal(b["gross"]) for b in payable), Decimal(0))),
            "paid": _m(paid), "retention_held": _m(held), "advance_given": _m(advance_given),
            "advance_recovered": _m(recovered), "advance_left": _m(max(advance_given - recovered, Decimal(0))),
            "progress_pct": str(int(done_value / value * 100)) if value > 0 else "0",
            "billed_pct": str(int(billed_value / value * 100)) if value > 0 else "0",
            "bills": len([b for b in bills if b["check_status"] != "rejected"]),
            "to_check": len([b for b in bills if b["check_status"] in ("waiting", "flagged")]),
            "payable_now": _m(sum((Decimal(b["payable_now"]) for b in bills), Decimal(0))),
        },
        "flags": sum(1 for x in out_lines if x["over_measured"] or x["over_agreed"]),
        "bills": bills,
    }


def _d(v: Any) -> str | None:
    return v.isoformat() if v else None


async def fetch_bills(conn: AsyncConnection, org: uuid.UUID, *, wo_ids: list | None = None,
                      bill_id: uuid.UUID | None = None, expense_ids: list | None = None) -> list[dict]:
    where, p = ["b.organization_id = :org"], {"org": org}
    if wo_ids is not None:
        where.append("b.work_order_id = ANY(:wos)")
        p["wos"] = wo_ids
    if bill_id is not None:
        where.append("b.id = :b")
        p["b"] = bill_id
    if expense_ids is not None:
        where.append("b.expense_id = ANY(:eids)")
        p["eids"] = expense_ids
    rows = [dict(r) for r in (await conn.execute(text(
        "SELECT b.*, e.workflow_status, e.payment_status, e.description, w.number AS wo_number, w.vendor_id, "
        "d.full_name AS decided_by_name, sb.full_name AS submitted_by_name, "
        "COALESCE((SELECT SUM(x.amount) FROM expense_payments x WHERE x.expense_id = b.expense_id AND x.status = 'confirmed'), 0) AS paid_all, "
        "COALESCE((SELECT SUM(x.amount) FROM expense_payments x JOIN money_accounts a ON a.id = x.account_id "
        "  WHERE x.expense_id = b.expense_id AND x.status = 'confirmed' AND x.advance_id IS NULL AND a.name <> :tds), 0) AS paid_cash "
        "FROM work_order_bills b JOIN expenses e ON e.id = b.expense_id JOIN work_orders w ON w.id = b.work_order_id "
        "LEFT JOIN users d ON d.id = b.decided_by LEFT JOIN users sb ON sb.id = b.submitted_by "
        f"WHERE {' AND '.join(where)} ORDER BY b.number"), {**p, "tds": TDS_ACCOUNT})).mappings()]  # noqa: S608
    if not rows:
        return []
    blines = defaultdict(list)
    for r in (await conn.execute(text(
        "SELECT bl.*, l.description, l.unit, l.rate AS agreed_rate FROM work_order_bill_lines bl "
        "JOIN work_order_lines l ON l.id = bl.line_id WHERE bl.bill_id = ANY(:ids) ORDER BY l.position"),
        {"ids": [r["id"] for r in rows]})).mappings():
        blines[r["bill_id"]].append({"line_id": str(r["line_id"]), "description": r["description"], "unit": r["unit"],
                                     "quantity": rules.qty(r["quantity"]), "rate": _m(r["rate"]),
                                     "agreed_rate": _m(r["agreed_rate"]), "amount": _m(Decimal(r["quantity"]) * Decimal(r["rate"]))})
    out = []
    for r in rows:
        # A bill waiting for its check is an expense waiting for confirmation: not owed, not a cost, not payable
        # until it passes or is approved (8 Nov 2026). Taken back (voided / rejected): rejected.
        status = "rejected" if r["workflow_status"] in ("voided", "rejected") else r["check_status"]
        gross = Decimal(r["gross"])
        left = max(gross - Decimal(r["paid_all"]), Decimal(0))
        held = Decimal(r["retention_amount"]) - Decimal(r["retention_released"])
        payable_now = max(left - held, Decimal(0)) if status in PAYABLE else Decimal(0)
        out.append({
            "id": str(r["id"]), "work_order_id": str(r["work_order_id"]), "wo_ref": ref(r["wo_number"]),
            "vendor_id": str(r["vendor_id"]), "expense_id": str(r["expense_id"]), "number": r["number"],
            "ref": bill_ref(r["number"]), "their_bill_no": r["their_bill_no"], "bill_date": r["bill_date"].isoformat(),
            "gross": _m(gross), "check_status": status, "flags": (flags := r["flags"] if isinstance(r["flags"], list) else json.loads(r["flags"] or "[]")),
            "caught": _m(rules.caught(flags, gross)),
            "retention_amount": _m(r["retention_amount"]), "retention_released": _m(r["retention_released"]),
            "retention_held": _m(held if status in PAYABLE else 0),
            "advance_recovered": _m(r["advance_recovered"]), "tds_pct": _m(r["tds_pct"]) if r["tds_pct"] is not None else None,
            "tds_amount": _m(r["tds_amount"]), "net_payable": _m(r["net_payable"]) if r["net_payable"] is not None else None,
            "paid_cash": _m(r["paid_cash"]), "left": _m(left), "payable_now": _m(payable_now),
            "payment_status": r["payment_status"], "decided_by_name": r["decided_by_name"],
            "decided_at": r["decided_at"].isoformat() if r["decided_at"] else None, "decision_reason": r["decision_reason"],
            "submitted_by_name": r["submitted_by_name"], "submitted_by_contact": str(r["submitted_by_contact"]) if r["submitted_by_contact"] else None,
            "source": r["source"], "created_at": r["created_at"].isoformat(), "lines": blines[r["id"]],
        })
    return out


async def payable_caps(conn: AsyncConnection, org: uuid.UUID, expense_ids: list) -> dict:
    """For subcontract bills among these expenses: expense id -> what may be paid now (0 while waiting for a check;
    never the retention held). Expenses that are not subcontract bills are not in the answer."""
    if not expense_ids:
        return {}
    return {uuid.UUID(b["expense_id"]): Decimal(b["payable_now"]) for b in await fetch_bills(conn, org, expense_ids=list(expense_ids))}


async def history(conn: AsyncConnection, wo_id: Any) -> list[dict]:
    rows = (await conn.execute(text(
        "SELECT e.kind, e.what, e.at, COALESCE(u.full_name, e.by_name) AS who FROM work_order_events e "
        "LEFT JOIN users u ON u.id = e.by_user WHERE e.work_order_id = :wo ORDER BY e.at DESC"), {"wo": wo_id})).mappings()
    return [{"kind": r["kind"], "what": r["what"], "at": r["at"].isoformat(), "who": r["who"]} for r in rows]


async def measurements(conn: AsyncConnection, wo_id: Any) -> list[dict]:
    rows = (await conn.execute(text(
        "SELECT m.*, l.description, l.unit, COALESCE(u.full_name, m.recorded_by_name) AS who, d.full_name AS decided_by_name "
        "FROM work_order_measurements m JOIN work_order_lines l ON l.id = m.line_id "
        "LEFT JOIN users u ON u.id = m.recorded_by LEFT JOIN users d ON d.id = m.decided_by "
        "WHERE m.work_order_id = :wo AND m.status <> 'removed' ORDER BY m.measured_on DESC, m.created_at DESC"), {"wo": wo_id})).mappings()
    return [{"id": str(r["id"]), "line_id": str(r["line_id"]), "description": r["description"], "unit": r["unit"],
             "measured_on": r["measured_on"].isoformat(), "quantity": rules.qty(r["quantity"]), "notes": r["notes"],
             "status": r["status"], "source": r["source"], "who": r["who"], "decided_by_name": r["decided_by_name"],
             "has_photo": bool(r["photo_key"]), "from_activity": r["activity_quantity_id"] is not None} for r in rows]


async def team_days(conn: AsyncConnection, org: uuid.UUID, vendor_id: Any, project_id: Any, site_id: Any) -> dict:
    """The subcontractor's team on site from attendance (lines that name them): man-days and the last day."""
    sql = ("SELECT COALESCE(SUM(l.headcount), 0) AS days, MAX(r.occurred_date) AS last, COUNT(DISTINCT r.occurred_date) AS n "
           "FROM labour_attendance_lines l JOIN labour_attendance_reports r ON r.id = l.report_id "
           "WHERE r.organization_id = :org AND l.vendor_id = :v AND r.project_id = :p")
    p = {"org": org, "v": vendor_id, "p": project_id}
    if site_id:
        sql += " AND r.site_id = :s"
        p["s"] = site_id
    r = (await conn.execute(text(sql), p)).mappings().first()
    return {"man_days": rules.qty(Decimal(r["days"] or 0)), "days": int(r["n"] or 0), "last": _d(r["last"])}


async def tds_account(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    """The company's TDS payable account (type other): TDS deducted from a bill is paid "from" it, so its balance
    below zero is what is owed to the government; paying the government is a transfer into it."""
    found = (await conn.execute(text(
        "SELECT id FROM money_accounts WHERE organization_id = :org AND name = :n"), {"org": org, "n": TDS_ACCOUNT})).scalar()
    if found:
        return found
    from mesiri.infrastructure.postgres.repositories.finance import PostgresMoneyAccountRepository

    acc = await PostgresMoneyAccountRepository(conn).create(
        organization_id=org, name=TDS_ACCOUNT, account_type="other", currency="INR", opening_balance=Decimal(0),
        opening_balance_date=datetime.date.today(), created_by=user_id)
    return acc.id


async def refuse_tds_account(conn: AsyncConnection, org: uuid.UUID, account_id: Any) -> None:
    """The TDS payable account only collects TDS deducted (and is paid off by a transfer into it): nothing is paid
    from it, so money owed to the government is never spent on a supplier."""
    from fastapi import HTTPException

    if account_id is None:
        return
    name = (await conn.execute(text("SELECT name FROM money_accounts WHERE id = :a AND organization_id = :org"),
                               {"a": account_id, "org": org})).scalar()
    if name == TDS_ACCOUNT:
        raise HTTPException(status_code=409, detail="The TDS payable account only collects TDS: pay from a bank or cash account.")
