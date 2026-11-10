"""PRC-46: Procurement > Returns -- the routes. Rules and reads in ``returns.py``.

``GET  /procurement/returns``                 the returns (status waiting | sent | settled | cancelled | open | all)
``GET  /procurement/returns/sources``         what can go back: a GRN's rejected quantities, a delivery, or a
                                              supplier's recent deliveries at a site
``GET  /procurement/returns/{id}``            one return with its debit note, lines and timeline
``POST /procurement/returns``                 send material back: stock down (RETURN_TO_VENDOR), a debit note
``POST /procurement/returns/{id}/sent``       the supplier collected it
``POST /procurement/returns/{id}/settle``     settled by a replacement delivery or by credit (bill / payment)
``POST /procurement/returns/{id}/cancel``     not going back after all (only while waiting): the stock comes back
``GET  /procurement/returns/{id}/photos``     the photos, as short-lived links

Who: the office (admin, owner, project manager) records and settles, as for orders (PRC-12 may change it); the
money (rates, the debit note's value) only for the roles that see spending (D-CC4). Anyone who sees the site sees
its returns.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_act_on_material_requests, may_view_expenses
from mesiri.domains.materials.router import (
    MaterialOutflowCreate,
    _assert_site_in_project,
    _authorize_write,
    _convert_to_stock_unit,
    _resolve_and_validate_material_unit,
    _resolve_project_ids,
    record_outflow,
    reverse_material_record,
)
from mesiri.domains.procurement import returns as store
from mesiri.domains.procurement.orders_router import ChallanPhoto, _vendor
from mesiri.domains.procurement.router import _visible
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri_contracts.common.storage import ObjectStoragePort

router = APIRouter(prefix="/procurement/returns", tags=["procurement"],
                   dependencies=[Depends(require_module("materials"))])

Reason = Literal["damaged", "short", "wrong_size", "excess", "quality_failed"]


class ReturnLineIn(BaseModel):
    material_id: uuid.UUID | None = None
    quantity: Decimal = Field(gt=0)
    #: The unit the quantity was said in; left out: the material's stock unit. Converted as a delivery is.
    unit_id: uuid.UUID | None = None
    #: Per stock unit; left out: the delivery's (or the order line's, for a GRN's rejected quantity).
    rate: Decimal | None = Field(default=None, ge=0)
    gst_percent: Decimal | None = Field(default=None, ge=0, le=100)
    rate_includes_gst: bool | None = None
    reason: Reason
    #: The delivery it came from (in stock): it leaves stock.
    receipt_id: uuid.UUID | None = None
    #: A GRN line's rejected quantity (never in stock): nothing leaves stock.
    grn_line_id: uuid.UUID | None = None


class ReturnIn(BaseModel):
    vendor_id: uuid.UUID | None = None
    #: The supplier in words (the company's vendor of that name): the WhatsApp form.
    supplier: str | None = Field(default=None, max_length=120)
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    lines: list[ReturnLineIn] = Field(min_length=1, max_length=50)
    returned_on: datetime.date | None = None
    notes: str | None = Field(default=None, max_length=500)
    photos: list[ChallanPhoto] = Field(default_factory=list, max_length=4)
    source: Literal["web", "whatsapp"] = "web"


class SentIn(BaseModel):
    sent_on: datetime.date | None = None
    collected_by: str | None = Field(default=None, max_length=120)


class SettleIn(BaseModel):
    how: Literal["replacement", "credit"]
    #: replacement: the delivery that replaced it (same supplier and site); optional.
    receipt_id: uuid.UUID | None = None
    #: credit: the supplier's bill (expense) or payment it was taken off; optional.
    expense_id: uuid.UUID | None = None
    payment_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=300)
    settled_on: datetime.date | None = None


class CancelIn(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


def _office(auth: AuthorizationContext) -> None:
    if not may_act_on_material_requests(auth.role):
        raise HTTPException(status_code=403, detail="Only an admin, owner or project manager can record a return.")


async def _today(conn: AsyncConnection, auth: AuthorizationContext) -> datetime.date:
    from mesiri.application.dpr import project_day

    return await project_day.company_today(conn, auth.organization_id)


async def _rows(conn: AsyncConnection, auth: AuthorizationContext, return_id: uuid.UUID | None = None, *,
                vendor_id: uuid.UUID | None = None, lock: bool = False) -> list[dict]:
    project_ids, denied = _resolve_project_ids(auth, None)
    if denied:
        return []
    rows = await store.fetch(conn, auth.organization_id, project_ids=project_ids, return_id=return_id,
                             vendor_id=vendor_id, lock=lock)
    return [r for r in rows if _visible(auth, r["project_id"], r["site_id"])]


def _out(auth: AuthorizationContext, row: dict) -> dict:
    item = store.describe(row, with_money=may_view_expenses(auth.role))
    office = may_act_on_material_requests(auth.role)
    item["may_send"] = office and row["status"] == "waiting"
    item["may_settle"] = office and row["status"] in ("waiting", "sent")
    item["may_cancel"] = office and row["status"] == "waiting"
    return item


async def _one(conn: AsyncConnection, auth: AuthorizationContext, return_id: uuid.UUID, *, lock: bool = False) -> dict:
    rows = await _rows(conn, auth, return_id, lock=lock)
    if not rows:
        raise HTTPException(status_code=404, detail="Return not found")
    return rows[0]


@router.get("")
async def list_returns(
    status: Literal["waiting", "sent", "settled", "cancelled", "open", "all"] = Query(default="all"),
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    vendor_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """The returns, newest first, with the page's figures: waiting for pickup, what suppliers owe back on returns not
    settled (money roles), and returns this month. ``open``: waiting or sent."""
    rows = await _rows(conn, auth_context, vendor_id=vendor_id)
    rows = [r for r in rows if (project_id is None or r["project_id"] == project_id)
            and (site_id is None or r["site_id"] == site_id)]
    today = await _today(conn, auth_context)
    money = may_view_expenses(auth_context.role)
    owed = sum((store.totals(r)["total"] for r in rows if r["status"] in ("waiting", "sent")), Decimal(0))
    counts = {
        "waiting": sum(1 for r in rows if r["status"] == "waiting"),
        "sent": sum(1 for r in rows if r["status"] == "sent"),
        "this_month": sum(1 for r in rows if r["status"] != "cancelled" and r["returned_on"].year == today.year
                          and r["returned_on"].month == today.month),
        **({"owed_to_you": store.gst.money(owed)} if money else {}),
    }
    if status == "open":
        rows = [r for r in rows if r["status"] in ("waiting", "sent")]
    elif status != "all":
        rows = [r for r in rows if r["status"] == status]
    items = [_out(auth_context, r) for r in rows]
    return {"items": items, "total": len(items), "counts": counts}


@router.get("/sources")
async def sources(
    grn_id: uuid.UUID | None = None,
    receipt_id: uuid.UUID | None = None,
    vendor_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """What can go back, with what is left to return and the rate: a GRN's rejected quantities (``grn_id``), one
    delivery (``receipt_id``), or a supplier's deliveries of the last 90 days (``vendor_id``, optionally at a site)."""
    money = may_view_expenses(auth_context.role)
    if grn_id is not None:
        rows = (await conn.execute(text(
            """
            SELECT gl.id AS grn_line_id, gl.rejected, gl.rejected_reason, l.material_id, m.name AS material,
                   u.code AS unit, l.unit_id, l.rate, l.gst_percent, l.rate_includes_gst, o.vendor_id, v.name AS vendor_name,
                   o.project_id, o.site_id, s.name AS site_name, g.number AS grn_number
              FROM goods_receipt_lines gl JOIN goods_receipts g ON g.id = gl.goods_receipt_id
              JOIN purchase_order_lines l ON l.id = gl.purchase_order_line_id
              JOIN purchase_orders o ON o.id = l.purchase_order_id
              JOIN materials_catalog m ON m.id = l.material_id JOIN units_of_measure u ON u.id = l.unit_id
              JOIN vendors v ON v.id = o.vendor_id JOIN sites s ON s.id = o.site_id
             WHERE g.id = :id AND g.organization_id = :org AND gl.rejected > 0
            """), {"id": grn_id, "org": auth_context.organization_id})).mappings().all()
        done = await store.returned_from(conn, grn_line_ids=[r["grn_line_id"] for r in rows])
        lines = [{"grn_line_id": str(r["grn_line_id"]), "material_id": str(r["material_id"]), "material": r["material"],
                  "unit": r["unit"], "unit_id": str(r["unit_id"]), "left": store.num(r["rejected"] - done.get(str(r["grn_line_id"]), 0)),
                  "said_reason": r["rejected_reason"], "in_stock": False,
                  **({"rate": store.gst.money(r["rate"]), "gst_percent": store.num(r["gst_percent"]) if r["gst_percent"] is not None else None,
                      "rate_includes_gst": r["rate_includes_gst"]} if money else {}),
                  "vendor_id": str(r["vendor_id"]), "vendor_name": r["vendor_name"], "site_id": str(r["site_id"]),
                  "site_name": r["site_name"], "project_id": str(r["project_id"]), "from": f"GRN-{r['grn_number']:04d}"}
                 for r in rows if _visible(auth_context, r["project_id"], r["site_id"])]
        return {"items": [x for x in lines if Decimal(x["left"]) > 0]}
    sql = """
        SELECT r.id AS receipt_id, r.occurred_date, r.quantity, r.material_id, m.name AS material, u.code AS unit,
               m.default_unit_id AS unit_id, r.unit_cost, r.gst_percent, r.rate_includes_gst, r.vendor_id,
               COALESCE(v.name, r.supplier) AS vendor_name, r.project_id, r.site_id, s.name AS site_name
          FROM material_receipts r JOIN materials_catalog m ON m.id = r.material_id
          JOIN units_of_measure u ON u.id = m.default_unit_id
          LEFT JOIN vendors v ON v.id = r.vendor_id JOIN sites s ON s.id = r.site_id
         WHERE r.organization_id = :org AND r.movement_reason = 'RECEIVED' AND r.quantity > 0
           AND r.transfer_id IS NULL AND r.reverses_movement_id IS NULL
           AND NOT EXISTS (SELECT 1 FROM material_usage x WHERE x.reverses_movement_id = r.id)
    """
    params: dict = {"org": auth_context.organization_id}
    if receipt_id is not None:
        sql += " AND r.id = :id"
        params["id"] = receipt_id
    elif vendor_id is not None:
        sql += " AND r.vendor_id = :vendor AND r.occurred_date >= :since"
        params.update(vendor=vendor_id, since=await _today(conn, auth_context) - datetime.timedelta(days=90))
        if site_id is not None:
            sql += " AND r.site_id = :site"
            params["site"] = site_id
    else:
        raise HTTPException(status_code=422, detail="Say where it goes back from: grn_id, receipt_id or vendor_id.")
    rows = (await conn.execute(text(sql + " ORDER BY r.occurred_date DESC, r.created_at DESC LIMIT 100"),
                               params)).mappings().all()
    done = await store.returned_from(conn, receipt_ids=[r["receipt_id"] for r in rows])
    out = []
    for r in rows:
        if not _visible(auth_context, r["project_id"], r["site_id"]):
            continue
        left = r["quantity"] - done.get(str(r["receipt_id"]), Decimal(0))
        if left <= 0:
            continue
        out.append({"receipt_id": str(r["receipt_id"]), "date": r["occurred_date"].isoformat(),
                    "material_id": str(r["material_id"]), "material": r["material"], "unit": r["unit"],
                    "unit_id": str(r["unit_id"]), "delivered": store.num(r["quantity"]), "left": store.num(left),
                    "in_stock": True, **({"rate": store.gst.money(r["unit_cost"]),
                                          "gst_percent": store.num(r["gst_percent"]) if r["gst_percent"] is not None else None,
                                          "rate_includes_gst": r["rate_includes_gst"]} if money else {}),
                    "vendor_id": str(r["vendor_id"]) if r["vendor_id"] else None, "vendor_name": r["vendor_name"],
                    "site_id": str(r["site_id"]), "site_name": r["site_name"], "project_id": str(r["project_id"])})
    return {"items": out}


@router.get("/{return_id}")
async def get_return(return_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    return _out(auth_context, await _one(conn, auth_context, return_id))


async def _grn_line(conn: AsyncConnection, auth: AuthorizationContext, line: ReturnLineIn) -> dict:
    row = (await conn.execute(text(
        """
        SELECT gl.id, gl.rejected, gl.goods_receipt_id, l.material_id, l.unit_id, l.rate, l.gst_percent,
               l.rate_includes_gst, o.vendor_id, o.project_id, o.site_id
          FROM goods_receipt_lines gl JOIN purchase_order_lines l ON l.id = gl.purchase_order_line_id
          JOIN purchase_orders o ON o.id = l.purchase_order_id
         WHERE gl.id = :id AND gl.organization_id = :org
        """), {"id": line.grn_line_id, "org": auth.organization_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=422, detail="grn_line_id is not one of this company's GRN lines")
    left = row["rejected"] - (await store.returned_from(conn, grn_line_ids=[row["id"]])).get(str(row["id"]), Decimal(0))
    if line.quantity > left:
        raise HTTPException(status_code=409, detail=f"Only {store.num(left)} of that GRN line was turned away and is "
                            "not on a return yet.")
    return dict(row)


async def _receipt(conn: AsyncConnection, auth: AuthorizationContext, receipt_id: uuid.UUID,
                   quantity: Decimal | None) -> dict:
    row = (await conn.execute(text(
        """
        SELECT r.id, r.quantity, r.material_id, r.unit_cost, r.gst_percent, r.rate_includes_gst, r.vendor_id,
               r.project_id, r.site_id
          FROM material_receipts r
         WHERE r.id = :id AND r.organization_id = :org AND r.movement_reason = 'RECEIVED' AND r.transfer_id IS NULL
           AND r.reverses_movement_id IS NULL
           AND NOT EXISTS (SELECT 1 FROM material_usage x WHERE x.reverses_movement_id = r.id)
        """), {"id": receipt_id, "org": auth.organization_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=422, detail="receipt_id is not a delivery of this company (or it was taken back)")
    if quantity is not None:
        left = row["quantity"] - (await store.returned_from(conn, receipt_ids=[row["id"]])).get(str(row["id"]), Decimal(0))
        if quantity > left:
            raise HTTPException(status_code=409, detail=f"Only {store.num(left)} of that delivery is left to return.")
    return dict(row)


async def _last_delivery(conn: AsyncConnection, auth: AuthorizationContext, vendor_id: uuid.UUID, site_id: uuid.UUID,
                         material_id: uuid.UUID) -> uuid.UUID | None:
    """The supplier's last delivery of the material at the site (a return said in words goes against it)."""
    return (await conn.execute(text(
        "SELECT r.id FROM material_receipts r WHERE r.organization_id = :org AND r.vendor_id = :v AND r.site_id = :s "
        "AND r.material_id = :m AND r.movement_reason = 'RECEIVED' AND r.transfer_id IS NULL "
        "AND r.reverses_movement_id IS NULL AND NOT EXISTS (SELECT 1 FROM material_usage x WHERE x.reverses_movement_id = r.id) "
        "ORDER BY r.occurred_date DESC, r.created_at DESC LIMIT 1"),
        {"org": auth.organization_id, "v": vendor_id, "s": site_id, "m": material_id})).scalar()


@router.post("", status_code=201)
async def create_return(body: ReturnIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn),
                        object_storage: ObjectStoragePort = Depends(get_object_storage)):
    """Send material back to a supplier. Lines from a GRN's rejected quantity (``grn_line_id``: never in stock), from a
    delivery (``receipt_id``) or just the material (from the site's stock, against the supplier's last delivery of
    it there). Stock goes down (RETURN_TO_VENDOR) for what was in stock; the debit note DN-0001 lowers what is owed
    to the supplier at once (D-P2-3). Rate: the delivery's (or the order line's) unless said."""
    _office(auth_context)
    org = auth_context.organization_id
    vendor_id = await _vendor(conn, auth_context, body.vendor_id, body.supplier) \
        if (body.vendor_id or body.supplier) else None
    project_id, site_id, grn_id = body.project_id, body.site_id, None
    planned: list[dict] = []
    for line in body.lines:
        rate, pct, inc, unit_id = line.rate, line.gst_percent, line.rate_includes_gst, line.unit_id
        said_rate = line.rate
        material_id, receipt_id, grn_line_id, from_stock = line.material_id, line.receipt_id, line.grn_line_id, True
        if line.grn_line_id is not None:
            g = await _grn_line(conn, auth_context, line)
            if material_id is not None and material_id != g["material_id"]:
                raise HTTPException(status_code=422, detail="That GRN line is for another material.")
            material_id, unit_id, from_stock, grn_id = g["material_id"], g["unit_id"], False, g["goods_receipt_id"]
            src_vendor, src_project, src_site = g["vendor_id"], g["project_id"], g["site_id"]
            if rate is None:
                rate, pct, inc = g["rate"], g["gst_percent"], g["rate_includes_gst"]
        else:
            if material_id is None and receipt_id is None:
                raise HTTPException(status_code=422, detail="Each line needs a material, a delivery or a GRN line.")
            src_vendor = src_project = src_site = None
            if receipt_id is None and material_id is not None and vendor_id is not None and site_id is not None:
                receipt_id = await _last_delivery(conn, auth_context, vendor_id, site_id, material_id)
            if receipt_id is not None:
                r = await _receipt(conn, auth_context, receipt_id, None)
                if material_id is not None and material_id != r["material_id"]:
                    raise HTTPException(status_code=422, detail="That delivery is of another material.")
                material_id = r["material_id"]
                src_vendor, src_project, src_site = r["vendor_id"], r["project_id"], r["site_id"]
                if rate is None:
                    rate, pct, inc = r["unit_cost"], r["gst_percent"], r["rate_includes_gst"]
        for value, name in ((src_vendor, "supplier"), (src_project, "project"), (src_site, "site")):
            if value is None:
                continue
            current = {"supplier": vendor_id, "project": project_id, "site": site_id}[name]
            if current is not None and current != value:
                raise HTTPException(status_code=422, detail=f"Every line of a return is for one {name}: this one is "
                                    "for another. Make a return per supplier and site.")
        vendor_id, project_id, site_id = vendor_id or src_vendor, project_id or src_project, site_id or src_site
        planned.append({"material_id": material_id, "unit_id": unit_id, "quantity": line.quantity, "rate": rate,
                        "gst_percent": pct, "rate_includes_gst": inc, "reason": line.reason, "receipt_id": receipt_id,
                        "grn_line_id": grn_line_id, "from_stock": from_stock, "said_rate": said_rate})
    if vendor_id is None:
        raise HTTPException(status_code=422, detail="Say which supplier it goes back to.")
    if site_id is None:
        raise HTTPException(status_code=422, detail="Say which site it goes back from.")
    if project_id is None:
        project_id = (await conn.execute(text("SELECT project_id FROM sites WHERE id = :s AND organization_id = :org"),
                                         {"s": site_id, "org": org})).scalar()
        if project_id is None:
            raise HTTPException(status_code=404, detail="Site not found")
    _authorize_write(auth_context, project_id, site_id)
    await _assert_site_in_project(conn, org, project_id, site_id)
    returned_on = body.returned_on or await _today(conn, auth_context)
    number = await store.next_number(conn, org)
    ref = store.ref(number)
    return_id = uuid.uuid4()
    await conn.execute(text(
        """
        INSERT INTO material_returns (id, organization_id, number, vendor_id, project_id, site_id, goods_receipt_id,
                                      returned_on, notes, source, created_by)
        VALUES (:id, :org, :number, :vendor, :project, :site, :grn, :on, :notes, :source, :by)
        """), {"id": return_id, "org": org, "number": number, "vendor": vendor_id, "project": project_id, "site": site_id,
               "grn": grn_id, "on": returned_on, "notes": (body.notes or "").strip() or None, "source": body.source,
               "by": auth_context.user_id})
    vendor_name = (await conn.execute(text("SELECT name FROM vendors WHERE id = :v"), {"v": vendor_id})).scalar()
    for position, p in enumerate(planned):
        # The unit they said, converted to the stock unit as a delivery is (a rate per that unit too).
        out_body = MaterialOutflowCreate(project_id=project_id, site_id=site_id, material_id=p["material_id"],
                                         unit_id=p["unit_id"] or await _stock_unit(conn, org, p["material_id"]),
                                         quantity=p["quantity"], movement_reason="RETURN_TO_VENDOR",
                                         notes=f"{ref} to {vendor_name}: {store.REASONS[p['reason']].lower()}",
                                         occurred_date=returned_on, allow_negative=False)
        # Only a rate they said is per the unit they said; one taken from the delivery or order is per stock unit.
        line_ns = _RateLine(out_body.material_id, out_body.unit_id, out_body.quantity, p["said_rate"])
        await _convert_to_stock_unit(conn, org, line_ns)
        if p["said_rate"] is None:
            line_ns.unit_cost = p["rate"]
        await _resolve_and_validate_material_unit(conn, org, line_ns.material_id, line_ns.unit_id)
        usage_id = None
        if p["from_stock"]:
            if p["receipt_id"] is not None:
                await _receipt(conn, auth_context, p["receipt_id"], line_ns.quantity)
            out_body.quantity, out_body.unit_id = line_ns.quantity, line_ns.unit_id
            usage_id = (await record_outflow(conn, auth_context, out_body))["id"]
        await conn.execute(text(
            """
            INSERT INTO material_return_lines (organization_id, return_id, material_id, unit_id, quantity, rate,
                                               gst_percent, rate_includes_gst, reason, receipt_id, grn_line_id,
                                               usage_id, position)
            VALUES (:org, :ret, :material, :unit, :qty, :rate, :pct, :inc, :reason, :receipt, :grn_line, :usage, :pos)
            """), {"org": org, "ret": return_id, "material": line_ns.material_id, "unit": line_ns.unit_id,
                   "qty": line_ns.quantity, "rate": line_ns.unit_cost, "pct": p["gst_percent"],
                   "inc": p["rate_includes_gst"], "reason": p["reason"], "receipt": p["receipt_id"],
                   "grn_line": p["grn_line_id"], "usage": usage_id, "pos": position})
    keys = []
    for photo in body.photos:
        from mesiri.domains.expenses.bill_file import decode_bill

        try:
            data, extension, content_type = decode_bill(photo.data_base64, photo.content_type, "photo")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        key = f"org/{org}/returns/{return_id}/photo-{uuid.uuid4().hex}.{extension}"
        await object_storage.put_object(key, data, content_type=content_type)
        keys.append(key)
    if keys:
        await conn.execute(text("UPDATE material_returns SET photo_keys = :keys WHERE id = :id"),
                           {"keys": keys, "id": return_id})
    return _out(auth_context, await _one(conn, auth_context, return_id))


class _RateLine:
    """A return line in the shape the unit conversion rewrites (quantity, unit, a rate per that unit)."""

    def __init__(self, material_id: uuid.UUID, unit_id: uuid.UUID, quantity: Decimal, rate: Decimal | None) -> None:
        self.material_id, self.unit_id, self.quantity, self.unit_cost, self.notes = material_id, unit_id, quantity, rate, None


async def _stock_unit(conn: AsyncConnection, org: uuid.UUID, material_id: uuid.UUID) -> uuid.UUID:
    unit = (await conn.execute(text("SELECT default_unit_id FROM materials_catalog WHERE id = :m AND organization_id = :org"),
                               {"m": material_id, "org": org})).scalar()
    if unit is None:
        raise HTTPException(status_code=422, detail="material_id is not a valid active catalog entry")
    return unit


async def _set(conn: AsyncConnection, auth: AuthorizationContext, return_id: uuid.UUID, fields: dict) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    await conn.execute(text(f"UPDATE material_returns SET {sets}, status_by = :by, status_at = now(), "  # noqa: S608
                            "updated_at = now() WHERE id = :id"), {**fields, "by": auth.user_id, "id": return_id})


@router.post("/{return_id}/sent")
async def mark_sent(return_id: uuid.UUID, body: SentIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    """The supplier collected it (or it was sent back): waiting -> sent."""
    _office(auth_context)
    row = await _one(conn, auth_context, return_id, lock=True)
    if row["status"] != "waiting":
        raise HTTPException(status_code=409, detail=f"{store.ref(row['number'])} is {store.LOOK[row['status']].lower()}.")
    await _set(conn, auth_context, return_id, {"status": "sent", "sent_on": body.sent_on or await _today(conn, auth_context),
                                               "collected_by": (body.collected_by or "").strip() or None})
    return _out(auth_context, await _one(conn, auth_context, return_id))


@router.post("/{return_id}/settle")
async def settle(return_id: uuid.UUID, body: SettleIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                 conn: AsyncConnection = Depends(get_db_conn)):
    """Settled: the supplier sent a replacement (the delivery that replaced it, same supplier and site), or gave
    credit (the bill it was taken off, or the payment). The debit note stays on the ledger either way."""
    _office(auth_context)
    org = auth_context.organization_id
    row = await _one(conn, auth_context, return_id, lock=True)
    if row["status"] not in ("waiting", "sent"):
        raise HTTPException(status_code=409, detail=f"{store.ref(row['number'])} is {store.LOOK[row['status']].lower()}.")
    if body.how == "replacement" and (body.expense_id or body.payment_id):
        raise HTTPException(status_code=422, detail="A replacement is settled with the delivery that replaced it.")
    if body.how == "credit" and body.receipt_id:
        raise HTTPException(status_code=422, detail="Credit is settled with the bill or the payment it went on.")
    if body.receipt_id is not None:
        r = await _receipt(conn, auth_context, body.receipt_id, None)
        if r["vendor_id"] != row["vendor_id"] or r["site_id"] != row["site_id"]:
            raise HTTPException(status_code=422, detail="The replacement must be a delivery from the same supplier to "
                                "the same site.")
    if body.expense_id is not None:
        found = (await conn.execute(text("SELECT 1 FROM expenses WHERE id = :e AND organization_id = :org "
                                         "AND vendor_id = :v"), {"e": body.expense_id, "org": org,
                                                                 "v": row["vendor_id"]})).first()
        if found is None:
            raise HTTPException(status_code=422, detail="expense_id is not a bill of this supplier.")
    if body.payment_id is not None:
        found = (await conn.execute(text(
            "SELECT 1 FROM expense_payments p LEFT JOIN expenses e ON e.id = p.expense_id WHERE p.id = :p "
            "AND p.organization_id = :org AND COALESCE(p.vendor_id, e.vendor_id) = :v"),
            {"p": body.payment_id, "org": org, "v": row["vendor_id"]})).first()
        if found is None:
            raise HTTPException(status_code=422, detail="payment_id is not a payment to this supplier.")
    await _set(conn, auth_context, return_id, {
        "status": "settled", "settled_how": body.how, "settled_receipt_id": body.receipt_id,
        "settled_expense_id": body.expense_id, "settled_payment_id": body.payment_id,
        "settled_note": (body.note or "").strip() or None,
        "settled_on": body.settled_on or await _today(conn, auth_context)})
    out = _out(auth_context, await _one(conn, auth_context, return_id))
    if body.how == "credit" and row["goods_receipt_id"] and row["order_id"]:
        # Turned away at the gate, so the order still waits for it: say how to stop waiting, never do it silently.
        out["hint"] = (f"PO-{row['order_number']:04d} still expects what was turned away: close it short if no "
                       "replacement is coming.")
    return out


@router.post("/{return_id}/cancel")
async def cancel(return_id: uuid.UUID, body: CancelIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                 conn: AsyncConnection = Depends(get_db_conn)):
    """Not going back after all (only while waiting for pickup): what it took from stock is put back (the existing
    reversal) and its debit note leaves the ledger."""
    _office(auth_context)
    row = await _one(conn, auth_context, return_id, lock=True)
    if row["status"] != "waiting":
        raise HTTPException(status_code=409, detail=f"{store.ref(row['number'])} is {store.LOOK[row['status']].lower()}: "
                            "only a return still waiting for pickup can be cancelled.")
    for line in row["lines"]:
        if line["usage_id"] is not None:
            await reverse_material_record(conn, kind="usage", record_id=line["usage_id"],
                                          organization_id=auth_context.organization_id, user_id=auth_context.user_id,
                                          reason_note=f"{store.ref(row['number'])} cancelled: {body.reason.strip()}")
    await _set(conn, auth_context, return_id, {"status": "cancelled", "cancel_reason": body.reason.strip()})
    return _out(auth_context, await _one(conn, auth_context, return_id))


@router.get("/{return_id}/photos")
async def photos(return_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                 conn: AsyncConnection = Depends(get_db_conn),
                 object_storage: ObjectStoragePort = Depends(get_object_storage)):
    from mesiri.domains.shared.media import signed_media_url

    row = await _one(conn, auth_context, return_id)
    return {"items": [await signed_media_url(object_storage, key) for key in row["photo_keys"] or []]}

