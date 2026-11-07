"""PRC-14 / PRC-16: the rates page (Procurement > Rates) and a supplier's last rates.

``GET /procurement/rates`` -- every item bought in the period: last rate and the one before it, low / high /
average, each supplier's average, the cheapest supplier and what was paid above its rate, and the points for a
trend line. ``vendor_id`` narrows the items to what that supplier delivered (the supplier page), still compared
with every supplier. ``GET /procurement/rates/{material_id}`` -- one item's purchases, newest first.

Rates are for the roles that see the company's spending (SEC-01, ``may_view_expenses``); others get 403. Rows
follow the caller's project and site scope, like stock.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_view_expenses
from mesiri.domains.materials.router import _resolve_project_ids, _site_filter_denied
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
