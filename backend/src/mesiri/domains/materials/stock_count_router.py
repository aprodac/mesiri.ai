"""PRC-48: Materials > Stock count -- the routes. Rules in ``stock_count.py``.

``GET  /materials/stock-counts``                  the counts (status open | approved | cancelled | all), each site's
                                                  last count and the sites due one
``POST /materials/stock-counts``                  start a count for a site (all, a category, or the top 20 by value)
``GET  /materials/stock-counts/{id}``             one count: per line book, counted, difference, its value
``PUT  /materials/stock-counts/{id}/lines``       what was counted (partial saves; counted null = not counted)
``POST /materials/stock-counts/{id}/approve``     post the differences (admin / owner, D-P2-2)
``POST /materials/stock-counts/{id}/cancel``      not going on with it

Anyone who may record stock at the site starts and fills a count; approving is the admin's or owner's. Rupees only
for the roles that see spending (D-CC4).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_view_expenses
from mesiri.domains.materials import stock_count as rules
from mesiri.domains.materials.router import (
    MaterialInflowCreate,
    MaterialOutflowCreate,
    _authorize_write,
    _convert_to_stock_unit,
    _resolve_project_ids,
    _site_filter_denied,
    record_inflow,
    record_outflow,
)
from mesiri.domains.materials.valuation import average_rates, money
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(prefix="/materials/stock-counts", tags=["materials"],
                   dependencies=[Depends(require_module("materials"))])


class CountStart(BaseModel):
    site_id: uuid.UUID
    scope: Literal["all", "category", "top"] = "all"
    category_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=300)


class CountLineIn(BaseModel):
    material_id: uuid.UUID
    #: What is there; null: not counted (yet). In the unit said (unit_id), converted to the stock unit.
    counted: Decimal | None = Field(default=None, ge=0)
    unit_id: uuid.UUID | None = None
    reason: Literal["wastage", "theft", "wrong_entry", "unrecorded_use", "found", "other"] | None = None


class CountLines(BaseModel):
    lines: list[CountLineIn] = Field(min_length=1, max_length=500)


class CancelIn(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


async def _today(conn: AsyncConnection, auth: AuthorizationContext) -> datetime.date:
    from mesiri.application.dpr import project_day

    return await project_day.company_today(conn, auth.organization_id)


async def _fetch(conn: AsyncConnection, auth: AuthorizationContext, count_id: uuid.UUID | None = None, *,
                 lock: bool = False) -> list[dict]:
    project_ids, denied = _resolve_project_ids(auth, None)
    if denied:
        return []
    sql = ("SELECT c.*, s.name AS site_name, p.name AS project_name, cat.name AS category_name, "
           "cb.full_name AS created_by_name, ab.full_name AS approved_by_name FROM stock_counts c "
           "JOIN sites s ON s.id = c.site_id JOIN projects p ON p.id = c.project_id "
           "LEFT JOIN material_categories cat ON cat.id = c.category_id "
           "LEFT JOIN users cb ON cb.id = c.created_by LEFT JOIN users ab ON ab.id = c.approved_by "
           "WHERE c.organization_id = :org")
    params: dict = {"org": auth.organization_id}
    if count_id is not None:
        sql += " AND c.id = :id"
        params["id"] = count_id
    if project_ids is not None:
        sql += " AND c.project_id = ANY(:projects)"
        params["projects"] = list(project_ids)
    sql += " ORDER BY c.created_at DESC" + (" FOR UPDATE OF c" if lock else "")
    rows = [dict(r) for r in (await conn.execute(text(sql), params)).mappings().all()
            if not _site_filter_denied(auth, r["project_id"], r["site_id"])]
    if not rows:
        return []
    lines = (await conn.execute(text(
        "SELECT l.*, m.name AS material, u.code AS unit, COALESCE(parent.name, cat.name) AS main_category "
        "FROM stock_count_lines l JOIN materials_catalog m ON m.id = l.material_id "
        "JOIN units_of_measure u ON u.id = l.unit_id LEFT JOIN material_categories cat ON cat.id = m.category_id "
        "LEFT JOIN material_categories parent ON parent.id = cat.parent_id WHERE l.count_id = ANY(:ids) "
        "ORDER BY COALESCE(parent.name, cat.name, '~'), m.name"), {"ids": [r["id"] for r in rows]})).mappings().all()
    by: dict = {}
    for line in lines:
        by.setdefault(line["count_id"], []).append(dict(line))
    for r in rows:
        r["lines"] = by.get(r["id"], [])
    return rows


def _out(auth: AuthorizationContext, row: dict, *, with_lines: bool = True) -> dict:
    money_role = may_view_expenses(auth.role)
    figures = rules.review(row["lines"])
    lines = []
    for x in row["lines"]:
        d = rules.difference(x)
        lines.append({
            "material_id": str(x["material_id"]), "material": x["material"], "unit": x["unit"],
            "unit_id": str(x["unit_id"]), "main_category": x["main_category"] or "No category",
            "book": rules.num(x["book_qty"]), "counted": rules.num(x["counted_qty"]) if x["counted_qty"] is not None else None,
            "difference": rules.num(d["difference"]) if d["difference"] is not None else None, "reason": x["reason"],
            **({"rate": money(x["rate"]), "difference_value": money(d["difference_value"])} if money_role else {}),
        })
    if money_role:
        lines.sort(key=lambda x: -abs(Decimal(x["difference_value"] or 0)))
    live = row["status"] == "open"
    return {
        "id": str(row["id"]), "number": row["number"], "ref": rules.ref(row["number"]), "status": row["status"],
        "project_id": str(row["project_id"]), "project_name": row["project_name"], "site_id": str(row["site_id"]),
        "site_name": row["site_name"], "scope": row["scope"], "category_name": row["category_name"],
        "notes": row["notes"], "created_by_name": row["created_by_name"], "created_at": row["created_at"].isoformat(),
        "approved_by_name": row["approved_by_name"],
        "approved_at": row["approved_at"].isoformat() if row["approved_at"] else None,
        "cancel_reason": row["cancel_reason"],
        "counts": {k: figures[k] for k in ("lines", "counted", "not_counted", "differing")},
        **({"net_value": money(figures["net_value"]), "gross_value": money(figures["gross_value"])} if money_role else {}),
        "may_count": live, "may_approve": live and rules.may_approve(auth.role) and figures["counted"] > 0,
        **({"lines": lines} if with_lines else {}),
    }


async def _one(conn: AsyncConnection, auth: AuthorizationContext, count_id: uuid.UUID, *, lock: bool = False) -> dict:
    rows = await _fetch(conn, auth, count_id, lock=lock)
    if not rows:
        raise HTTPException(status_code=404, detail="Count not found")
    return rows[0]


@router.get("")
async def list_counts(status: Literal["open", "approved", "cancelled", "all"] = Query(default="all"),
                      site_id: uuid.UUID | None = None,
                      auth_context: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    """The counts newest first (without their lines), each site's last approved count, and the sites due one."""
    rows = [r for r in await _fetch(conn, auth_context) if (status == "all" or r["status"] == status)
            and (site_id is None or r["site_id"] == site_id)]
    project_ids, denied = _resolve_project_ids(auth_context, None)
    due = [] if denied else [
        {"site_id": str(s["id"]), "site_name": s["name"], "project_name": s["project_name"],
         "last_counted": s["last"].date().isoformat() if s["last"] else None}
        for s in await rules.due_sites(conn, auth_context.organization_id, await _today(conn, auth_context))
        if (project_ids is None or s["project_id"] in project_ids)
        and not _site_filter_denied(auth_context, s["project_id"], s["id"])]
    return {"items": [_out(auth_context, r, with_lines=False) for r in rows], "total": len(rows), "due": due,
            "last_counted": {k: v.date().isoformat() for k, v in
                             (await rules.last_counted(conn, auth_context.organization_id)).items()}}


@router.post("", status_code=201)
async def start_count(body: CountStart, auth_context: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    """Start counting a site: the book quantity of each item is frozen now. One open count per site."""
    from mesiri.infrastructure.postgres.repositories.materials import PostgresMaterialReadRepository

    org = auth_context.organization_id
    site = (await conn.execute(text("SELECT id, project_id FROM sites WHERE id = :s AND organization_id = :org"),
                               {"s": body.site_id, "org": org})).mappings().first()
    if site is None or _site_filter_denied(auth_context, site["project_id"], body.site_id) or \
            _resolve_project_ids(auth_context, site["project_id"])[1]:
        raise HTTPException(status_code=404, detail="Site not found")
    _authorize_write(auth_context, site["project_id"], body.site_id)
    if auth_context.role.upper() == "FINANCE":
        raise HTTPException(status_code=403, detail="Counting stock is for the people at the site and the office.")
    if body.scope == "category" and body.category_id is None:
        raise HTTPException(status_code=422, detail="Say which category to count.")
    today = await _today(conn, auth_context)
    rows = await PostgresMaterialReadRepository(conn).get_stock_summary(
        org, date_from=today, date_to=today, project_ids={site["project_id"]}, site_id=body.site_id,
        category_id=body.category_id if body.scope == "category" else None)
    rows = [r for r in rows if Decimal(str(r["closing"])) != 0]
    rates = await average_rates(conn, org, today)
    if body.scope == "top":
        rows = rules.pick_top(rows, rates)
    if not rows:
        raise HTTPException(status_code=422, detail="Nothing is in stock at this site to count.")
    await conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"stock_counts:{org}"})
    number = int((await conn.execute(text("SELECT COALESCE(MAX(number), 0) + 1 FROM stock_counts WHERE organization_id = :org"),
                                     {"org": org})).scalar_one())
    count_id = uuid.uuid4()
    try:
        async with conn.begin_nested():
            await conn.execute(text(
                "INSERT INTO stock_counts (id, organization_id, number, project_id, site_id, scope, category_id, notes, "
                "created_by) VALUES (:id, :org, :n, :p, :s, :scope, :cat, :notes, :by)"),
                {"id": count_id, "org": org, "n": number, "p": site["project_id"], "s": body.site_id, "scope": body.scope,
                 "cat": body.category_id if body.scope == "category" else None,
                 "notes": (body.notes or "").strip() or None, "by": auth_context.user_id})
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="A count is already open for this site: finish or cancel it first.") from exc
    unit_of = {str(r.id): r.default_unit_id for r in (await conn.execute(text(
        "SELECT id, default_unit_id FROM materials_catalog WHERE id = ANY(:ids)"),
        {"ids": [r["material_id"] for r in rows]})).all()}
    for r in rows:
        rate = rates.get(str(r["material_id"]))
        await conn.execute(text(
            "INSERT INTO stock_count_lines (organization_id, count_id, material_id, unit_id, book_qty, rate) "
            "VALUES (:org, :c, :m, :u, :book, :rate)"),
            {"org": org, "c": count_id, "m": r["material_id"], "u": unit_of[str(r["material_id"])],
             "book": r["closing"], "rate": rate.quantize(Decimal("0.01")) if rate is not None else None})
    return _out(auth_context, await _one(conn, auth_context, count_id))


@router.get("/{count_id}")
async def get_count(count_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    return _out(auth_context, await _one(conn, auth_context, count_id))


@router.put("/{count_id}/lines")
async def count_lines(count_id: uuid.UUID, body: CountLines, auth_context: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    """Save what was counted (only the lines sent; counted null = not counted). An item on the count only, in the unit
    they said (converted to the stock unit as a delivery is)."""
    row = await _one(conn, auth_context, count_id, lock=True)
    _authorize_write(auth_context, row["project_id"], row["site_id"])
    if row["status"] != "open":
        raise HTTPException(status_code=409, detail=f"{rules.ref(row['number'])} is {row['status']}: a new count "
                            "corrects it.")
    on_count = {str(x["material_id"]): x for x in row["lines"]}
    for line in body.lines:
        mine = on_count.get(str(line.material_id))
        if mine is None:
            raise HTTPException(status_code=422, detail="That item is not on this count.")
        counted = line.counted
        if counted is not None and line.unit_id is not None and line.unit_id != mine["unit_id"]:
            said = SimpleNamespace(material_id=line.material_id, unit_id=line.unit_id, quantity=counted, notes=None)
            await _convert_to_stock_unit(conn, auth_context.organization_id, said)
            if said.unit_id != mine["unit_id"]:
                raise HTTPException(status_code=422, detail=f"{mine['material']} is counted in {mine['unit']}: say how "
                                    "many of those.")
            counted = Decimal(str(said.quantity))
        await conn.execute(text(
            "UPDATE stock_count_lines SET counted_qty = :q, reason = COALESCE(:r, reason), counted_by = :by, "
            "counted_at = now() WHERE count_id = :c AND material_id = :m"),
            {"q": counted, "r": line.reason, "by": auth_context.user_id, "c": count_id, "m": line.material_id})
    return _out(auth_context, await _one(conn, auth_context, count_id))


@router.post("/{count_id}/approve")
async def approve(count_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                  conn: AsyncConnection = Depends(get_db_conn)):
    """Post each counted difference as ADJUSTMENT_IN / ADJUSTMENT_OUT (the count as reference); lines not counted are
    left as they are. A difference needs its reason. Admin or owner (D-P2-2)."""
    if not rules.may_approve(auth_context.role):
        raise HTTPException(status_code=403, detail="Only an admin or the owner can approve a stock count.")
    row = await _one(conn, auth_context, count_id, lock=True)
    if row["status"] != "open":
        raise HTTPException(status_code=409, detail=f"{rules.ref(row['number'])} is {row['status']}.")
    counted = [x for x in row["lines"] if x["counted_qty"] is not None]
    if not counted:
        raise HTTPException(status_code=422, detail="Nothing is counted yet.")
    missing = [x["material"] for x in counted if x["counted_qty"] != x["book_qty"] and not x["reason"]]
    if missing:
        raise HTTPException(status_code=422, detail=f"Say why these differ: {', '.join(missing[:5])}.")
    ref = rules.ref(row["number"])
    today = await _today(conn, auth_context)
    for x in counted:
        diff = Decimal(x["counted_qty"]) - Decimal(x["book_qty"])
        if diff == 0:
            continue
        note = f"{ref} count: {x['reason'].replace('_', ' ')}"
        common = {"project_id": row["project_id"], "site_id": row["site_id"], "material_id": x["material_id"],
                  "unit_id": x["unit_id"], "quantity": abs(diff), "notes": note, "occurred_date": today}
        if diff > 0:
            got = await record_inflow(conn, auth_context, MaterialInflowCreate(**common, movement_reason="ADJUSTMENT_IN",
                                                                                no_order=True), adjust_allowed=True)
            column = "receipt_id"
        else:
            got = await record_outflow(conn, auth_context, MaterialOutflowCreate(**common, movement_reason="ADJUSTMENT_OUT",
                                                                                 allow_negative=True), adjust_allowed=True)
            column = "usage_id"
        await conn.execute(text(f"UPDATE stock_count_lines SET {column} = :id WHERE id = :line"),  # noqa: S608
                           {"id": got["id"], "line": x["id"]})
    await conn.execute(text("UPDATE stock_counts SET status = 'approved', approved_by = :by, approved_at = now() "
                            "WHERE id = :id"), {"by": auth_context.user_id, "id": count_id})
    return _out(auth_context, await _one(conn, auth_context, count_id))


@router.post("/{count_id}/cancel")
async def cancel(count_id: uuid.UUID, body: CancelIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                 conn: AsyncConnection = Depends(get_db_conn)):
    row = await _one(conn, auth_context, count_id, lock=True)
    _authorize_write(auth_context, row["project_id"], row["site_id"])
    if row["status"] != "open":
        raise HTTPException(status_code=409, detail=f"{rules.ref(row['number'])} is {row['status']}.")
    await conn.execute(text("UPDATE stock_counts SET status = 'cancelled', cancel_reason = :r WHERE id = :id"),
                       {"r": body.reason.strip(), "id": count_id})
    return _out(auth_context, await _one(conn, auth_context, count_id))
