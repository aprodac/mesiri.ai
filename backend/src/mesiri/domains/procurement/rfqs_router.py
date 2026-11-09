"""PRC-40..43: Procurement > Quotations -- the routes. Storage and the comparison rule are in ``rfqs.py``.

``GET  /procurement/rfqs``                         the RFQs (status open | ready | awarded | closed | all)
``GET  /procurement/rfqs/{id}``                    one RFQ with its comparison sheet
``POST /procurement/rfqs``                         ask for quotes (lines, or a site's request; suppliers)
``PATCH /procurement/rfqs/{id}``                   change dates / terms / notes while open
``POST /procurement/rfqs/{id}/suppliers``          add a supplier to ask
``POST /procurement/rfqs/{id}/suppliers/{rv}/sent``     the RFQ was sent to them (WhatsApp, print)
``POST /procurement/rfqs/{id}/quotes``             record (or revise) a supplier's quote
``POST /procurement/rfqs/{id}/suppliers/{rv}/decline`` the supplier will not quote
``POST /procurement/rfqs/{id}/award``              choose, and place the orders (the order route's own rules)
``POST /procurement/rfqs/{id}/close`` / ``cancel``  no order from it

Who: the office (admin, owner, project manager) asks, records and awards, as for orders (PRC-12 may change it);
rates are shown to the roles that see spending (D-CC4). Quotations and orders share one duplicate check: an award
goes through ``create_order``.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_act_on_material_requests, may_view_expenses
from mesiri.domains.materials.router import (
    _assert_site_in_project,
    _authorize_write,
    _convert_to_stock_unit,
    _resolve_and_validate_material_unit,
    _resolve_project_ids,
)
from mesiri.domains.procurement import gst
from mesiri.domains.procurement import rates as rate_store
from mesiri.domains.procurement import requests as request_store
from mesiri.domains.procurement import rfqs as store
from mesiri.domains.procurement.orders_router import OrderCreate, OrderLineIn, _vendor, create_order
from mesiri.domains.procurement.router import _one as one_request
from mesiri.domains.procurement.router import _visible
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(prefix="/procurement/rfqs", tags=["procurement"], dependencies=[Depends(require_module("materials"))])


class RfqLineIn(BaseModel):
    material_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit_id: uuid.UUID
    request_line_id: uuid.UUID | None = None
    notes: str | None = None  # filled by the unit conversion


class SupplierIn(BaseModel):
    vendor_id: uuid.UUID | None = None
    supplier: str | None = Field(default=None, max_length=120)


class RfqCreate(BaseModel):
    """Lines, or ``request_id`` (a site's request: its site and what is still to buy); suppliers by id or in words."""

    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    lines: list[RfqLineIn] = Field(default_factory=list, max_length=50)
    request_id: uuid.UUID | None = None
    vendor_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    #: Suppliers in their words (the company's vendor of that name, made when new): the WhatsApp form.
    suppliers: list[str] = Field(default_factory=list, max_length=20)
    due_date: datetime.date | None = None
    needed_by: datetime.date | None = None
    terms: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=500)


class RfqUpdate(BaseModel):
    due_date: datetime.date | None = None
    needed_by: datetime.date | None = None
    terms: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=500)


class QuoteLineIn(BaseModel):
    #: The RFQ line, or the material (its line on this RFQ).
    rfq_line_id: uuid.UUID | None = None
    material_id: uuid.UUID | None = None
    rate: Decimal = Field(ge=0)
    #: The unit the rate is per; left out: the line's (stock) unit.
    unit_id: uuid.UUID | None = None
    gst_percent: Decimal | None = Field(default=None, ge=0, le=100)
    rate_includes_gst: bool | None = None
    brand: str | None = Field(default=None, max_length=80)
    remark: str | None = Field(default=None, max_length=200)


class QuoteIn(BaseModel):
    vendor_id: uuid.UUID | None = None
    supplier: str | None = Field(default=None, max_length=120)
    lines: list[QuoteLineIn] = Field(min_length=1, max_length=50)
    #: GST for every line that does not say its own (most quotes print one).
    gst_percent: Decimal | None = Field(default=None, ge=0, le=100)
    rates_include_gst: bool | None = None
    valid_until: datetime.date | None = None
    delivery_days: int | None = Field(default=None, ge=0, le=365)
    payment_days: int | None = Field(default=None, ge=0, le=365)
    their_ref: str | None = Field(default=None, max_length=60)
    notes: str | None = Field(default=None, max_length=500)
    source: Literal["web", "whatsapp", "photo"] = "web"


class Decline(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class Pick(BaseModel):
    rfq_line_id: uuid.UUID
    vendor_id: uuid.UUID


class Award(BaseModel):
    """``lowest_total``: every line from the cheapest supplier who quoted all; ``lowest_per_line``: each line from its
    cheapest; ``picks``: chosen per line (a line left out is not ordered). ``reason``: required when a pick is not the
    cheapest for its line (kept on the line)."""

    mode: Literal["lowest_total", "lowest_per_line", "picks"] = "picks"
    picks: list[Pick] = Field(default_factory=list, max_length=50)
    reason: str | None = Field(default=None, max_length=300)
    expected_date: datetime.date | None = None
    confirm_duplicate: bool = False


class StatusChange(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


def _office(auth: AuthorizationContext) -> None:
    if not may_act_on_material_requests(auth.role):
        raise HTTPException(status_code=403, detail="Only an admin, owner or project manager can ask for or record quotes.")


async def _today(conn: AsyncConnection, auth: AuthorizationContext) -> datetime.date:
    from mesiri.application.dpr import project_day

    return await project_day.company_today(conn, auth.organization_id)


async def _last_paid(conn: AsyncConnection, auth: AuthorizationContext, rows: list[dict],
                     project_ids: set[uuid.UUID] | None) -> dict[str, dict]:
    """Per material on these RFQs, the last delivery's cost rate (the Rates rule), to set each quote against."""
    material_ids = list({line["material_id"] for r in rows for line in r["lines"]})
    if not material_ids:
        return {}
    today = await _today(conn, auth)
    last = await rate_store.fetch_before(conn, auth.organization_id, project_ids=project_ids,
                                         before=today + datetime.timedelta(days=1), material_ids=material_ids)
    return {str(mid): {"rate": gst.money(rate_store.cost_rate(r)), "date": r["occurred_date"].isoformat(),
                       "vendor_name": rate_store.vendor_name(r)} for mid, r in last.items()}


async def _describe(conn: AsyncConnection, auth: AuthorizationContext, rows: list[dict],
                    project_ids: set[uuid.UUID] | None) -> list[dict]:
    today = await _today(conn, auth)
    money = may_view_expenses(auth.role)
    paid = await _last_paid(conn, auth, rows, project_ids) if money else {}
    office = may_act_on_material_requests(auth.role)
    out = []
    for r in rows:
        item = store.describe(r, today, with_money=money, last_paid=paid)
        live = item["status"] in ("open", "ready")
        item["may_edit"] = item["may_award"] = item["may_cancel"] = office and live
        item["may_record"] = office and live
        out.append(item)
    return out


async def _rows(conn: AsyncConnection, auth: AuthorizationContext, rfq_id: uuid.UUID | None = None, *,
                lock: bool = False) -> tuple[list[dict], set[uuid.UUID] | None]:
    project_ids, denied = _resolve_project_ids(auth, None)
    if denied:
        return [], project_ids
    rows = await store.fetch_rfqs(conn, auth.organization_id, project_ids=project_ids, rfq_id=rfq_id, lock=lock)
    return [r for r in rows if _visible(auth, r["project_id"], r["site_id"])], project_ids


async def _one(conn: AsyncConnection, auth: AuthorizationContext, rfq_id: uuid.UUID, *, lock: bool = False) -> dict:
    rows, project_ids = await _rows(conn, auth, rfq_id, lock=lock)
    if not rows:
        raise HTTPException(status_code=404, detail="RFQ not found")
    return (await _describe(conn, auth, rows, project_ids))[0]


def _live(item: dict) -> None:
    if item["status"] not in ("open", "ready"):
        raise HTTPException(status_code=409, detail=f"{item['ref']} is {item['status']}; it takes no more changes.")


@router.get("")
async def list_rfqs(
    status: Literal["open", "ready", "awarded", "closed", "cancelled", "live", "all"] = Query(default="all"),
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """The RFQs, newest first. ``live``: open or ready (waiting for quotes, or ready to compare)."""
    rows, project_ids = await _rows(conn, auth_context)
    rows = [r for r in rows if (project_id is None or r["project_id"] == project_id)
            and (site_id is None or r["site_id"] == site_id)]
    items = await _describe(conn, auth_context, rows, project_ids)
    if status == "live":
        items = [i for i in items if i["status"] in ("open", "ready")]
    elif status != "all":
        items = [i for i in items if i["status"] == status]
    return {"items": items, "total": len(items)}


@router.get("/{rfq_id}")
async def get_rfq(rfq_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                  conn: AsyncConnection = Depends(get_db_conn)):
    return await _one(conn, auth_context, rfq_id)


async def _lines(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID,
                 lines: list[RfqLineIn]) -> list[dict]:
    out, seen = [], set()
    for line in lines:
        said = await _convert_to_stock_unit(conn, auth.organization_id, line)
        await _resolve_and_validate_material_unit(conn, auth.organization_id, line.material_id, line.unit_id)
        if line.material_id in seen:
            raise HTTPException(status_code=422, detail="Each material once per RFQ: add the quantities together.")
        seen.add(line.material_id)
        if line.request_line_id is not None:
            req = (await conn.execute(text(
                "SELECT l.material_id, r.project_id FROM material_request_lines l JOIN material_requests r "
                "ON r.id = l.request_id WHERE l.id = :id AND l.organization_id = :org"),
                {"id": line.request_line_id, "org": auth.organization_id})).first()
            if req is None or req.project_id != project_id or req.material_id != line.material_id:
                raise HTTPException(status_code=422, detail="request_line_id is not a request line for this project "
                                    "and material")
        out.append({"material_id": line.material_id, "unit_id": line.unit_id, "quantity": line.quantity,
                    "said": said.split(" = ")[0] if said else None, "request_line_id": line.request_line_id})
    return out


@router.post("", status_code=201)
async def create_rfq(body: RfqCreate, auth_context: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    """Ask suppliers for quotes. From a site's request (``request_id``): its site, and per item what is still to buy."""
    _office(auth_context)
    if body.request_id is not None:
        if body.lines:
            raise HTTPException(status_code=422, detail="Quotes for a request take its items from the request.")
        req = await one_request(conn, auth_context, body.request_id)
        if req["status"] not in (request_store.WAITING, "ordered"):
            raise HTTPException(status_code=409, detail=f"{req['ref']} is {req['status']}; it is not bought now.")
        body.project_id, body.site_id = uuid.UUID(req["project_id"]), uuid.UUID(req["site_id"])
        body.lines = [RfqLineIn(material_id=uuid.UUID(x["material_id"]), unit_id=uuid.UUID(x["unit_id"]),
                                quantity=Decimal(x["to_buy"]) if Decimal(x["to_buy"]) > 0 else Decimal(x["quantity"]),
                                request_line_id=uuid.UUID(x["id"])) for x in req["lines"]]
        if body.needed_by is None and req.get("needed_by"):
            body.needed_by = datetime.date.fromisoformat(req["needed_by"])
    if not body.lines:
        raise HTTPException(status_code=422, detail="Say what the quotes are for: at least one item.")
    if body.project_id is None or body.site_id is None:
        raise HTTPException(status_code=422, detail="Say which project and site it is delivered to.")
    _authorize_write(auth_context, body.project_id, body.site_id)
    await _assert_site_in_project(conn, auth_context.organization_id, body.project_id, body.site_id)
    lines = await _lines(conn, auth_context, body.project_id, body.lines)
    vendor_ids: list[uuid.UUID] = []
    for vid in body.vendor_ids:
        vendor_ids.append(await _vendor(conn, auth_context, vid, None))
    for name in body.suppliers:
        if name.strip():
            vendor_ids.append(await _vendor(conn, auth_context, None, name.strip()))
    rfq_id = await store.insert_rfq(
        conn, auth_context.organization_id, project_id=body.project_id, site_id=body.site_id,
        request_id=body.request_id, due_date=body.due_date, needed_by=body.needed_by,
        terms=(body.terms or "").strip() or None, notes=(body.notes or "").strip() or None,
        created_by=auth_context.user_id, lines=lines, vendor_ids=list(dict.fromkeys(vendor_ids)))
    return await _one(conn, auth_context, rfq_id)


@router.patch("/{rfq_id}")
async def update_rfq(rfq_id: uuid.UUID, body: RfqUpdate, auth_context: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    _office(auth_context)
    item = await _one(conn, auth_context, rfq_id, lock=True)
    _live(item)
    fields = body.model_dump(exclude_unset=True)
    if fields:
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        await conn.execute(text(f"UPDATE rfqs SET {sets}, updated_at = now() WHERE id = :id"),  # noqa: S608 -- model keys
                           {**{k: (v.strip() or None) if isinstance(v, str) else v for k, v in fields.items()}, "id": rfq_id})
    return await _one(conn, auth_context, rfq_id)


@router.post("/{rfq_id}/suppliers", status_code=201)
async def add_supplier(rfq_id: uuid.UUID, body: SupplierIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    _office(auth_context)
    _live(await _one(conn, auth_context, rfq_id, lock=True))
    vendor_id = await _vendor(conn, auth_context, body.vendor_id, body.supplier)
    await store.add_vendor(conn, auth_context.organization_id, rfq_id, vendor_id)
    return await _one(conn, auth_context, rfq_id)


async def _rfq_vendor(conn: AsyncConnection, rfq_id: uuid.UUID, rv_id: uuid.UUID) -> None:
    row = (await conn.execute(text("SELECT 1 FROM rfq_vendors WHERE id = :id AND rfq_id = :rfq"),
                              {"id": rv_id, "rfq": rfq_id})).first()
    if row is None:
        raise HTTPException(status_code=404, detail="That supplier is not on this RFQ.")


@router.post("/{rfq_id}/suppliers/{rv_id}/sent")
async def mark_sent(rfq_id: uuid.UUID, rv_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    _office(auth_context)
    _live(await _one(conn, auth_context, rfq_id))
    await _rfq_vendor(conn, rfq_id, rv_id)
    await conn.execute(text("UPDATE rfq_vendors SET sent_at = COALESCE(sent_at, now()) WHERE id = :id"), {"id": rv_id})
    return await _one(conn, auth_context, rfq_id)


@router.post("/{rfq_id}/suppliers/{rv_id}/decline")
async def decline(rfq_id: uuid.UUID, rv_id: uuid.UUID, body: Decline,
                  auth_context: AuthorizationContext = Depends(get_auth_context),
                  conn: AsyncConnection = Depends(get_db_conn)):
    _office(auth_context)
    _live(await _one(conn, auth_context, rfq_id, lock=True))
    await _rfq_vendor(conn, rfq_id, rv_id)
    await conn.execute(text("DELETE FROM rfq_quote_lines WHERE rfq_vendor_id = :id"), {"id": rv_id})
    await conn.execute(text("UPDATE rfq_vendors SET status = 'declined', decline_reason = :r WHERE id = :id"),
                       {"id": rv_id, "r": (body.reason or "").strip() or None})
    return await _one(conn, auth_context, rfq_id)


async def _rate_per_line_unit(conn: AsyncConnection, auth: AuthorizationContext, line: dict,
                              q: QuoteLineIn) -> Decimal:
    """A rate said per another unit (a tonne for steel kept in kg, a load for sand in cft) per the line's unit."""
    if q.unit_id is None or str(q.unit_id) == line["unit_id"]:
        return q.rate
    probe = RfqLineIn(material_id=uuid.UUID(line["material_id"]), quantity=Decimal(1), unit_id=q.unit_id)
    await _convert_to_stock_unit(conn, auth.organization_id, probe)
    if str(probe.unit_id) != line["unit_id"] or not probe.quantity:
        raise HTTPException(status_code=422, detail=f"Say the {line['material']} rate per {line['unit']}: that unit "
                            "cannot be converted.")
    return (q.rate / Decimal(probe.quantity)).quantize(Decimal("0.01"))


@router.post("/{rfq_id}/quotes", status_code=201)
async def record_quote(rfq_id: uuid.UUID, body: QuoteIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    """A supplier's quote (a revised one replaces what it said for those lines). A supplier not asked yet is added."""
    _office(auth_context)
    item = await _one(conn, auth_context, rfq_id, lock=True)
    _live(item)
    vendor_id = await _vendor(conn, auth_context, body.vendor_id, body.supplier)
    rv_id = await store.add_vendor(conn, auth_context.organization_id, rfq_id, vendor_id)
    by_id = {line["id"]: line for line in item["lines"]}
    by_material = {line["material_id"]: line for line in item["lines"]}
    lines, seen = [], set()
    for q in body.lines:
        line = by_id.get(str(q.rfq_line_id)) if q.rfq_line_id else by_material.get(str(q.material_id))
        if line is None:
            raise HTTPException(status_code=422, detail="A quoted item is not on this RFQ.")
        if line["id"] in seen:
            raise HTTPException(status_code=422, detail=f"{line['material']} is quoted twice.")
        seen.add(line["id"])
        pct = q.gst_percent if q.gst_percent is not None else body.gst_percent
        incl = q.rate_includes_gst if q.rate_includes_gst is not None else body.rates_include_gst
        lines.append({"rfq_line_id": uuid.UUID(line["id"]), "rate": await _rate_per_line_unit(conn, auth_context, line, q),
                      "gst_percent": pct, "rate_includes_gst": incl, "brand": (q.brand or "").strip() or None,
                      "remark": (q.remark or "").strip() or None})
    await store.save_quote(conn, auth_context.organization_id, rv_id, lines=lines, valid_until=body.valid_until,
                           delivery_days=body.delivery_days, payment_days=body.payment_days,
                           their_ref=(body.their_ref or "").strip() or None, notes=(body.notes or "").strip() or None,
                           source=body.source, user_id=auth_context.user_id)
    return await _one(conn, auth_context, rfq_id)


def _picks(item: dict, body: Award) -> list[tuple[dict, dict]]:
    """(line, chosen quote) per line to order, by the mode. Refused when a line has no quote from the chosen one."""
    supplier = {s["rfq_vendor_id"]: s for s in item["suppliers"]}
    out = []
    if body.mode == "lowest_total":
        best = item["lowest_total"]
        if best is None:
            raise HTTPException(status_code=422, detail="No supplier quoted every item: choose per item.")
        for line in item["lines"]:
            out.append((line, next(q for q in line["quotes"] if q["rfq_vendor_id"] == best["rfq_vendor_id"])))
        return out
    if body.mode == "lowest_per_line":
        for line in item["lines"]:
            if line["quotes"]:
                out.append((line, line["quotes"][0]))
        if not out:
            raise HTTPException(status_code=422, detail="No quotes yet.")
        return out
    if not body.picks:
        raise HTTPException(status_code=422, detail="Choose a supplier for at least one item.")
    lines = {line["id"]: line for line in item["lines"]}
    vendor_rv = {s["vendor_id"]: s["rfq_vendor_id"] for s in item["suppliers"]}
    for pick in body.picks:
        line = lines.get(str(pick.rfq_line_id))
        rv = vendor_rv.get(str(pick.vendor_id))
        quote = next((q for q in line["quotes"] if q["rfq_vendor_id"] == rv), None) if line and rv else None
        if quote is None:
            name = supplier.get(rv or "", {}).get("name", "That supplier")
            raise HTTPException(status_code=422, detail=f"{name} did not quote {line['material'] if line else 'that item'}.")
        out.append((line, quote))
    return out


@router.post("/{rfq_id}/award", status_code=201)
async def award(rfq_id: uuid.UUID, body: Award, auth_context: AuthorizationContext = Depends(get_auth_context),
                conn: AsyncConnection = Depends(get_db_conn)):
    """Choose and order: one purchase order per chosen supplier, at the quoted rate and GST, each line linked to the
    request it covers (so the site is told), through the order route's own checks (a possible duplicate is a 409
    unless ``confirm_duplicate``; nothing is saved then). Choosing a supplier that was not the cheapest for an item
    needs a ``reason``."""
    _office(auth_context)
    if not may_view_expenses(auth_context.role):
        raise HTTPException(status_code=403, detail="Choosing a quote needs a role that sees rates.")
    item = await _one(conn, auth_context, rfq_id, lock=True)
    _live(item)
    chosen = _picks(item, body)
    not_cheapest = [line["material"] for line, q in chosen if line["quotes"] and q["rfq_vendor_id"] != line["quotes"][0]["rfq_vendor_id"]]
    reason = (body.reason or "").strip() or None
    if not_cheapest and not reason:
        return JSONResponse(status_code=422, content={"detail": {
            "code": "reason_needed", "message": f"Not the cheapest for {', '.join(not_cheapest)}: say why (quality, "
            "delivery time, credit, brand).", "items": not_cheapest}})
    supplier = {s["rfq_vendor_id"]: s for s in item["suppliers"]}
    by_vendor: dict[str, list[tuple[dict, dict]]] = {}
    for line, q in chosen:
        by_vendor.setdefault(q["rfq_vendor_id"], []).append((line, q))
    orders = []
    for rv, picked in by_vendor.items():
        s = supplier[rv]
        days = s["delivery_days"]
        today = await _today(conn, auth_context)
        expected = body.expected_date or (today + datetime.timedelta(days=days) if days is not None else None)
        result = await create_order(OrderCreate(
            project_id=uuid.UUID(item["project_id"]), site_id=uuid.UUID(item["site_id"]), vendor_id=uuid.UUID(s["vendor_id"]),
            lines=[OrderLineIn(material_id=uuid.UUID(line["material_id"]), quantity=Decimal(line["quantity"]),
                               unit_id=uuid.UUID(line["unit_id"]), rate=Decimal(q["rate_entered"]),
                               gst_percent=Decimal(q["gst_percent"]) if q["gst_percent"] is not None else None,
                               rate_includes_gst=q["rate_includes_gst"],
                               request_line_id=uuid.UUID(line["request_line_id"]) if line["request_line_id"] else None)
                   for line, q in picked],
            expected_date=expected, their_ref=s["their_ref"], notes=f"From {item['ref']}",
            confirm_duplicate=body.confirm_duplicate), auth_context, conn)
        if isinstance(result, JSONResponse):  # a possible duplicate: undo every order of this award
            import json

            raise HTTPException(status_code=result.status_code, detail=json.loads(bytes(result.body))["detail"])
        order_id = uuid.UUID(result["id"])
        await conn.execute(text("UPDATE purchase_orders SET rfq_id = :rfq WHERE id = :id"), {"rfq": rfq_id, "id": order_id})
        for line, q in picked:
            await conn.execute(text(
                "UPDATE purchase_order_lines SET quote_line_id = :ql WHERE purchase_order_id = :o AND material_id = :m"),
                {"ql": uuid.UUID(q["quote_line_id"]), "o": order_id, "m": uuid.UUID(line["material_id"])})
            why = reason if line["material"] in not_cheapest else None
            await conn.execute(text("UPDATE rfq_lines SET awarded_quote_line_id = :ql, award_reason = :why WHERE id = :id"),
                               {"ql": uuid.UUID(q["quote_line_id"]), "why": why, "id": uuid.UUID(line["id"])})
        from mesiri.domains.procurement import orders as order_store

        await order_store.log(conn, auth_context.organization_id, order_id, "rfq",
                              f"Placed from {item['ref']} ({s['name']}'s quote)", auth_context.user_id)
        orders.append(result["ref"])
    await store.set_status(conn, rfq_id, "awarded", auth_context.user_id, f"Ordered: {', '.join(orders)}")
    return await _one(conn, auth_context, rfq_id)


@router.post("/{rfq_id}/close")
async def close_rfq(rfq_id: uuid.UUID, body: StatusChange, auth_context: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    """No order from it (prices only, or bought another way); the quotes stay for Rates and the supplier's price list."""
    _office(auth_context)
    _live(await _one(conn, auth_context, rfq_id, lock=True))
    await store.set_status(conn, rfq_id, "closed", auth_context.user_id, (body.reason or "").strip() or None)
    return await _one(conn, auth_context, rfq_id)


@router.post("/{rfq_id}/cancel")
async def cancel_rfq(rfq_id: uuid.UUID, body: StatusChange, auth_context: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    _office(auth_context)
    _live(await _one(conn, auth_context, rfq_id, lock=True))
    await store.set_status(conn, rfq_id, "cancelled", auth_context.user_id, (body.reason or "").strip() or None)
    return await _one(conn, auth_context, rfq_id)
