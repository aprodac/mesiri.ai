"""RA bills (NXT-02): reads and writes. The money is ``ra.py``.

A draft is made from the BOQ: every current priced line whose work measured to date (CC-04's ``done_by_line``, the
same count as the BOQ page and the Gantt) is more than what earlier bills already billed. Earlier bills are the
project's bills that are not cancelled; a line billed under an older revision of the BOQ line counts for its current
revision. The contract's percentages are copied onto the bill. Totals are stored on submit.

Every function takes the request's connection and never commits.
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.billing import ra

_BILL = ("b.id, b.project_id, p.name AS project_name, b.number, b.status, b.bill_date, b.period_to, b.client_id, "
         "cl.name AS client_name, cl.gstin AS client_gstin, cl.address AS client_address, b.retention_pct, "
         "b.advance_recovery_pct, b.gst_pct, b.tds_pct, b.gross, b.retention, b.advance_recovery, b.gst, b.tds, b.net, "
         "b.certified_amount, b.certified_on, b.notes, b.submitted_at, b.created_at")


def ref(number: int) -> str:
    return f"RA-{number:02d}"


async def _current_of(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> dict:
    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

    return await PostgresBoqRepository(conn).current_revision_of(org, project_id)


async def previous_by_line(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID,
                           exclude_bill: Any = None) -> dict[Any, Decimal]:
    """What the project's other bills (not cancelled) already billed, per current BOQ line."""
    rows = (await conn.execute(text(
        "SELECT l.planned_item_id, SUM(l.quantity) AS q FROM ra_bill_lines l JOIN ra_bills b ON b.id = l.ra_bill_id "
        "WHERE b.organization_id = :org AND b.project_id = :p AND b.status <> 'cancelled' "
        "AND (CAST(:x AS uuid) IS NULL OR b.id <> CAST(:x AS uuid)) GROUP BY l.planned_item_id"),
        {"org": org, "p": project_id, "x": exclude_bill})).all()
    current = await _current_of(conn, org, project_id)
    out: dict[Any, Decimal] = defaultdict(Decimal)
    for item, q in rows:
        out[current.get(item, item)] += Decimal(q)
    return dict(out)


async def advance_left(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, exclude_bill: Any = None) -> Decimal:
    """The contract's mobilisation advance less what submitted / certified bills already recovered."""
    advance = (await conn.execute(text(
        "SELECT COALESCE(mobilisation_advance, 0) FROM project_contracts WHERE organization_id = :org "
        "AND project_id = :p"), {"org": org, "p": project_id})).scalar() or Decimal(0)
    recovered = (await conn.execute(text(
        "SELECT COALESCE(SUM(advance_recovery), 0) FROM ra_bills WHERE organization_id = :org AND project_id = :p "
        "AND status IN ('submitted', 'certified') AND (CAST(:x AS uuid) IS NULL OR id <> CAST(:x AS uuid))"),
        {"org": org, "p": project_id, "x": exclude_bill})).scalar() or Decimal(0)
    return Decimal(advance) - Decimal(recovered)


async def create_draft(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, bill_date: datetime.date,
                       period_to: datetime.date | None, user_id: uuid.UUID) -> tuple[Any, int]:
    """A new draft with a line per BOQ line that has measured work not billed yet. Returns (id, lines added)."""
    from mesiri.domains.progress.boq_router import done_by_line
    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

    repo = PostgresBoqRepository(conn)
    lines = await repo.list_lines(org, project_id)
    done = await done_by_line(repo, org, project_id, lines)
    previous = await previous_by_line(conn, org, project_id)
    contract = (await conn.execute(text(
        "SELECT client_id, retention_pct, advance_recovery_pct, gst_pct, tds_pct FROM project_contracts "
        "WHERE organization_id = :org AND project_id = :p"), {"org": org, "p": project_id})).mappings().first() or {}
    number = (await conn.execute(text(
        "SELECT COALESCE(MAX(number), 0) + 1 FROM ra_bills WHERE organization_id = :org AND project_id = :p"),
        {"org": org, "p": project_id})).scalar_one()
    bill_id = (await conn.execute(text(
        "INSERT INTO ra_bills (organization_id, project_id, number, bill_date, period_to, client_id, retention_pct, "
        "advance_recovery_pct, gst_pct, tds_pct, created_by) VALUES (:org, :p, :n, :d, :to, :client, :ret, :rec, "
        ":gst, :tds, :by) RETURNING id"),
        {"org": org, "p": project_id, "n": number, "d": bill_date, "to": period_to, "client": contract.get("client_id"),
         "ret": contract.get("retention_pct") or 0, "rec": contract.get("advance_recovery_pct") or 0,
         "gst": contract.get("gst_pct") or 0, "tds": contract.get("tds_pct") or 0, "by": user_id})).scalar_one()
    added = 0
    for i, ln in enumerate(lines):
        if ln["client_rate"] is None:
            continue
        measured = done[ln["id"]]["done"]
        before = previous.get(ln["id"], Decimal(0))
        qty = ra.suggested(measured, before)
        if qty <= 0:
            continue
        await conn.execute(text(
            "INSERT INTO ra_bill_lines (organization_id, ra_bill_id, planned_item_id, boq_code, work, unit, client_rate, "
            "measured_to_date, previous_quantity, suggested_quantity, quantity, sort_order) VALUES (:org, :b, :item, "
            ":code, :work, :unit, :rate, :m, :prev, :q, :q, :i)"),
            {"org": org, "b": bill_id, "item": ln["id"], "code": ln["boq_code"], "work": ln["work_type"],
             "unit": ln["unit"], "rate": ln["client_rate"], "m": measured, "prev": before, "q": qty, "i": i})
        added += 1
    return bill_id, added


async def get(conn: AsyncConnection, org: uuid.UUID, bill_id: uuid.UUID) -> dict[str, Any] | None:
    row = (await conn.execute(text(
        f"SELECT {_BILL}, pc.contract_no, pc.contract_value, pc.mobilisation_advance FROM ra_bills b "  # noqa: S608
        "JOIN projects p ON p.id = b.project_id LEFT JOIN clients cl ON cl.id = b.client_id "
        "LEFT JOIN project_contracts pc ON pc.project_id = b.project_id "
        "WHERE b.organization_id = :org AND b.id = :id"), {"org": org, "id": bill_id})).mappings().first()
    if row is None:
        return None
    bill = dict(row)
    bill["ref"] = ref(bill["number"])
    bill["lines"] = [dict(r) for r in (await conn.execute(text(
        "SELECT id, planned_item_id, boq_code, work, unit, client_rate, measured_to_date, previous_quantity, "
        "suggested_quantity, quantity FROM ra_bill_lines WHERE ra_bill_id = :b ORDER BY sort_order, work"),
        {"b": bill_id})).mappings()]
    for ln in bill["lines"]:
        ln["amount"] = ra.line_amount(ln["quantity"], ln["client_rate"])
        ln["upto_date"] = Decimal(ln["previous_quantity"]) + Decimal(ln["quantity"])
        ln["edited"] = Decimal(ln["quantity"]) != Decimal(ln["suggested_quantity"])
    if bill["status"] == "draft":
        left = await advance_left(conn, org, bill["project_id"], exclude_bill=bill_id)
        bill.update(ra.totals(bill["lines"], bill, left))
    bill["warnings"] = await gaps(conn, org, bill["project_id"], bill_id) if bill["status"] in ("draft", "submitted") else []
    bill["previous_billed"] = (await conn.execute(text(
        "SELECT COALESCE(SUM(gross), 0) FROM ra_bills WHERE organization_id = :org AND project_id = :p "
        "AND status IN ('submitted', 'certified') AND number < :n"),
        {"org": org, "p": bill["project_id"], "n": bill["number"]})).scalar_one()
    return bill


async def gaps(conn: AsyncConnection, org: uuid.UUID, project_id: Any, bill_id: Any) -> list[dict[str, Any]]:
    """What the bill can't show by itself, so nobody is billed wrong without knowing:

    - **unpriced**: work measured on a BOQ line with no client rate: it is not on any bill;
    - **other_unit**: work updates on a line in another unit (sq ft on a sq m line): never added in;
    - **overbilled**: the bills (this one included, withdrawn ones not) hold more than is measured now, e.g. a site
      update was removed after a bill went out.
    """
    from mesiri.domains.progress.boq_router import done_by_line
    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

    repo = PostgresBoqRepository(conn)
    lines = await repo.list_lines(org, project_id)
    done = await done_by_line(repo, org, project_id, lines)
    billed = await previous_by_line(conn, org, project_id)  # every non-withdrawn bill, this one included
    out = []
    for ln in lines:
        measured = done[ln["id"]]["done"]
        on_bills = billed.get(ln["id"], Decimal(0))
        unit = ln["unit"]
        if ln["client_rate"] is None and measured > on_bills:
            out.append({"kind": "unpriced", "work": ln["work_type"],
                        "message": f"{ln['work_type']}: {_q(measured - on_bills)} {unit} measured but the line has no "
                                   "client rate, so it is not billed. Add the rate on the BOQ, then make the bill again."})
        if done[ln["id"]]["other_unit"]:
            n = done[ln["id"]]["other_unit"]
            out.append({"kind": "other_unit", "work": ln["work_type"],
                        "message": f"{ln['work_type']}: {n} work update{'s' if n > 1 else ''} recorded in another unit "
                                   f"(not {unit}) {'are' if n > 1 else 'is'} not counted. Put them right on the BOQ page."})
        if on_bills > measured:
            out.append({"kind": "overbilled", "work": ln["work_type"],
                        "message": f"{ln['work_type']}: {_q(on_bills)} {unit} billed so far but only {_q(measured)} "
                                   f"measured now (a site update was changed or removed?). Check before sending."})
    return out


def _q(v: Decimal) -> str:
    v = Decimal(v)
    return f"{v.normalize():f}" if v == v.to_integral_value() else f"{v.quantize(Decimal('0.001')).normalize():f}"


async def list_bills(conn: AsyncConnection, org: uuid.UUID, project_ids: set | None) -> list[dict[str, Any]]:
    sql = (f"SELECT {_BILL} FROM ra_bills b JOIN projects p ON p.id = b.project_id "  # noqa: S608
           "LEFT JOIN clients cl ON cl.id = b.client_id WHERE b.organization_id = :org")
    params: dict = {"org": org}
    if project_ids is not None:
        sql += " AND b.project_id = ANY(:ps)"
        params["ps"] = list(project_ids)
    rows = [dict(r) for r in (await conn.execute(text(sql + " ORDER BY lower(p.name), b.number DESC"), params)).mappings()]
    for r in rows:
        r["ref"] = ref(r["number"])
        if r["status"] == "draft":  # a draft's money is worked out when read
            full = await get(conn, org, r["id"])
            r.update({k: full[k] for k in ("gross", "retention", "advance_recovery", "gst", "tds", "net")})
    return rows


async def set_quantity(conn: AsyncConnection, bill_id: uuid.UUID, line_id: uuid.UUID, quantity: Decimal) -> bool:
    res = await conn.execute(text(
        "UPDATE ra_bill_lines SET quantity = :q WHERE id = :l AND ra_bill_id = :b"),
        {"q": quantity, "l": line_id, "b": bill_id})
    return res.rowcount > 0


async def update_details(conn: AsyncConnection, bill_id: uuid.UUID, values: dict[str, Any]) -> None:
    cols = [c for c in ("bill_date", "period_to", "notes") if c in values]
    if cols:
        await conn.execute(text(
            f"UPDATE ra_bills SET {', '.join(f'{c} = :{c}' for c in cols)}, updated_at = now() WHERE id = :id"),  # noqa: S608
            {"id": bill_id, **{c: values[c] for c in cols}})


async def submit(conn: AsyncConnection, bill: dict[str, Any], user_id: uuid.UUID) -> None:
    """Freeze the draft: store its money (worked out by ``get``) and mark it submitted."""
    await conn.execute(text(
        "UPDATE ra_bills SET status = 'submitted', gross = :gross, retention = :retention, "
        "advance_recovery = :advance_recovery, gst = :gst, tds = :tds, net = :net, submitted_by = :by, "
        "submitted_at = now(), updated_at = now() WHERE id = :id AND status = 'draft'"),
        {"id": bill["id"], "by": user_id, **{k: bill[k] for k in ("gross", "retention", "advance_recovery", "gst", "tds",
                                                                      "net")}})


async def set_status(conn: AsyncConnection, bill_id: uuid.UUID, status: str, **extra: Any) -> None:
    sets = ", ".join([f"{k} = :{k}" for k in extra] + ["status = :status", "updated_at = now()"])
    await conn.execute(text(f"UPDATE ra_bills SET {sets} WHERE id = :id"),  # noqa: S608 (fixed names)
                       {"id": bill_id, "status": status, **extra})


async def delete_draft(conn: AsyncConnection, bill_id: uuid.UUID) -> None:
    await conn.execute(text("DELETE FROM ra_bills WHERE id = :id AND status = 'draft'"), {"id": bill_id})


async def billed_items(conn: AsyncConnection, item_ids: list) -> int:
    """How many of these BOQ line rows are on a bill (a billed line can't be removed from the BOQ)."""
    if not item_ids:
        return 0
    return int((await conn.execute(text(
        "SELECT count(*) FROM ra_bill_lines WHERE planned_item_id = ANY(:ids)"), {"ids": list(item_ids)})).scalar() or 0)
