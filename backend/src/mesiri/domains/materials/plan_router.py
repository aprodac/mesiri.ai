"""REST API for a project's material plan (MP-02).

  GET /projects/{project_id}/material-plan?weeks=8&site_id=

What the project needs of each material week by week, from the BOQ's remaining work × its norms (MP-01) over the
schedule's dates (ST-04), against stock on hand and on open orders (PRC-17, PRC-27): the week each material runs
short and by how much. The maths is ``domains/materials/plan.py``; this file only gathers the inputs.

Who sees it: the BOQ's roles (``may_view_expenses``), because it is read from the BOQ. Showing the plan's quantities
to site roles (storekeeper, engineer) is a permissions decision for later. Plan: docs/plans/material-plan-plan.md.
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.materials import plan
from mesiri.domains.progress.boq_router import _exact, _scope
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(tags=["material-plan"], dependencies=[Depends(require_module("dpr"))])


async def _lines(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, site_id: uuid.UUID | None) -> list[dict]:
    """Current BOQ lines with norms, with their activity's dates, and their norms."""
    from mesiri.infrastructure.postgres.repositories.material_norms import MaterialNormRepository

    norms = await MaterialNormRepository(conn).for_project(org, project_id)
    if not norms:
        return []
    rows = (await conn.execute(text(
        "SELECT i.id, i.work_type, u.code AS unit, i.planned_quantity, w.planned_start, w.planned_end, "
        "w.status, w.site_id FROM work_package_planned_items i JOIN work_packages w ON w.id = i.work_package_id "
        "JOIN units_of_measure u ON u.id = i.unit_id "
        "WHERE i.organization_id = :org AND w.project_id = :p AND i.superseded_by_id IS NULL AND i.id = ANY(:ids) "
        "AND (CAST(:site AS uuid) IS NULL OR w.site_id = CAST(:site AS uuid))"),
        {"org": org, "p": project_id, "ids": list(norms), "site": site_id})).mappings().all()
    return [{
        "id": r["id"], "work": r["work_type"], "unit": r["unit"], "planned": r["planned_quantity"],
        "start": r["planned_start"], "end": r["planned_end"], "finished": r["status"] == "COMPLETED",
        "site_id": r["site_id"],
        "norms": [{"material_id": n["material_id"], "material": n["material"], "unit": n["unit"],
                   "per_unit": n["quantity_per_unit"], "wastage_pct": n["wastage_pct"]} for n in norms[r["id"]]],
    } for r in rows]


async def _stock(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, site_id: uuid.UUID | None,
                 today: datetime.date) -> dict[Any, dict]:
    """On hand (closing today, all the project's sites or one) and on open orders, per material."""
    from mesiri.domains.procurement.orders import on_order_by_site
    from mesiri.infrastructure.postgres.repositories.materials import PostgresMaterialReadRepository

    rows = await PostgresMaterialReadRepository(conn).get_stock_summary(
        org, date_from=today, date_to=today, project_ids={project_id}, site_id=site_id)
    out: dict[Any, dict] = {}
    for r in rows:
        held = out.setdefault(r["material_id"], {"unit": r["unit"], "on_hand": Decimal(0), "on_order": Decimal(0)})
        if held["unit"] != r["unit"]:
            held["unit"] = "several units"  # never added across units: the plan says the unit differs
        held["on_hand"] += Decimal(str(r["closing"] or 0))
    sites = {str(s) for s in (await conn.execute(text(
        "SELECT id FROM sites WHERE project_id = :p AND organization_id = :org"),
        {"p": project_id, "org": org})).scalars()}
    if site_id is not None:
        sites &= {str(site_id)}
    coming: dict[str, Decimal] = defaultdict(Decimal)
    for (site, material), pending in (await on_order_by_site(conn, org)).items():
        if site in sites:
            coming[material] += pending
    for material, pending in coming.items():
        key = next((k for k in out if str(k) == material), uuid.UUID(material))
        out.setdefault(key, {"unit": None, "on_hand": Decimal(0), "on_order": Decimal(0)})["on_order"] += pending
    return out


async def _suppliers(conn: AsyncConnection, org: uuid.UUID, material_ids: list) -> dict[Any, dict]:
    """MP-03: per material, the supplier who last delivered it (any project) and their lead time, if set."""
    if not material_ids:
        return {}
    rows = (await conn.execute(text(
        "SELECT DISTINCT ON (r.material_id) r.material_id, v.id AS vendor_id, v.name, v.lead_time_days "
        "FROM material_receipts r JOIN vendors v ON v.id = r.vendor_id "
        "WHERE r.organization_id = :org AND r.material_id = ANY(:ids) AND r.movement_reason = 'RECEIVED' "
        "ORDER BY r.material_id, r.occurred_date DESC, r.created_at DESC"),
        {"org": org, "ids": list(material_ids)})).mappings().all()
    return {r["material_id"]: dict(r) for r in rows}


async def load_plan(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, today: datetime.date,
                    weeks: int = 8, site_id: uuid.UUID | None = None) -> dict[str, Any]:
    """The plan with its inputs gathered: used by the route, the order-by note (MP-03) and WhatsApp (MP-04)."""
    from mesiri.domains.schedule.store import measured_by_line

    lines = await _lines(conn, org, project_id, site_id)
    if not lines:
        return plan.build([], {}, today, weeks)
    done = await measured_by_line(conn, org, project_id)
    for line in lines:
        line["done"] = done.get(line["id"], Decimal(0))
    stock = await _stock(conn, org, project_id, site_id, today)
    ids = {n["material_id"] for line in lines for n in line["norms"]}
    for material_id, sup in (await _suppliers(conn, org, list(ids))).items():
        held = stock.setdefault(material_id, {"unit": None, "on_hand": Decimal(0), "on_order": Decimal(0)})
        held.update(supplier=sup["name"], supplier_id=sup["vendor_id"], lead_days=sup["lead_time_days"])
    result = plan.build(lines, stock, today, weeks)
    for row in result["materials"]:
        row["supplier_id"] = (stock.get(row["material_id"]) or {}).get("supplier_id")
    return result


@router.get("/projects/{project_id}/material-plan")
async def material_plan(
    project_id: uuid.UUID,
    weeks: int = Query(default=8, ge=1, le=26),
    site_id: uuid.UUID | None = None,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    from mesiri.application.dpr import project_day

    repo = await _scope(project_id, auth, conn)
    if site_id is not None and not await repo.site_in_project(project_id, site_id):
        raise HTTPException(status_code=422, detail="site_id is not a site of this project")
    org = auth.organization_id
    today = await project_day.company_today(conn, org)
    result = await load_plan(conn, org, project_id, today, weeks, site_id)
    with_norms = (await conn.execute(text(
        "SELECT count(DISTINCT n.planned_item_id) FROM boq_material_norms n "
        "JOIN work_package_planned_items i ON i.id = n.planned_item_id JOIN work_packages w ON w.id = i.work_package_id "
        "WHERE n.organization_id = :org AND w.project_id = :p AND i.superseded_by_id IS NULL"),
        {"org": org, "p": project_id})).scalar_one()
    without = (await conn.execute(text(
        "SELECT count(*) FROM work_package_planned_items i JOIN work_packages w ON w.id = i.work_package_id "
        "WHERE i.organization_id = :org AND w.project_id = :p AND i.superseded_by_id IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM boq_material_norms n WHERE n.planned_item_id = i.id)"),
        {"org": org, "p": project_id})).scalar_one()
    return _exact({"project_id": project_id, "today": today, "site_id": site_id, **result,
                   "lines_with_norms": with_norms, "lines_without_norms": without})
