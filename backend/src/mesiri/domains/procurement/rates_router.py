"""PRC-14 / PRC-16: the rates page (Procurement > Rates) and a supplier's last rates.

``GET /procurement/rates`` -- every item bought in the period: last rate and the one before it, low / high /
average, each supplier's average, the cheapest supplier and what was paid above its rate, and the points for a
trend line. ``vendor_id`` narrows the items to what that supplier delivered (the supplier page), still compared
with every supplier. ``GET /procurement/rates/{material_id}`` -- one item's purchases, newest first.
``GET /procurement/rates/suppliers/{vendor_id}`` -- PRC-51: the supplier's price list (last quoted and last paid per
material, ``price_list.py``); the supplier page and the new-order dialog read it.
``GET /procurement/rates/suppliers/performance`` / ``.../suppliers/{vendor_id}/performance`` -- PRC-50: each
supplier's 0-5 score and its measures (``vendors/performance.py``); the list, picker and comparison sheet read the
first, the supplier page the second.

Rates are for the roles that see the company's spending (SEC-01, ``may_view_expenses``); others get 403. Rows
follow the caller's project and site scope, like stock.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_view_expenses
from mesiri.domains.materials.router import _resolve_project_ids, _site_filter_denied
from mesiri.domains.procurement import price_list
from mesiri.domains.procurement import rates as store
from mesiri.domains.procurement.router import _visible
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(prefix="/procurement/rates", tags=["procurement"], dependencies=[Depends(require_module("materials"))])

#: Without dates: the last three months, the window most rate questions mean.
DEFAULT_DAYS = 90


def _allowed(auth: AuthorizationContext) -> None:
    if not may_view_expenses(auth.role):
        raise HTTPException(status_code=403, detail="Rates are shown to the roles that see spending.")


async def _period(conn: AsyncConnection, auth: AuthorizationContext, date_from, date_to):
    if date_to is None:
        from mesiri.application.dpr import project_day

        date_to = await project_day.company_today(conn, auth.organization_id)
    date_from = date_from or date_to - datetime.timedelta(days=DEFAULT_DAYS - 1)
    if date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from is after date_to")
    if (date_to - date_from).days > 731:
        raise HTTPException(status_code=422, detail="A period is at most two years.")
    return date_from, date_to


def _in_scope(auth: AuthorizationContext, rows: list[dict], site_id: uuid.UUID | None) -> list[dict]:
    out = []
    for r in rows:
        if site_id is not None and r.get("site_id") != site_id:
            continue
        if r.get("site_id") is not None and not _visible(auth, r["project_id"], r["site_id"]):
            continue
        out.append(r)
    return out


@router.get("")
async def list_rates(
    date_from: datetime.date | None = Query(default=None, description="First day; default: 89 days before date_to."),
    date_to: datetime.date | None = Query(default=None, description="Last day; default: today (company date)."),
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = Query(default=None, description="A main category includes its sub-categories."),
    vendor_id: uuid.UUID | None = Query(default=None, description="Only items this supplier delivered in the period."),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    _allowed(auth_context)
    date_from, date_to = await _period(conn, auth_context, date_from, date_to)
    empty = {"date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "items": [],
             "summary": {"items": 0, "purchases": 0, "spend": "0.00", "rising": 0, "falling": 0, "above_best": "0.00"}}
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return empty
    rows = await store.fetch_purchases(conn, auth_context.organization_id, project_ids=project_ids,
                                       date_from=date_from, date_to=date_to, category_id=category_id)
    rows = _in_scope(auth_context, rows, site_id)
    before = await store.fetch_before(conn, auth_context.organization_id, project_ids=project_ids, before=date_from,
                                      material_ids=list({r["material_id"] for r in rows}))
    before = {m: r for m, r in before.items() if _in_scope(auth_context, [r], site_id)}
    items = store.summarise(rows, before)
    if vendor_id is not None:
        items = [i for i in items if any(v["vendor_id"] == str(vendor_id) for v in i["vendors"])]
    items.sort(key=lambda i: -Decimal(i["spend"]))
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "items": items,
        "summary": {
            "items": len(items),
            "purchases": sum(i["purchases"] for i in items),
            "spend": store._money(sum((Decimal(i["spend"]) for i in items), Decimal(0))),
            "rising": sum(1 for i in items if i["trend"] == "up"),
            "falling": sum(1 for i in items if i["trend"] == "down"),
            "above_best": store._money(sum((Decimal(i["above_best"]) for i in items), Decimal(0))),
        },
    }


async def _performance(conn: AsyncConnection, auth: AuthorizationContext, vendor_id: uuid.UUID | None) -> list[dict]:
    from mesiri.application.dpr import project_day
    from mesiri.domains.vendors import performance

    org = auth.organization_id
    sql = "SELECT id FROM vendors WHERE organization_id = :org"
    params: dict = {"org": org}
    if vendor_id is not None:
        sql += " AND id = :id"
        params["id"] = vendor_id
    ids = [str(r[0]) for r in (await conn.execute(text(sql), params)).all()]
    if vendor_id is not None and not ids:
        raise HTTPException(status_code=404, detail="Supplier not found")
    project_ids, denied = _resolve_project_ids(auth, None)
    if denied or not ids:
        return []
    today = await project_day.company_today(conn, org)
    return await performance.performance(conn, org, today=today, project_ids=project_ids, vendor_id=vendor_id,
                                         vendor_ids=ids, with_problems=vendor_id is not None)


@router.get("/suppliers/performance")
async def suppliers_performance(auth_context: AuthorizationContext = Depends(get_auth_context),
                                conn: AsyncConnection = Depends(get_db_conn)):
    """PRC-50: every supplier's score and measures (no trend or problems): the supplier list, pickers, comparison."""
    _allowed(auth_context)
    from mesiri.domains.vendors.performance import WEIGHTS

    return {"weights": WEIGHTS, "items": await _performance(conn, auth_context, None)}


@router.get("/suppliers/{vendor_id}/performance")
async def supplier_performance(vendor_id: uuid.UUID, auth_context: AuthorizationContext = Depends(get_auth_context),
                               conn: AsyncConnection = Depends(get_db_conn)):
    """PRC-50: one supplier's score, measures, monthly trend, last problems and manual rating."""
    _allowed(auth_context)
    from mesiri.domains.vendors.performance import WEIGHTS

    return {"weights": WEIGHTS, **(await _performance(conn, auth_context, vendor_id))[0]}


@router.get("/suppliers/{vendor_id}")
async def supplier_price_list(
    vendor_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """PRC-51: per material, the supplier's newest quote (live or expired) and its last delivery's rate, within the
    caller's project and site scope."""
    _allowed(auth_context)
    org = auth_context.organization_id
    found = (await conn.execute(text("SELECT 1 FROM vendors WHERE id = :id AND organization_id = :org"),
                                {"id": vendor_id, "org": org})).first()
    if found is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    from mesiri.application.dpr import project_day

    today = await project_day.company_today(conn, org)
    project_ids, denied = _resolve_project_ids(auth_context, None)
    if denied:
        return {"vendor_id": str(vendor_id), "today": today.isoformat(), "items": []}
    purchases = await store.fetch_purchases(conn, org, project_ids=project_ids, date_from=None, date_to=today,
                                            vendor_id=vendor_id)
    quotes = [q for q in await price_list.fetch_quotes(conn, org, vendor_id)
              if (project_ids is None or q["project_id"] in project_ids)
              and _visible(auth_context, q["project_id"], q["site_id"])]
    items = price_list.build(quotes, _in_scope(auth_context, purchases, None), today)
    return {"vendor_id": str(vendor_id), "today": today.isoformat(), "items": items}


@router.get("/{material_id}")
async def material_rates(
    material_id: uuid.UUID,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """One item's purchases in the period, newest first, with where each came from (bill, order, delivery) and
    whether the delivery's rate differs from its order's."""
    _allowed(auth_context)
    date_from, date_to = await _period(conn, auth_context, date_from, date_to)
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return {"material_id": str(material_id), "purchases": []}
    rows = await store.fetch_purchases(conn, auth_context.organization_id, project_ids=project_ids,
                                       date_from=date_from, date_to=date_to, material_id=material_id)
    rows = _in_scope(auth_context, rows, site_id)
    return {"material_id": str(material_id), "purchases": [store.purchase_out(r) for r in reversed(rows)]}
