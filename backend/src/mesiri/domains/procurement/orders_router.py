"""PRC-06 / PRC-07 / PRC-08: the purchase orders API (dashboard Procurement > Purchase orders).

The office (``may_act_on_material_requests``) places, edits, cancels and closes orders; anyone who can record a
delivery at the order's site can receive against it. Rates and amounts only for the roles that see spending
(SEC-01). An order made from a site's request marks the request ordered and tells the person who asked; when every
line from a request has come, the request is received and they are told again.

PRC-23: a request follows its orders in one place (``requests_follow``): ordered while anything is still to come,
received when everything ordered for it came, waiting again (the asker told) when an order is cancelled or closed
short. A delivery recorded anywhere (Materials, WhatsApp) fills an open order line at its site
(``match_delivery``); one already recorded can be put on an order line or taken off one
(``POST /procurement/orders/deliveries/{receipt_id}/order``). More than an order line still has to come is asked.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_act_on_material_requests, may_view_expenses
from mesiri.domains.materials.router import (
    MaterialInflowCreate,
    _assert_site_in_project,
    _authorize_write,
    _convert_to_stock_unit,
    _resolve_and_validate_material_unit,
    _resolve_project_ids,
    record_inflow,
)
from mesiri.domains.procurement import orders as store
from mesiri.domains.procurement import requests as request_store
from mesiri.domains.procurement.router import _one as one_request
from mesiri.domains.procurement.router import _tell_requester, _visible
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(
    prefix="/procurement/orders",
    tags=["procurement"],
    dependencies=[Depends(require_module("materials"))],
)


class OrderLineIn(BaseModel):
    material_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit_id: uuid.UUID
    #: Per the unit given; converted to the stock unit with the quantity.
    rate: Decimal | None = Field(default=None, ge=0)
    #: The site's request line this order line covers (PRC-22).
    request_line_id: uuid.UUID | None = None
    notes: str | None = None  # filled by the conversion


class OrderCreate(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID
    #: The vendor from the list, or ``supplier`` in words (the company's vendor of that name, made when new).
    vendor_id: uuid.UUID | None = None
    supplier: str | None = Field(default=None, max_length=120)
    lines: list[OrderLineIn] = Field(min_length=1, max_length=50)
    expected_date: datetime.date | None = None
    notes: str | None = Field(default=None, max_length=500)
    confirm_duplicate: bool = False
    #: PRC-30: the number it also goes by outside Mesiri (their paper PO, the supplier's quote, a Tally voucher).
    their_ref: str | None = Field(default=None, max_length=60)


class OrderUpdate(BaseModel):
    expected_date: datetime.date | None = None
    notes: str | None = Field(default=None, max_length=500)
    their_ref: str | None = Field(default=None, max_length=60)
    vendor_id: uuid.UUID | None = None
    supplier: str | None = Field(default=None, max_length=120)
    #: Replaces every line; only while nothing has come against the order.
    lines: list[OrderLineIn] | None = Field(default=None, min_length=1, max_length=50)


class StatusChange(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class ReceiveLine(BaseModel):
    line_id: uuid.UUID
    quantity: Decimal = Field(gt=0)


class Receive(BaseModel):
    lines: list[ReceiveLine] = Field(min_length=1, max_length=50)
    occurred_date: datetime.date
    notes: str | None = Field(default=None, max_length=300)
    #: PRC-23: more than a line still has to come is refused (409 ``more_than_ordered``) unless confirmed.
    confirm_extra: bool = False


class DeliveryOrder(BaseModel):
    #: The open order line the delivery fills; null (and no ``order``) takes it off the order it is on.
    line_id: uuid.UUID | None = None
    #: Or the order by its number as people say it ("PO-0003", "3"): its line for the delivery's material.
    order: str | None = Field(default=None, max_length=20)
    confirm_extra: bool = False


def _office(auth: AuthorizationContext) -> None:
    if not may_act_on_material_requests(auth.role):
        raise HTTPException(status_code=403, detail="Only an admin, owner or project manager can place or change orders.")


async def _vendor(conn: AsyncConnection, auth: AuthorizationContext, vendor_id: uuid.UUID | None,
                  supplier: str | None) -> uuid.UUID:
    if vendor_id is not None:
        row = (await conn.execute(text("SELECT id FROM vendors WHERE id = :id AND organization_id = :org"),
                                  {"id": vendor_id, "org": auth.organization_id})).first()
        if row is None:
            raise HTTPException(status_code=422, detail="vendor_id is not one of this company's vendors")
        return vendor_id
    from mesiri.application.vendors.resolution import vendor_for_name

    found = await vendor_for_name(conn, auth.organization_id, supplier, created_by=auth.user_id)
    if found is None:
        raise HTTPException(status_code=422, detail="Say who the order is from: a vendor or a supplier name.")
    return found


async def _lines(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID,
                 lines: list[OrderLineIn]) -> list[dict]:
    """Each line in its material's stock unit (rate per stock unit), checked like a delivery line; a request line
    must be the company's, in the same project, for the same material."""
    out = []
    for line in lines:
        said_qty = line.quantity
        said = await _convert_to_stock_unit(conn, auth.organization_id, line)
        await _resolve_and_validate_material_unit(conn, auth.organization_id, line.material_id, line.unit_id)
        rate = line.rate
        if rate is not None and said and line.quantity:
            rate = (rate * said_qty / line.quantity).quantize(Decimal("0.01"))  # per stock unit
        if line.request_line_id is not None:
            req = (await conn.execute(text(
                "SELECT l.material_id, r.project_id FROM material_request_lines l JOIN material_requests r "
                "ON r.id = l.request_id WHERE l.id = :id AND l.organization_id = :org"),
                {"id": line.request_line_id, "org": auth.organization_id})).first()
            if req is None or req.project_id != project_id or req.material_id != line.material_id:
                raise HTTPException(status_code=422, detail="request_line_id is not a request line for this project "
                                    "and material")
        out.append({"material_id": line.material_id, "unit_id": line.unit_id, "quantity": line.quantity,
                    "rate": rate, "said": said.split(" = ")[0] if said else None,
                    "request_line_id": line.request_line_id})
    if len({line["material_id"] for line in out}) != len(out):
        raise HTTPException(status_code=422, detail="Each material once per order: add the quantities together.")
    return out


async def _describe(conn: AsyncConnection, auth: AuthorizationContext, rows: list[dict],
                    all_rows: list[dict]) -> list[dict]:
    from mesiri.application.dpr import project_day

    today = await project_day.company_today(conn, auth.organization_id)
    items = store.describe(rows, today=today, with_money=may_view_expenses(auth.role), all_orders=all_rows)
    office = may_act_on_material_requests(auth.role)
    for item in items:
        nothing_came = not item["deliveries"]
        item["may_edit"] = office and item["status"] == "open" and nothing_came
        item["may_cancel"] = office and item["status"] == "open" and nothing_came
        item["may_close"] = office and item["status"] == "part"
        item["may_receive"] = item["status"] in ("open", "part")
        #: PRC-31: a closed or cancelled order can be brought back (the rest is coming after all).
        item["may_reopen"] = office and item["status"] in ("closed", "cancelled")
    return items


async def _one(conn: AsyncConnection, auth: AuthorizationContext, order_id: uuid.UUID, *, lock: bool = False) -> dict:
    project_ids, denied = _resolve_project_ids(auth, None)
    if denied:
        raise HTTPException(status_code=404, detail="Order not found")
    rows = await store.fetch_orders(conn, auth.organization_id, project_ids=project_ids, order_id=order_id, lock=lock)
    rows = [r for r in rows if _visible(auth, r["project_id"], r["site_id"])]
    if not rows:
        raise HTTPException(status_code=404, detail="Order not found")
    all_rows = await store.fetch_orders(conn, auth.organization_id, project_ids=project_ids)
    item = (await _describe(conn, auth, rows, all_rows))[0]
    # PRC-23: deliveries here on no order that may belong to it (put on it with POST /deliveries/{id}/order).
    item["unlinked_deliveries"] = await store.unlinked_deliveries(
        conn, auth.organization_id, site_id=rows[0]["site_id"],
        material_ids=[line["material_id"] for line in rows[0]["lines"]],
        since=rows[0]["created_at"].date()) if item["status"] in ("open", "part") else []
    return item


@router.get("")
async def list_orders(
    status: str = Query(default="open", description="open (open or part), part, received, closed, cancelled, all"),
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    vendor_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Orders the caller can see, the late ones first, with counts for the page's tiles and tabs."""
    if status not in ("open", "part", "received", "closed", "cancelled", "all"):
        raise HTTPException(status_code=422, detail="status is one of open, part, received, closed, cancelled, all")
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied:
        return {"items": [], "counts": {}}
    all_rows = await store.fetch_orders(conn, auth_context.organization_id, project_ids=project_ids)
    rows = [r for r in all_rows if _visible(auth_context, r["project_id"], r["site_id"])]
    if site_id is not None:
        rows = [r for r in rows if r["site_id"] == site_id]
    if vendor_id is not None:
        rows = [r for r in rows if r["vendor_id"] == vendor_id]
    items = await _describe(conn, auth_context, rows, all_rows)

    def tab(item: dict, name: str) -> bool:
        return name == "all" or item["status"] == name or (name == "open" and item["status"] in ("open", "part"))

    counts = {name: sum(1 for i in items if tab(i, name)) for name in ("open", "part", "received", "closed",
                                                                       "cancelled", "all")}
    counts["late"] = sum(1 for i in items if i["urgency"] == "late")
    counts["soon"] = sum(1 for i in items if i["urgency"] == "soon")
    items = [i for i in items if tab(i, status)]
    order = {"late": 0, "soon": 1, "later": 2, "closed": 3}
    items.sort(key=lambda i: (order[i["urgency"]], i["expected_date"] or "9999", -i["number"]))
    return {"items": items, "counts": counts}


@router.get("/{order_id}")
async def get_order(order_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    return await _one(conn, auth_context, order_id)


@router.post("", status_code=201)
async def create_order(body: OrderCreate, auth_context: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    """Place an order. If an open order in the project already has one of these materials, nothing is saved and a
    409 names it (``detail.code`` = ``possible_duplicate``), unless ``confirm_duplicate`` (PRC-07)."""
    _office(auth_context)
    _authorize_write(auth_context, body.project_id, body.site_id)
    await _assert_site_in_project(conn, auth_context.organization_id, body.project_id, body.site_id)
    lines = await _lines(conn, auth_context, body.project_id, body.lines)
    project_ids, _ = _resolve_project_ids(auth_context, body.project_id)
    existing = await store.fetch_orders(conn, auth_context.organization_id, project_ids=project_ids)
    duplicates = store.open_duplicates(existing, body.project_id, {line["material_id"] for line in lines})
    # PRC-23: a site's waiting request for one of these materials, which this order does not cover ("Arun asked").
    asked = await _waiting_requests(conn, auth_context, body.project_id,
                                    {line["material_id"] for line in lines if line["request_line_id"] is None})
    if (duplicates or asked) and not body.confirm_duplicate:
        if duplicates:
            first = duplicates[0]
            what = ", ".join(f"{x['quantity']} {x['unit']} {x['material']} ({x['pending']} still to come)"
                             for x in first["lines"])
            message = (f"{first['created_by_name'] or 'Someone'} already ordered {what} from {first['vendor_name']} "
                       f"for this project ({first['ref']}).")
        else:
            first = asked[0]
            what = ", ".join(f"{x['quantity']} {x['unit']} {x['material']}" for x in first["lines"])
            message = (f"{first['requested_by_name'] or 'Someone'} asked for {what} for {first['site_name']} "
                       f"({first['ref']}, waiting). Order it from the request so they are told.")
        return JSONResponse(status_code=409, content={"detail": {
            "code": "possible_duplicate", "message": message, "duplicates": duplicates, "requests": asked}})
    vendor_id = await _vendor(conn, auth_context, body.vendor_id, body.supplier)
    order_id = await store.insert_order(
        conn, auth_context.organization_id, project_id=body.project_id, site_id=body.site_id, vendor_id=vendor_id,
        expected_date=body.expected_date, notes=(body.notes or "").strip() or None, created_by=auth_context.user_id,
        raised_over_duplicate=bool(duplicates or asked), lines=lines,
        their_ref=(body.their_ref or "").strip() or None)
    item = await _one(conn, auth_context, order_id)
    await requests_follow(conn, auth_context, _request_ids(item))
    return await _one(conn, auth_context, order_id)


@router.patch("/{order_id}")
async def update_order(order_id: uuid.UUID, body: OrderUpdate,
                       auth_context: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    """Change the date, notes or their reference any time the order is open; the supplier and the lines only while
    nothing came."""
    _office(auth_context)
    item = await _one(conn, auth_context, order_id, lock=True)
    if item["status"] not in ("open", "part"):
        raise HTTPException(status_code=409, detail=f"{item['ref']} is {item['status']}; it cannot be changed.")
    fields = body.model_fields_set
    changes: dict = {}
    if "expected_date" in fields:
        changes["expected_date"] = body.expected_date
    if "notes" in fields:
        changes["notes"] = (body.notes or "").strip() or None
    if "their_ref" in fields:
        changes["their_ref"] = (body.their_ref or "").strip() or None
    if body.vendor_id is not None or body.supplier:
        if item["deliveries"]:
            raise HTTPException(status_code=409, detail="Something already came against this order; the supplier "
                                "stays.")
        changes["vendor_id"] = await _vendor(conn, auth_context, body.vendor_id, body.supplier)
    if changes:
        sets = ", ".join(f"{k} = :{k}" for k in changes)
        await conn.execute(text(f"UPDATE purchase_orders SET {sets}, updated_at = now() WHERE id = :id"),  # noqa: S608
                           {**changes, "id": order_id})
    if body.lines is not None:
        if item["deliveries"]:
            raise HTTPException(status_code=409, detail="Something already came against this order; its lines stay. "
                                "Close it and place a new one.")
        lines = await _lines(conn, auth_context, uuid.UUID(item["project_id"]), body.lines)
        await conn.execute(text("DELETE FROM purchase_order_lines WHERE purchase_order_id = :id"), {"id": order_id})
        await store.insert_lines(conn, auth_context.organization_id, order_id, lines)
    after = await _one(conn, auth_context, order_id)
    # A request taken off the order waits again; one put on it is ordered.
    await requests_follow(conn, auth_context, _request_ids(item) | _request_ids(after),
                          note=f"taken off {item['ref']}", released=_request_ids(item) - _request_ids(after))
    return await _one(conn, auth_context, order_id)


@router.post("/{order_id}/cancel")
async def cancel_order(order_id: uuid.UUID, body: StatusChange,
                       auth_context: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    """Take back an order nothing came against (a reason is required). Its requests wait again."""
    _office(auth_context)
    item = await _one(conn, auth_context, order_id, lock=True)
    if item["status"] != "open" or item["deliveries"]:
        raise HTTPException(status_code=409, detail=f"{item['ref']} is {item['status']}; only an order nothing came "
                            "against can be cancelled (close it instead).")
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="Say why it is cancelled (a reason is required).")
    await store.set_status(conn, order_id, "cancelled", auth_context.user_id, reason)
    await requests_follow(conn, auth_context, _request_ids(item), note=f"{item['ref']} cancelled: {reason}")
    return await _one(conn, auth_context, order_id)


@router.post("/{order_id}/close")
async def close_order(order_id: uuid.UUID, body: StatusChange,
                      auth_context: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    """Part of it came and the rest will not: the order is closed with what came (a reason is required)."""
    _office(auth_context)
    item = await _one(conn, auth_context, order_id, lock=True)
    if item["status"] != "part":
        raise HTTPException(status_code=409, detail=f"{item['ref']} is {item['status']}; only a part-received order "
                            "is closed (cancel one nothing came against).")
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="Say why the rest will not come (a reason is required).")
    await store.set_status(conn, order_id, "closed", auth_context.user_id, reason)
    await requests_follow(conn, auth_context, _request_ids(item), note=f"{item['ref']} closed short: {reason}")
    return await _one(conn, auth_context, order_id)


@router.post("/{order_id}/reopen")
async def reopen_order(order_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    """PRC-31: a closed or cancelled order is open again (the rest is coming after all, or it was cancelled by
    mistake). Its requests follow: ordered again, the person who asked told."""
    _office(auth_context)
    item = await _one(conn, auth_context, order_id, lock=True)
    if not item["may_reopen"]:
        raise HTTPException(status_code=409, detail=f"{item['ref']} is {item['status']}; only a closed or cancelled "
                            "order can be opened again.")
    await store.set_status(conn, order_id, "open", auth_context.user_id, f"opened again (was {item['status']})")
    after = await _one(conn, auth_context, order_id)
    await requests_follow(conn, auth_context, _request_ids(after))
    return await _one(conn, auth_context, order_id)


@router.post("/{order_id}/receive", status_code=201)
async def receive_order(order_id: uuid.UUID, body: Receive,
                        auth_context: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn)):
    """Material came against the order: each line is a delivery at the order's site (stock goes up at once), from
    the order's supplier at the order's rate. A request whose lines have all come is received, and its asker told."""
    item = await _one(conn, auth_context, order_id, lock=True)
    if item["status"] not in ("open", "part"):
        raise HTTPException(status_code=409, detail=f"{item['ref']} is {item['status']}; it takes no more deliveries.")
    by_id = {line["id"]: line for line in item["lines"]}
    if len({str(x.line_id) for x in body.lines}) != len(body.lines):
        raise HTTPException(status_code=422, detail="Each order line once per delivery.")
    for got in body.lines:
        line = by_id.get(str(got.line_id))
        if line is None:
            raise HTTPException(status_code=422, detail="A line is not on this order.")
        await record_inflow(conn, auth_context, MaterialInflowCreate(
            project_id=uuid.UUID(item["project_id"]), site_id=uuid.UUID(item["site_id"]),
            material_id=uuid.UUID(line["material_id"]), unit_id=uuid.UUID(line["unit_id"]), quantity=got.quantity,
            movement_reason="RECEIVED", vendor_id=uuid.UUID(item["vendor_id"]), occurred_date=body.occurred_date,
            unit_cost=await _line_rate(conn, got.line_id), notes=(body.notes or "").strip() or f"Against {item['ref']}",
            purchase_order_line_id=got.line_id, confirm_extra=body.confirm_extra))
    # record_inflow already moved the requests (requests_follow, after each line).
    return await _one(conn, auth_context, order_id)


@router.post("/deliveries/{receipt_id}/order")
async def set_delivery_order(receipt_id: uuid.UUID, body: DeliveryOrder,
                             auth_context: AuthorizationContext = Depends(get_auth_context),
                             conn: AsyncConnection = Depends(get_db_conn)):
    """PRC-23: put a delivery already recorded (Materials, WhatsApp) on an open order line at its site, or take it
    off the order it is on (``line_id`` null). Stock does not change; the order's received and its requests do.
    Anyone who can record a delivery at the site; more than the line still has to come is asked."""
    row = (await conn.execute(text(
        "SELECT r.id, r.project_id, r.site_id, r.material_id, r.quantity, r.movement_reason, r.reverses_movement_id, "
        "r.purchase_order_line_id, l.purchase_order_id AS order_id FROM material_receipts r "
        "LEFT JOIN purchase_order_lines l ON l.id = r.purchase_order_line_id "
        "WHERE r.id = :id AND r.organization_id = :org FOR UPDATE OF r"),
        {"id": receipt_id, "org": auth_context.organization_id})).first()
    if row is None or row.site_id is None or not _visible(auth_context, row.project_id, row.site_id):
        raise HTTPException(status_code=404, detail="Delivery not found")
    _authorize_write(auth_context, row.project_id, row.site_id)
    if body.line_id is None and body.order:
        body.line_id = await _line_by_ref(conn, auth_context, body.order, row.material_id)
    taken_back = (await conn.execute(text(
        "SELECT 1 FROM material_usage WHERE reverses_movement_id = :id UNION ALL "
        "SELECT 1 FROM material_receipts WHERE reverses_movement_id = :id"), {"id": receipt_id})).first()
    if row.reverses_movement_id is not None or taken_back is not None:
        raise HTTPException(status_code=409, detail="That delivery was taken back; it fills no order.")
    if row.order_id is not None and body.line_id != row.purchase_order_line_id:
        status = (await conn.execute(text("SELECT status, number FROM purchase_orders WHERE id = :id"),
                                     {"id": row.order_id})).first()
        if status is not None and status.status != "open":
            raise HTTPException(status_code=409, detail=f"{store.ref(status.number)} is {status.status}; its "
                                "deliveries stay on it.")
    if body.line_id is not None:
        try:
            await store.check_delivery_line(conn, auth_context.organization_id, body.line_id, site_id=row.site_id,
                                            material_id=row.material_id, reason=row.movement_reason,
                                            quantity=row.quantity, confirm_extra=body.confirm_extra,
                                            receipt_id=receipt_id)
        except store.OrderRuleError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    await conn.execute(text("UPDATE material_receipts SET purchase_order_line_id = :line WHERE id = :id"),
                       {"line": body.line_id, "id": receipt_id})
    touched = set()
    if row.order_id is not None:
        touched.add(row.order_id)
    if body.line_id is not None:
        new = (await conn.execute(text("SELECT purchase_order_id FROM purchase_order_lines WHERE id = :id"),
                                  {"id": body.line_id})).first()
        touched.add(new.purchase_order_id)  # type: ignore[union-attr]
    for order_id in touched:
        await requests_follow(conn, auth_context, _request_ids(await _one(conn, auth_context, order_id)))
    return {"id": str(receipt_id), "purchase_order_line_id": str(body.line_id) if body.line_id else None,
            "orders": [await _one(conn, auth_context, order_id) for order_id in touched]}


async def _line_by_ref(conn: AsyncConnection, auth: AuthorizationContext, said: str, material_id) -> uuid.UUID:
    digits = "".join(ch for ch in said if ch.isdigit())
    if not digits:
        raise HTTPException(status_code=422, detail=f"'{said}' is not an order number (PO-0003).")
    row = (await conn.execute(text(
        "SELECT l.id FROM purchase_orders o JOIN purchase_order_lines l ON l.purchase_order_id = o.id "
        "WHERE o.organization_id = :org AND o.number = :n AND l.material_id = :m"),
        {"org": auth.organization_id, "n": int(digits), "m": material_id})).first()
    if row is None:
        raise HTTPException(status_code=422, detail=f"{store.ref(int(digits))} has no line for this material.")
    return row.id


async def match_delivery(conn: AsyncConnection, auth: AuthorizationContext, *, site_id: uuid.UUID,
                         material_id: uuid.UUID, quantity: Decimal, vendor_id: uuid.UUID | None,
                         supplier: str | None) -> tuple[dict | None, list[dict]]:
    """PRC-23: which open order line a delivery recorded without one fills. Exactly one open line at the site for
    the material, the delivery within what is still to come, and no other supplier named: that line (the code
    decides; the reply says so). Otherwise none, and the open lines are offered (never matched silently when two
    fit, or when it is more than ordered, or from another shop)."""
    lines = await store.open_lines_at(conn, auth.organization_id, site_id=site_id, material_id=material_id)
    if not lines:
        return None, []
    if len(lines) == 1:
        line = lines[0]
        same_shop = vendor_id is None or str(vendor_id) == line["vendor_id"]
        if same_shop and supplier and vendor_id is None:
            same_shop = supplier.strip().casefold() == line["vendor_name"].strip().casefold()
        if same_shop and quantity <= Decimal(line["pending"]):
            return line, []
    return None, lines


async def after_delivery(conn: AsyncConnection, auth: AuthorizationContext, line_id: uuid.UUID) -> dict:
    """The order a delivery just filled, as the delivery's result says it ("PO-0003: 150 of 160 came"), after its
    requests followed it."""
    order_id = (await conn.execute(text("SELECT purchase_order_id FROM purchase_order_lines WHERE id = :id"),
                                   {"id": line_id})).scalar_one()
    rows = await store.fetch_orders(conn, auth.organization_id, project_ids=None, order_id=order_id)
    item = store.describe(rows, today=datetime.date.today(), with_money=False, all_orders=[])[0]
    await requests_follow(conn, auth, _request_ids(item))
    line = next(x for x in item["lines"] if x["id"] == str(line_id))
    return {"id": item["id"], "ref": item["ref"], "vendor_name": item["vendor_name"], "status": item["status"],
            "line_id": str(line_id), "material": line["material"], "unit": line["unit"],
            "quantity": line["quantity"], "received": line["received"], "pending": line["pending"],
            "extra": line["extra"]}


async def _line_rate(conn: AsyncConnection, line_id: uuid.UUID) -> Decimal | None:
    """The agreed rate, read here so it reaches stock and spend even when the caller may not see rates."""
    row = (await conn.execute(text("SELECT rate FROM purchase_order_lines WHERE id = :id"), {"id": line_id})).first()
    return row.rate if row else None


def _request_ids(item: dict) -> set[uuid.UUID]:
    return {uuid.UUID(line["request"]["id"]) for line in item["lines"] if line["request"]}


async def _waiting_requests(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID,
                            material_ids: set) -> list[dict]:
    """Waiting requests in the project for any of these materials (what a new order should be made from)."""
    if not material_ids:
        return []
    rows = await request_store.fetch_requests(conn, auth.organization_id, project_ids={project_id})
    waiting = [r for r in rows if r["status"] == request_store.WAITING]
    return [d for d in request_store.open_duplicates(waiting, project_id, material_ids)]


async def requests_follow(conn: AsyncConnection, auth: AuthorizationContext, request_ids: set[uuid.UUID], *,
                          note: str | None = None, released: set[uuid.UUID] = frozenset()) -> None:  # type: ignore[assignment]
    """PRC-23: the one place a request follows its purchase orders. Only requests waiting or ordered, and only ones an
    order ever covered (a request ordered by hand, or sent from another site, is left as it is):

    * anything still to come on an open order: ordered (from waiting; the asker told);
    * nothing to come, every line of the request on an order and every order line for it came in full: received;
    * otherwise (cancelled, closed short, a line never ordered): waiting again, the asker told with ``note`` and what
      is still missing. ``released``: requests just taken off an order's lines (no order line points at them now).
    """
    for rid in request_ids:
        found = await request_store.fetch_requests(conn, auth.organization_id, project_ids=None, request_id=rid)
        if not found or found[0]["status"] not in (request_store.WAITING, "ordered"):
            continue
        req = found[0]
        lines = [x for x in await store.order_lines_for_requests(conn, auth.organization_id,
                                                                 project_ids={req["project_id"]})
                 if x["request_id"] == rid]
        if not lines and not (rid in released and req["status"] == "ordered"):
            continue
        live = [x for x in lines if x["status"] != "cancelled"]
        coming = [x for x in live if x["pending"] > 0]
        status = req["status"]
        target: str | None = None
        message: str | None = None
        if coming:
            if status == request_store.WAITING:
                target = "ordered"
                message = ", ".join(sorted({f"{store.ref(x['number'])}, {x['vendor_name']}" for x in coming}))
        else:
            missing = []
            for line in req["lines"]:
                its = [x for x in live if x["request_line_id"] == line["id"]]
                came = sum((x["received"] for x in its), Decimal(0))
                # Covered: what came is what was asked, or every order for it came in full (an order may be for
                # less than asked when some was already at the site).
                if not its or (came < Decimal(line["quantity"]) and any(x["received"] < x["quantity"] for x in its)):
                    missing.append(f"{store._num(Decimal(line['quantity']) - came)} {line['unit']} {line['material']}")
            if not missing:
                target = "done"
            elif status == "ordered":
                target = request_store.WAITING
                message = "; ".join(p for p in (note, f"still to order: {', '.join(missing)}") if p)
        if target is None:
            continue
        await request_store.set_status(conn, rid, target, auth.user_id, message)
        try:
            await _tell_requester(conn, auth, await one_request(conn, auth, rid), target, message,
                                  wording="received" if target == "done" else None)
        except HTTPException:
            continue  # the request is outside what this person can see: it still follows the order
