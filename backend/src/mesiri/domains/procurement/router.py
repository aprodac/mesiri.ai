"""PRC-22: the material requests API (dashboard Materials > Requests, and the WhatsApp assistant's tools).

Anyone who can reach a project and site may ask for material there and cancel their own request while it
waits. Deciding (ordered, sent from another site, not ordered, received) is for the roles in
``may_act_on_material_requests``. Each line is checked and converted like a delivery (the material's
stock unit); rates are shown only to the roles that see the company's spending (SEC-01).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_act_on_material_requests, may_view_expenses
from mesiri.domains.materials.router import (
    _assert_site_in_project,
    _authorize_write,
    _convert_to_stock_unit,
    _resolve_and_validate_material_unit,
    _resolve_project_ids,
    _site_filter_denied,
)
from mesiri.domains.procurement import requests as store
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.materials import PostgresMaterialReadRepository

router = APIRouter(
    prefix="/procurement/requests",
    tags=["procurement"],
    dependencies=[Depends(require_module("materials"))],
)


class RequestLineIn(BaseModel):
    material_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit_id: uuid.UUID
    #: Filled by the conversion: what was said in another unit.
    notes: str | None = None


class RequestCreate(BaseModel):
    """Several items as ``lines``, or one item as ``material_id`` + ``quantity`` + ``unit_id`` (the WhatsApp
    assistant's form: one card line per item, checked like a delivery line)."""

    project_id: uuid.UUID
    site_id: uuid.UUID
    lines: list[RequestLineIn] = Field(default_factory=list, max_length=50)
    material_id: uuid.UUID | None = None
    quantity: Decimal | None = Field(default=None, gt=0)
    unit_id: uuid.UUID | None = None
    needed_by: datetime.date | None = None
    purpose: str | None = Field(default=None, max_length=300)
    source: Literal["dashboard", "whatsapp"] = "dashboard"
    #: Raise it even though an open request in the project already asks for the same material.
    confirm_duplicate: bool = False


class RequestDecision(BaseModel):
    action: Literal["ordered", "sent", "rejected", "done"]
    note: str | None = Field(default=None, max_length=300)


def _visible(auth: AuthorizationContext, project_id: uuid.UUID, site_id: uuid.UUID) -> bool:
    if not auth.project_scope.grants_all_org_projects and project_id not in auth.project_scope.project_ids:
        return False
    return not _site_filter_denied(auth, project_id, site_id)


async def _context(conn: AsyncConnection, auth: AuthorizationContext, project_ids: set[uuid.UUID] | None):
    """What every description needs: stock per site and material, the open requests, today, rates."""
    from mesiri.application.dpr import project_day

    stock_rows = await PostgresMaterialReadRepository(conn).get_stock_levels(
        organization_id=auth.organization_id, project_ids=project_ids)
    stock_rows = [s for s in stock_rows if s.get("site_id") and _visible(auth, s["project_id"], s["site_id"])]
    all_rows = await store.fetch_requests(conn, auth.organization_id, project_ids=project_ids)
    today = await project_day.company_today(conn, auth.organization_id)
    return stock_rows, all_rows, today


async def _order_lines(conn: AsyncConnection, auth: AuthorizationContext, project_ids: set[uuid.UUID] | None):
    from mesiri.domains.procurement.orders import order_lines_for_requests

    return await order_lines_for_requests(conn, auth.organization_id, project_ids=project_ids)


async def _rates(conn: AsyncConnection, auth: AuthorizationContext, rows: list[dict]) -> dict | None:
    if not may_view_expenses(auth.role):
        return None
    repo = PostgresMaterialReadRepository(conn)
    out = {}
    for material_id in {line["material_id"] for row in rows for line in row["lines"]}:
        rate = await repo.get_last_purchase_price(auth.organization_id, material_id)
        if rate is not None:
            out[material_id] = rate
    return out


def _with_rights(item: dict, auth: AuthorizationContext) -> dict:
    mine = item["requested_by"] == str(auth.user_id)
    item["may_act"] = may_act_on_material_requests(auth.role)
    item["may_cancel"] = item["status"] == store.WAITING and (mine or item["may_act"])
    #: PRC-23: a request an order covers follows the order; the office decides on the order, not here.
    item["may_decide"] = item["may_act"] and not item["follows_order"] and item["status"] in store.OPEN
    return item


async def _describe(conn, auth, rows, stock_rows, all_rows, today) -> list[dict]:
    project_ids, _ = _resolve_project_ids(auth, None)
    items = await store.describe(conn, auth.organization_id, rows, stock_rows=stock_rows, all_requests=all_rows,
                                 today=today, last_rates=await _rates(conn, auth, rows),
                                 order_lines=await _order_lines(conn, auth, project_ids))
    return [_with_rights(item, auth) for item in items]


async def _one(conn: AsyncConnection, auth: AuthorizationContext, request_id: uuid.UUID) -> dict:
    project_ids, denied = _resolve_project_ids(auth, None)
    if denied:
        raise HTTPException(status_code=404, detail="Request not found")
    stock_rows, all_rows, today = await _context(conn, auth, project_ids)
    rows = [r for r in all_rows if r["id"] == request_id and _visible(auth, r["project_id"], r["site_id"])]
    if not rows:
        raise HTTPException(status_code=404, detail="Request not found")
    return (await _describe(conn, auth, rows, stock_rows, all_rows, today))[0]


@router.get("")
async def list_requests(
    status: str = Query(default="waiting", description="waiting, ordered (ordered or sent), done, rejected, "
                        "cancelled, open (not closed) or all"),
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    requested_by: uuid.UUID | None = None,
    category_id: uuid.UUID | None = Query(default=None, description="A main category includes its sub-categories."),
    urgency: str | None = Query(default=None, description="late, soon, later or closed"),
    mine: bool = False,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """The requests the caller can see, most urgent first, with counts for the page's tiles and tabs."""
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return {"items": [], "counts": {}}
    stock_rows, all_rows, today = await _context(conn, auth_context, project_ids)
    rows = [r for r in all_rows if _visible(auth_context, r["project_id"], r["site_id"])]
    if site_id is not None:
        rows = [r for r in rows if r["site_id"] == site_id]
    if mine:
        rows = [r for r in rows if r["requested_by"] == auth_context.user_id]
    if requested_by is not None:
        rows = [r for r in rows if r["requested_by"] == requested_by]
    if category_id is not None:
        rows = [r for r in rows if any(category_id in (line["category_id"], line["main_category_id"])
                                       for line in r["lines"])]
    items = await _describe(conn, auth_context, rows, stock_rows, all_rows, today)

    def in_tab(item: dict, tab: str) -> bool:
        s = item["status"]
        return {"waiting": s == "waiting", "ordered": s in store.IN_FLIGHT, "done": s == "done",
                "rejected": s == "rejected", "cancelled": s == "cancelled", "open": s in store.OPEN,
                "all": True}.get(tab, False)

    counts = {tab: sum(1 for i in items if in_tab(i, tab)) for tab in ("waiting", "ordered", "done", "rejected", "all")}
    counts["late"] = sum(1 for i in items if i["urgency"] == "late")
    counts["soon"] = sum(1 for i in items if i["urgency"] == "soon")
    counts["duplicates"] = sum(1 for i in items if i["duplicates"] and i["status"] in store.OPEN)
    if status not in ("waiting", "ordered", "done", "rejected", "cancelled", "open", "all"):
        raise HTTPException(status_code=422, detail="status is one of waiting, ordered, done, rejected, cancelled, "
                            "open, all")
    items = [i for i in items if in_tab(i, status)]
    if urgency:
        items = [i for i in items if i["urgency"] == urgency]
    order = {"late": 0, "soon": 1, "later": 2, "closed": 3}
    items.sort(key=lambda i: (order[i["urgency"]], i["needed_by"] or "9999", -i["number"]))
    return {"items": items, "counts": counts}


@router.get("/{request_id}")
async def get_request(
    request_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    return await _one(conn, auth_context, request_id)


@router.post("", status_code=201)
async def create_request(
    body: RequestCreate,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Ask for material for a site. If an open request in the project already asks for one of the same materials,
    nothing is saved and a 409 names it (``detail.code`` = ``possible_duplicate``), unless ``confirm_duplicate``."""
    if body.material_id is not None:
        if body.lines or body.quantity is None or body.unit_id is None:
            raise HTTPException(status_code=422, detail="One item is material_id, quantity and unit_id (or use lines).")
        body.lines = [RequestLineIn(material_id=body.material_id, quantity=body.quantity, unit_id=body.unit_id)]
    if not body.lines:
        raise HTTPException(status_code=422, detail="Say what is needed: at least one item.")
    _authorize_write(auth_context, body.project_id, body.site_id)
    await _assert_site_in_project(conn, auth_context.organization_id, body.project_id, body.site_id)
    org = auth_context.organization_id
    lines = []
    for line in body.lines:
        said = await _convert_to_stock_unit(conn, org, line)
        await _resolve_and_validate_material_unit(conn, org, line.material_id, line.unit_id)
        lines.append({"material_id": line.material_id, "unit_id": line.unit_id, "quantity": line.quantity,
                      "said": said.split(" = ")[0] if said else None})
    if len({line["material_id"] for line in lines}) != len(lines):
        raise HTTPException(status_code=422, detail="Each material once per request: add the quantities together.")
    project_ids, _ = _resolve_project_ids(auth_context, body.project_id)
    existing = await store.fetch_requests(conn, org, project_ids=project_ids)
    materials = {line["material_id"] for line in lines}
    duplicates = store.open_duplicates(existing, body.project_id, materials)
    # PRC-23: an order placed without a request is a duplicate too ("already on order").
    on_order = store.on_order_in_project(await _order_lines(conn, auth_context, project_ids), body.project_id,
                                         materials)
    if (duplicates or on_order) and not body.confirm_duplicate:
        if duplicates:
            first = duplicates[0]
            who = first["requested_by_name"] or "Someone"
            what = ", ".join(f"{x['quantity']} {x['unit']} {x['material']}" for x in first["lines"])
            message = f"{who} already asked for {what} in this project ({first['ref']}, {first['status']})."
        else:
            order = on_order[0]
            what = ", ".join(f"{x['pending']} {x['unit']} {x['material']}" for x in order["lines"])
            message = (f"Already on order for this project: {what} still to come on {order['ref']} from "
                       f"{order['vendor_name']}.")
        return JSONResponse(status_code=409, content={"detail": {
            "code": "possible_duplicate", "message": message, "duplicates": duplicates, "orders": on_order}})
    request_id = await store.insert_request(
        conn, org, project_id=body.project_id, site_id=body.site_id, requested_by=auth_context.user_id,
        source=body.source, needed_by=body.needed_by, purpose=(body.purpose or "").strip() or None,
        raised_over_duplicate=bool(duplicates or on_order), lines=lines)
    return await _one(conn, auth_context, request_id)


@router.post("/{request_id}/decide")
async def decide_request(
    request_id: uuid.UUID,
    body: RequestDecision,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """The office acts: ordered, sent from another site, not ordered (a reason is required), or received. The
    person who asked is told on WhatsApp."""
    if not may_act_on_material_requests(auth_context.role):
        raise HTTPException(status_code=403, detail="Only an admin, owner or project manager can act on a request.")
    item = await _locked(conn, auth_context, request_id)
    if item["follows_order"]:
        refs = ", ".join(o["ref"] for o in item["orders"] if o["status"] in ("open", "part", "received"))
        raise HTTPException(status_code=409, detail=f"{item['ref']} follows {refs}: it moves with the order (record "
                            "the delivery against the order, or close or cancel the order).")
    target, allowed_from = store.DECISIONS[body.action]
    if item["status"] not in allowed_from:
        raise HTTPException(status_code=409, detail=f"This request is {item['status']}; it cannot be marked "
                            f"{body.action} now.")
    note = (body.note or "").strip() or None
    if body.action == "rejected" and not note:
        raise HTTPException(status_code=422, detail="Say why it is not being ordered (a reason is required).")
    await store.set_status(conn, request_id, target, auth_context.user_id, note)
    after = await _one(conn, auth_context, request_id)
    await _tell_requester(conn, auth_context, after, target, note)
    return after


@router.post("/{request_id}/cancel")
async def cancel_request(
    request_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """The person who asked (or the office) takes a waiting request back."""
    item = await _locked(conn, auth_context, request_id)
    if not item["may_cancel"]:
        if item["status"] != store.WAITING:
            raise HTTPException(status_code=409, detail=f"This request is {item['status']}; only a waiting request "
                                "can be cancelled.")
        raise HTTPException(status_code=403, detail="Only the person who asked, or the office, can cancel it.")
    await store.set_status(conn, request_id, "cancelled", auth_context.user_id, None)
    return await _one(conn, auth_context, request_id)


async def _locked(conn: AsyncConnection, auth: AuthorizationContext, request_id: uuid.UUID) -> dict:
    """The request, locked for this change, as the caller sees it (404 when outside their projects or sites)."""
    rows = await store.fetch_requests(conn, auth.organization_id, project_ids=None, request_id=request_id, lock=True)
    if not rows or not _visible(auth, rows[0]["project_id"], rows[0]["site_id"]):
        raise HTTPException(status_code=404, detail="Request not found")
    return await _one(conn, auth, request_id)


async def _tell_requester(conn: AsyncConnection, auth: AuthorizationContext, item: dict, status: str,
                          note: str | None, *, wording: str | None = None) -> None:
    """The person who asked hears what happened, on WhatsApp (the notification queue), in their reply language.
    Once per change: the same status reached again later (ordered, closed short, ordered again the same day) is a new
    change and is told again. ``wording``: another line for the same status (``received`` for one done by its orders)."""
    if not item["requested_by"] or item["requested_by"] == str(auth.user_id):
        return
    from sqlalchemy import text

    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

    try:
        async with conn.begin_nested():
            language = (await conn.execute(text("SELECT reply_language FROM users WHERE id = :id"),
                                           {"id": uuid.UUID(item["requested_by"])})).scalar()
            changed_at = item.get("done_at") if status == "done" else item.get("decided_at")
            await PostgresNotificationRepository(conn).claim(
                organization_id=auth.organization_id, rule_key="material_request_update",
                subject_id=f"{item['id']}:{status}:{changed_at or ''}", occurred_on=datetime.date.today(),
                recipient_user_id=uuid.UUID(item["requested_by"]),
                project_id=uuid.UUID(item["project_id"]), site_id=uuid.UUID(item["site_id"]),
                payload={"message": store.requester_message(item, wording or status, note,
                                                            item.get("decided_by_name"), language)})
    except Exception:  # noqa: BLE001 -- the decision is saved; the note is a courtesy
        return
