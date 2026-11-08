"""REST API of the Cost control module (``cost``, CC-01 / CC-04), for the dashboard.

Mounted at /cost:
  GET   /centres                     a period's cost split into cost centres (one read model: finance.costs)
  GET   /categories                  the expense categories and the centre each counts in
  PATCH /categories/{category_id}    set or clear a category's centre
  GET   /projects/{project_id}/budget  budget against actual for a project, to date: the BOQ's budget and the
                                       budget earned by the work done, set against what was spent, per kind

Rates, earned value and money are shown to the roles that see spending (``may_view_expenses``: owner, admin,
finance, project manager), within their projects; who else sees them is decision D-CC4, not settled here. Setting a
category's centre is for the roles that manage money (owner, admin, finance).
Plan: docs/plans/cost-control-plan.md.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_manage_money, may_view_expenses
from mesiri.domains.costing.centres import CENTRES, cost_centres
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(prefix="/cost", tags=["cost"], dependencies=[Depends(require_module("cost"))])

_C = Decimal("0.01")
# The BOQ's budget rates and the centre whose spending they are set against.
_KINDS = (("labour", "Labour"), ("material", "Materials"), ("subcontract", "Subcontract"))
_CENTRE_OF = {"labour": "labour", "material": "materials", "subcontract": "subcontract"}


def _m(v: Decimal) -> str:
    return str(Decimal(v).quantize(_C))


def _may_see(auth: AuthorizationContext) -> None:
    if not may_view_expenses(auth.role):
        raise HTTPException(status_code=403, detail="Cost control is shown to the roles that see spending.")


async def _today(conn: AsyncConnection, org: uuid.UUID) -> datetime.date:
    from mesiri.application.dpr import project_day

    return await project_day.company_today(conn, org)


def _scope(auth: AuthorizationContext, project_id: uuid.UUID | None, site_id: uuid.UUID | None) -> dict:
    """The caller's projects and sites, the same rule as the Expenses page's Full cost (finance /costs)."""
    from mesiri.domains.materials.router import _resolve_project_ids, _site_filter_denied
    from mesiri.domains.procurement.router import _visible

    project_ids, denied = _resolve_project_ids(auth, project_id)
    if denied or _site_filter_denied(auth, project_id, site_id):
        project_ids = set()
    return {"project_ids": project_ids, "site_id": site_id, "visible": lambda p, s: _visible(auth, p, s)}


@router.get("/centres")
async def get_centres(
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Where the period's money went, per cost centre, and what in each (deliveries, attendance, machines, which
    expense categories). Expenses whose category has no centre are "not set", with the categories to fix."""
    _may_see(auth)
    date_to = date_to or await _today(conn, auth.organization_id)
    date_from = date_from or date_to - datetime.timedelta(days=29)
    if date_from > date_to or (date_to - date_from).days > 731:
        raise HTTPException(status_code=422, detail="Pick a period of at most two years, start before end.")
    return await cost_centres(conn, auth.organization_id, date_from=date_from, date_to=date_to,
                              **_scope(auth, project_id, site_id))


class CentreIn(BaseModel):
    cost_centre: Literal["materials", "labour", "subcontract", "equipment", "fuel", "overhead", "other"] | None


async def _categories(conn: AsyncConnection, org: uuid.UUID, category_id: uuid.UUID | None = None) -> list[dict]:
    rows = (await conn.execute(text(
        "SELECT id, name, code, status, cost_centre FROM expense_categories WHERE organization_id = :org "
        "AND (CAST(:id AS uuid) IS NULL OR id = CAST(:id AS uuid)) ORDER BY status, name"),
        {"org": org, "id": category_id})).mappings().all()
    return [{**dict(r), "id": str(r["id"])} for r in rows]


@router.get("/categories")
async def list_categories(
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    _may_see(auth)
    return {"centres": [{"key": k, "label": v} for k, v in CENTRES.items()],
            "categories": await _categories(conn, auth.organization_id)}


@router.patch("/categories/{category_id}")
async def set_category_centre(
    category_id: uuid.UUID,
    body: CentreIn,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Which cost centre a category's expenses count in; null takes it back to "not set"."""
    if not may_manage_money(auth.role):
        raise HTTPException(status_code=403, detail="Only the owner, an admin or finance can change cost centres.")
    res = await conn.execute(
        text("UPDATE expense_categories SET cost_centre = :c, updated_at = now(), updated_by = :u "
             "WHERE id = :id AND organization_id = :org"),
        {"c": body.cost_centre, "u": auth.user_id, "id": category_id, "org": auth.organization_id},
    )
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="Category not found")
    return (await _categories(conn, auth.organization_id, category_id))[0]


@router.get("/projects/{project_id}/budget")
async def project_budget(
    project_id: uuid.UUID,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Budget against actual for a project, to date.

    Per BOQ line: planned, done, left and the budget earned (the BOQ's own read, CC-04). For the project, per kind
    (labour, materials, subcontract): the budget, the budget earned by the work done, and the money spent in that
    cost centre since the first record. Spending in other centres (equipment, fuel, overhead, other, not set) has no
    BOQ rate to be set against and is listed apart. Earned only counts work put on a BOQ line, so the work not on one
    yet is counted and said: a low earned figure may mean work is waiting to be put on its line.
    """
    from mesiri.domains.progress.boq_router import _boq
    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

    _may_see(auth)
    if not auth.project_scope.grants_all_org_projects and project_id not in auth.project_scope.project_ids:
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    repo = PostgresBoqRepository(conn)
    if not await repo.project_exists(auth.organization_id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")

    boq = await _boq(repo, auth.organization_id, project_id)
    lines = [ln for s in boq["sections"] for ln in s["lines"]]
    # To date: from two years back, or earlier when the project's expenses or work go back further. Attendance and
    # deliveries have no cheap project-wide minimum, so the two-year floor is what keeps them from being missed.
    today = await _today(conn, auth.organization_id)
    start = (await conn.execute(text(
        "SELECT LEAST((SELECT MIN(occurred_date) FROM expenses WHERE project_id = :p), "
        "(SELECT MIN(activity_date) FROM activities WHERE project_id = :p))"), {"p": project_id})).scalar()
    floor = today - datetime.timedelta(days=730)
    centres = await cost_centres(conn, auth.organization_id, date_from=min(start or floor, floor), date_to=today,
                                 **_scope(auth, project_id, None))
    spent = {c["key"]: Decimal(c["amount"]) for c in centres["centres"]}

    kinds = []
    for kind, label in _KINDS:
        rate = f"{kind}_rate"
        budget = [Decimal(ln["planned_quantity"]) * Decimal(ln[rate]) for ln in lines if ln.get(rate) is not None]
        earned = [Decimal(ln[f"earned_{kind}"]) for ln in lines if ln.get(f"earned_{kind}") is not None]
        actual = spent[_CENTRE_OF[kind]]
        earned_total = sum(earned, Decimal(0))
        kinds.append({
            "kind": kind, "label": label,
            "budget": _m(sum(budget, Decimal(0))) if budget else None,
            "earned": _m(earned_total) if earned else None,
            "actual": _m(actual),
            "difference": _m(earned_total - actual) if earned else None,
            "lines_priced": len(budget),
        })
    unlinked = len(await repo.work_updates(auth.organization_id, project_id, unlinked_only=True, limit=500))
    other = [c for c in centres["centres"] if c["key"] not in _CENTRE_OF.values() and Decimal(c["amount"])]
    return {
        "project_id": str(project_id),
        "date_from": centres["date_from"],
        "date_to": centres["date_to"],
        "kinds": kinds,
        "other_spending": [{"key": c["key"], "label": c["label"], "amount": c["amount"]} for c in other],
        "not_set": centres["not_set"]["amount"],
        "total_spent": centres["total"],
        "work_not_on_a_line": unlinked,
        "boq": boq,
    }
