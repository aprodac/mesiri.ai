"""PRC-47: Materials > Stock -- the minimum per site and material, and what is below it. Rules in ``stock_levels.py``.

``GET    /materials/stock-levels``                       the minimums set (filter by project or site)
``PUT    /materials/stock-levels``                       set or change one (min_qty 0: no minimum)
``POST   /materials/stock-levels/bulk``                  set several at once (the "suggest from use" sheet)
``DELETE /materials/stock-levels/{site_id}/{material_id}``  no minimum any more
``GET    /materials/stock-levels/suggest``               a minimum per item of a site from its last week's use
``GET    /materials/stock-levels/below``                 what is below its minimum now, with the reorder quantities

Who sets them: the people who run the projects (admin, owner, project manager), the group that orders (PRC-12 may
change it). Anyone who sees the site sees its minimums and what is below them.
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
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_act_on_material_requests
from mesiri.domains.materials import stock_levels as store
from mesiri.domains.materials.router import (
    _authorize_write,
    _convert_to_stock_unit,
    _resolve_and_validate_material_unit,
    _resolve_project_ids,
    _site_filter_denied,
)
from mesiri.domains.materials.stock_summary import suggest_minimum
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(prefix="/materials/stock-levels", tags=["materials"],
                   dependencies=[Depends(require_module("materials"))])


class LevelIn(BaseModel):
    site_id: uuid.UUID
    material_id: uuid.UUID
    #: The minimum the site should hold; 0: no minimum any more.
    min_qty: Decimal = Field(ge=0)
    #: How much to ask for when it goes below; left out: enough to reach twice the minimum.
    reorder_qty: Decimal | None = Field(default=None, gt=0)
    #: The unit min_qty / reorder_qty were said in; left out: the material's stock unit. Converted as a delivery is.
    unit_id: uuid.UUID | None = None
    source: Literal["typed", "excel", "suggested", "whatsapp"] = "typed"


class LevelsIn(BaseModel):
    levels: list[LevelIn] = Field(min_length=1, max_length=500)


def _office(auth: AuthorizationContext) -> None:
    if not may_act_on_material_requests(auth.role):
        raise HTTPException(status_code=403, detail="Only an admin, owner or project manager can set minimum stock.")


async def _today(conn: AsyncConnection, auth: AuthorizationContext) -> datetime.date:
    from mesiri.application.dpr import project_day

    return await project_day.company_today(conn, auth.organization_id)


async def _site(conn: AsyncConnection, auth: AuthorizationContext, site_id: uuid.UUID) -> dict:
    row = (await conn.execute(text(
        "SELECT s.id, s.name, s.project_id FROM sites s WHERE s.id = :id AND s.organization_id = :org"),
        {"id": site_id, "org": auth.organization_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Site not found")
    _, denied = _resolve_project_ids(auth, row["project_id"])
    if denied or _site_filter_denied(auth, row["project_id"], site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    return dict(row)


async def _in_stock_unit(conn: AsyncConnection, auth: AuthorizationContext, body: LevelIn) -> tuple[Decimal, Decimal | None]:
    """min_qty and reorder_qty in the material's stock unit (said in another unit: converted as a delivery is)."""
    if body.unit_id is None:
        return body.min_qty, body.reorder_qty
    out = []
    for value in (body.min_qty, body.reorder_qty):
        if value is None or value == 0:
            out.append(value)
            continue
        line = SimpleNamespace(material_id=body.material_id, unit_id=body.unit_id, quantity=value, notes=None)
        await _convert_to_stock_unit(conn, auth.organization_id, line)
        await _resolve_and_validate_material_unit(conn, auth.organization_id, body.material_id, line.unit_id)
        out.append(Decimal(str(line.quantity)))
    return out[0], out[1]


async def _save(conn: AsyncConnection, auth: AuthorizationContext, body: LevelIn) -> dict:
    site = await _site(conn, auth, body.site_id)
    _authorize_write(auth, site["project_id"], body.site_id)
    material = (await conn.execute(text(
        "SELECT m.id, m.name, u.code AS unit FROM materials_catalog m LEFT JOIN units_of_measure u "
        "ON u.id = m.default_unit_id WHERE m.id = :id AND m.organization_id = :org AND m.is_active"),
        {"id": body.material_id, "org": auth.organization_id})).mappings().first()
    if material is None:
        raise HTTPException(status_code=422, detail="material_id is not a valid active catalog entry")
    minimum, reorder = await _in_stock_unit(conn, auth, body)
    words = f"{material['name']} at {site['name']}"
    if minimum == 0:
        removed = await store.remove_level(conn, auth.organization_id, body.site_id, body.material_id)
        return {"site_id": str(body.site_id), "material_id": str(body.material_id), "removed": removed,
                "said": f"No minimum for {words}"}
    if reorder is not None and reorder < minimum / 10:
        raise HTTPException(status_code=422, detail=f"Reorder {store.num(reorder)} {material['unit']} is very small "
                            f"for a minimum of {store.num(minimum)}: say how much to order when it goes below.")
    level_id = await store.save_level(conn, auth.organization_id, site_id=body.site_id, material_id=body.material_id,
                                      min_qty=minimum, reorder_qty=reorder, set_how=body.source,
                                      user_id=auth.user_id)
    return {"id": str(level_id), "site_id": str(body.site_id), "material_id": str(body.material_id),
            "min_qty": store.num(minimum), "reorder_qty": store.num(reorder) if reorder is not None else None,
            "unit": material["unit"],
            "said": f"Minimum {store.num(minimum)} {material['unit']} of {words}"
                    + (f", order {store.num(reorder)} when below" if reorder is not None else "")}


@router.get("")
async def list_levels(project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None,
                      auth_context: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    """The minimums set, per site and material, with who set them and how."""
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return {"items": [], "total": 0}
    sql = ("SELECT l.site_id, s.name AS site_name, s.project_id, l.material_id, m.name AS material, u.code AS unit, "
           "l.min_qty, l.reorder_qty, l.set_how, cu.full_name AS set_by_name, l.updated_at FROM stock_levels l "
           "JOIN sites s ON s.id = l.site_id JOIN materials_catalog m ON m.id = l.material_id "
           "LEFT JOIN units_of_measure u ON u.id = m.default_unit_id LEFT JOIN users cu ON cu.id = l.set_by "
           "WHERE l.organization_id = :org")
    params: dict = {"org": auth_context.organization_id}
    if project_ids is not None:
        sql += " AND s.project_id = ANY(:projects)"
        params["projects"] = list(project_ids)
    if site_id is not None:
        sql += " AND l.site_id = :site"
        params["site"] = site_id
    rows = (await conn.execute(text(sql + " ORDER BY s.name, m.name"), params)).mappings().all()
    items = [{**{k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in r.items()},
              "min_qty": store.num(r["min_qty"]),
              "reorder_qty": store.num(r["reorder_qty"]) if r["reorder_qty"] is not None else None,
              "updated_at": r["updated_at"].isoformat()}
             for r in rows if _site_filter_denied(auth_context, r["project_id"], r["site_id"]) is False]
    return {"items": items, "total": len(items)}


@router.put("")
async def set_level(body: LevelIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    """Set the minimum a site should hold of a material (in the unit they said, converted to the stock unit), and
    optionally how much to order when it goes below. min_qty 0: no minimum any more."""
    _office(auth_context)
    return await _save(conn, auth_context, body)


@router.post("/bulk")
async def set_levels(body: LevelsIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    """Set several minimums at once (all or none)."""
    _office(auth_context)
    saved = [await _save(conn, auth_context, level) for level in body.levels]
    return {"items": saved, "total": len(saved)}


@router.delete("/{site_id}/{material_id}", status_code=204)
async def remove_level(site_id: uuid.UUID, material_id: uuid.UUID,
                       auth_context: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    _office(auth_context)
    site = await _site(conn, auth_context, site_id)
    _authorize_write(auth_context, site["project_id"], site_id)
    if not await store.remove_level(conn, auth_context.organization_id, site_id, material_id):
        raise HTTPException(status_code=404, detail="No minimum is set for that item at that site")


@router.get("/suggest")
async def suggest(site_id: uuid.UUID, material_id: uuid.UUID | None = None,
                  auth_context: AuthorizationContext = Depends(get_auth_context),
                  conn: AsyncConnection = Depends(get_db_conn)):
    """A minimum per item of the site from its use: a week's average use plus the lead time of the supplier who last
    delivered it (2 days when not set), and a reorder quantity of two weeks' use. Nothing is saved; items used
    nothing in the last 7 days are not suggested."""
    from mesiri.infrastructure.postgres.repositories.materials import PostgresMaterialReadRepository

    site = await _site(conn, auth_context, site_id)
    today = await _today(conn, auth_context)
    rows = await PostgresMaterialReadRepository(conn).get_stock_summary(
        auth_context.organization_id, date_from=today - datetime.timedelta(days=6), date_to=today,
        project_ids={site["project_id"]}, site_id=site_id, material_id=material_id)
    used = [r for r in rows if Decimal(str(r["used"])) > 0]
    leads = await store.lead_days(conn, auth_context.organization_id, [r["material_id"] for r in used])
    levels = await store.levels_by_site(conn, auth_context.organization_id, [site_id])
    items = []
    for r in used:
        days, supplier = leads[str(r["material_id"])]
        got = suggest_minimum(Decimal(str(r["used"])), days)
        if got is None:
            continue
        now = levels.get((str(site_id), str(r["material_id"])))
        items.append({
            "site_id": str(site_id), "material_id": str(r["material_id"]), "material": r["material_name"],
            "unit": r["unit"], "main_category": r.get("main_category"), "used_last_week": store.num(r["used"]),
            "closing": store.num(r["closing"]), "lead_days": days, "supplier": supplier,
            "min_qty": store.num(got[0]), "reorder_qty": store.num(got[1]),
            "current_min": store.num(now["min_qty"]) if now else None,
        })
    items.sort(key=lambda i: i["material"])
    return {"site_id": str(site_id), "site_name": site["name"], "items": items, "total": len(items)}


@router.get("/below")
async def below(project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None,
                include_covered: bool = Query(default=True, description="Also items an order, RFQ or request covers"),
                auth_context: AuthorizationContext = Depends(get_auth_context),
                conn: AsyncConnection = Depends(get_db_conn)):
    """What each site holds less of than its minimum now: what it holds, the minimum, how much to order (the reorder
    quantity), and ``covered_by`` when an open order, RFQ or material request is already buying it. Grouped by site
    in ``sites`` (each with the lines a draft request or RFQ takes: material_id, unit_id, quantity)."""
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return {"items": [], "total": 0, "sites": []}
    rows = await store.below_minimum(conn, auth_context.organization_id, await _today(conn, auth_context),
                                     project_ids=project_ids, site_id=site_id)
    rows = [r for r in rows if not _site_filter_denied(auth_context, uuid.UUID(r["project_id"]), uuid.UUID(r["site_id"]))
            and (include_covered or r["covered_by"] is None)]
    sites: dict[str, dict] = {}
    for r in rows:
        group = sites.setdefault(r["site_id"], {"site_id": r["site_id"], "site_name": r["site_name"],
                                                "project_id": r["project_id"], "project_name": r["project_name"],
                                                "items": 0, "to_buy": []})
        group["items"] += 1
        if r["covered_by"] is None:
            group["to_buy"].append({"material_id": r["material_id"], "unit_id": r["unit_id"],
                                    "quantity": r["to_order"]})
    return {"items": rows, "total": len(rows), "not_covered": sum(1 for r in rows if r["covered_by"] is None),
            "sites": list(sites.values())}
