"""REST API of the Cost control module (``cost``, CC-01 / CC-04), for the dashboard.

Mounted at /cost:
  GET   /centres                     a period's cost split into cost centres (one read model: finance.costs)
  GET   /categories                  the expense categories and the centre each counts in
  PATCH /categories/{category_id}    set or clear a category's centre
  GET   /projects/{project_id}/budget  budget against actual for a project, to date: the BOQ's budget and the
                                       budget earned by the work done, set against what was spent, per kind;
                                       per BOQ line the labour put on it (CC-05)
  GET   /projects/{project_id}/labour  a period's attendance per site, day and trade, and the BOQ lines each is
                                       on (CC-05), with a suggested line for what is on none
  PUT   /projects/{project_id}/labour  put a site's day of one trade on BOQ lines by man-days (empty: take it off)
  GET   /projects/{project_id}/variance  green / amber / red per BOQ line over a period (a day: the site's day),
                                       labour earned against labour put on the line, with each day of the period
                                       (CC-07)

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
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_manage_money, may_view_expenses
from mesiri.domains.costing.centres import CENTRES, cost_centres
from mesiri.domains.costing.labour import group_key, labour_by_line, share_group
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
    # CC-05: the labour put on each line, set against the labour budget the line earned.
    labour = await _labour(conn, repo, auth.organization_id, project_id,
                           datetime.date.fromisoformat(str(centres["date_from"])), today)
    for section in boq["sections"]:
        for ln in section["lines"]:
            ln.update(_line_labour(ln, labour["lines"].get(uuid.UUID(str(ln["id"])))))
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
        "labour_on_lines": {"man_days": _q(sum((v["man_days"] for v in labour["lines"].values()), Decimal(0))),
                            "cost": _m(sum((v["cost"] for v in labour["lines"].values()), Decimal(0)))},
        "labour_not_on_a_line": {"man_days": _q(labour["not_on_a_line"]["man_days"]),
                                 "cost": _m(labour["not_on_a_line"]["cost"]),
                                 "unpriced_man_days": _q(labour["not_on_a_line"]["unpriced_man_days"])},
        "boq": boq,
    }


# -- CC-05: labour put on BOQ lines ---------------------------------------------------------------------------------


def _plain(v: Decimal) -> str:
    """A quantity as a short exact string with no exponent: 20 -> "20", 2.50 -> "2.5" (never "2E+1")."""
    text = format(Decimal(v), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _q(v: Decimal) -> str:
    """Man-days as an exact short string ("3", "2.5", "20")."""
    return _plain(Decimal(v).quantize(_C))


def _line_labour(line: dict, labour: dict | None) -> dict:
    """A BOQ line's labour: man-days and cost put on it, and the labour budget it earned less that cost."""
    if not labour:
        return {"labour_man_days": "0", "labour_cost": None, "labour_unpriced_man_days": "0", "labour_difference": None}
    cost = labour["cost"] if labour["man_days"] > labour["unpriced_man_days"] else None
    earned = line.get("earned_labour")
    return {
        "labour_man_days": _q(labour["man_days"]),
        "labour_cost": _m(cost) if cost is not None else None,
        "labour_unpriced_man_days": _q(labour["unpriced_man_days"]),
        "labour_difference": _m(Decimal(earned) - cost) if earned is not None and cost is not None else None,
    }


async def _labour(conn: AsyncConnection, repo, org: uuid.UUID, project_id: uuid.UUID,
                  date_from: datetime.date, date_to: datetime.date) -> dict:
    """The project's labour per BOQ line and not on a line, over the period (attendance counted by Labour)."""
    from mesiri.infrastructure.postgres.repositories.labour_allocations import (
        PostgresLabourAllocationRepository,
    )
    from mesiri.infrastructure.postgres.repositories.workforce import (
        PostgresWorkforceReadRepository,
    )

    groups = await PostgresWorkforceReadRepository(conn).attendance_by_site_day_trade(
        organization_id=org, project_id=project_id, date_from=date_from, date_to=date_to)
    allocations = await PostgresLabourAllocationRepository(conn).list(org, project_id, date_from, date_to)
    return labour_by_line(groups, allocations, await repo.current_revision_of(org, project_id))


async def _project_repo(auth: AuthorizationContext, conn: AsyncConnection, project_id: uuid.UUID):
    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

    _may_see(auth)
    if not auth.project_scope.grants_all_org_projects and project_id not in auth.project_scope.project_ids:
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    repo = PostgresBoqRepository(conn)
    if not await repo.project_exists(auth.organization_id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return repo


def _trade_key(trade: str | None) -> str:
    """The trade as attendance groups it (trimmed, lower-cased; '' when none)."""
    return (trade or "").strip().lower()


async def _labour_groups(conn: AsyncConnection, repo, org: uuid.UUID, project_id: uuid.UUID,
                         date_from: datetime.date, date_to: datetime.date) -> list[dict]:
    """Attendance per site, day and trade, each with the lines it is on and a suggested line for the rest."""
    from mesiri.domains.progress.boq import suggest_line
    from mesiri.infrastructure.postgres.repositories.labour_allocations import (
        PostgresLabourAllocationRepository,
    )
    from mesiri.infrastructure.postgres.repositories.workforce import (
        PostgresWorkforceReadRepository,
    )

    groups = await PostgresWorkforceReadRepository(conn).attendance_by_site_day_trade(
        organization_id=org, project_id=project_id, date_from=date_from, date_to=date_to)
    allocations = await PostgresLabourAllocationRepository(conn).list(org, project_id, date_from, date_to)
    current = await repo.current_revision_of(org, project_id)
    lines = await repo.list_lines(org, project_id)
    line_by_id = {ln["id"]: ln for ln in lines}
    by_group: dict[tuple, list[dict]] = {}
    for a in allocations:
        by_group.setdefault(group_key(a["site_id"], a["work_date"], a["trade_key"]), []).append(
            {"line_id": current.get(a["planned_item_id"], a["planned_item_id"]), "man_days": a["man_days"]})
    # The lines that got measured work on a site and day: when only one did, that day's labour most likely
    # went into it (a suggestion only; a person confirms).
    worked: dict[tuple, set] = {}
    for w in await repo.work_updates(org, project_id, unlinked_only=False, limit=500):
        if w["line_id"]:
            worked.setdefault((str(w["site_id"]) if w["site_id"] else None, str(w["activity_date"])), set()).add(
                current.get(w["line_id"], w["line_id"]))
    sites = {r["id"]: r["name"] for r in (await conn.execute(
        text("SELECT id, name FROM sites WHERE project_id = :p"), {"p": project_id})).mappings().all()}
    out = []
    for g in groups:
        key = group_key(g["site_id"], g["work_date"], g["trade_key"])
        shared = share_group(g, by_group.get(key, []))
        suggestion = None
        if shared["not_on_a_line"]["man_days"] > 0:
            said = " ".join(g["activities"] or [])
            suggestion = suggest_line(said, None, None, lines, any_unit=True) if said else None
            same_day = worked.get(key[:2], set())
            if suggestion is None and len(same_day) == 1:
                suggestion = next(iter(same_day))
        out.append({
            "site_id": g["site_id"], "site_name": sites.get(g["site_id"]), "date": g["work_date"],
            "trade": g["trade"] or None, "trade_key": g["trade_key"], "activities": g["activities"] or [],
            "man_days": _q(shared["man_days"]),
            "cost": _m(shared["cost"]) if shared["cost"] is not None else None,
            "on_lines": [{
                "line_id": p["line_id"], "work": (line_by_id.get(p["line_id"]) or {}).get("work_type"),
                "unit": (line_by_id.get(p["line_id"]) or {}).get("unit"),
                "man_days": _q(p["man_days"]), "cost": _m(p["cost"]) if p["cost"] is not None else None,
            } for p in shared["on_lines"]],
            "not_on_a_line": {"man_days": _q(shared["not_on_a_line"]["man_days"]),
                              "cost": _m(shared["not_on_a_line"]["cost"])
                              if shared["not_on_a_line"]["cost"] is not None else None},
            "over_allocated": shared["over_allocated"],
            "suggested_line_id": suggestion,
        })
    return out


@router.get("/projects/{project_id}/labour")
async def project_labour(
    project_id: uuid.UUID,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    unallocated: bool = False,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """A period's attendance per site, day and trade (newest first), the BOQ lines each was put on, and what is on
    none, with a suggested line (never saved by itself). ``unallocated``: only groups with man-days on no line."""
    repo = await _project_repo(auth, conn, project_id)
    date_to = date_to or await _today(conn, auth.organization_id)
    date_from = date_from or date_to - datetime.timedelta(days=29)
    if date_from > date_to or (date_to - date_from).days > 731:
        raise HTTPException(status_code=422, detail="Pick a period of at most two years, start before end.")
    groups = await _labour_groups(conn, repo, auth.organization_id, project_id, date_from, date_to)
    summary = {"man_days": Decimal(0), "cost": Decimal(0), "left_man_days": Decimal(0), "left_cost": Decimal(0)}
    for g in groups:
        summary["man_days"] += Decimal(g["man_days"])
        summary["cost"] += Decimal(g["cost"] or 0)
        summary["left_man_days"] += Decimal(g["not_on_a_line"]["man_days"])
        summary["left_cost"] += Decimal(g["not_on_a_line"]["cost"] or 0)
    if unallocated:
        groups = [g for g in groups if Decimal(g["not_on_a_line"]["man_days"]) > 0]
    return {
        "project_id": str(project_id), "date_from": str(date_from), "date_to": str(date_to),
        "total": {"man_days": _q(summary["man_days"]), "cost": _m(summary["cost"])},
        "not_on_a_line": {"man_days": _q(summary["left_man_days"]), "cost": _m(summary["left_cost"])},
        "groups": [{**g, "site_id": str(g["site_id"]) if g["site_id"] else None, "date": str(g["date"]),
                    "suggested_line_id": str(g["suggested_line_id"]) if g["suggested_line_id"] else None,
                    "on_lines": [{**p, "line_id": str(p["line_id"])} for p in g["on_lines"]]} for g in groups],
    }


class LabourPart(BaseModel):
    line_id: uuid.UUID
    man_days: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class LabourOnLines(BaseModel):
    site_id: uuid.UUID | None = None
    date: datetime.date
    trade: str | None = Field(default=None, max_length=200, description="As attendance says it; empty when none")
    lines: list[LabourPart] = Field(default_factory=list, max_length=50, description="Empty takes it off every line")


@router.put("/projects/{project_id}/labour")
async def put_labour_on_lines(
    project_id: uuid.UUID,
    body: LabourOnLines,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Put a site's day of one trade on BOQ lines by man-days, replacing what it was on.

    Refused (422) for a line not in this project or given twice, and for more man-days than attendance counts
    that day; 404 when attendance has no such site, day and trade. Returns the group as the list shows it.
    """
    from mesiri.infrastructure.postgres.repositories.labour_allocations import (
        PostgresLabourAllocationRepository,
    )

    repo = await _project_repo(auth, conn, project_id)
    trade_key = _trade_key(body.trade)
    groups = await _labour_groups(conn, repo, auth.organization_id, project_id, body.date, body.date)
    key = group_key(body.site_id, body.date, trade_key)
    group = next((g for g in groups if group_key(g["site_id"], g["date"], g["trade_key"]) == key), None)
    if group is None:
        raise HTTPException(status_code=404, detail="No attendance for that site, day and trade.")
    seen: set[uuid.UUID] = set()
    for part in body.lines:
        if part.line_id in seen:
            raise HTTPException(status_code=422, detail="A BOQ line is given twice; put its man-days together.")
        seen.add(part.line_id)
        if await repo.get_line(auth.organization_id, project_id, part.line_id) is None:
            raise HTTPException(status_code=422, detail="That BOQ line is not in this project.")
    put = sum((p.man_days for p in body.lines), Decimal(0))
    if put > Decimal(group["man_days"]):
        raise HTTPException(status_code=422, detail=(
            f"That is {_q(put)} man-days; attendance has {group['man_days']} for this day and trade."))
    await PostgresLabourAllocationRepository(conn).replace_group(
        auth.organization_id, project_id, body.site_id, body.date, trade_key,
        [(p.line_id, p.man_days) for p in body.lines], auth.user_id)
    groups = await _labour_groups(conn, repo, auth.organization_id, project_id, body.date, body.date)
    group = next(g for g in groups if group_key(g["site_id"], g["date"], g["trade_key"]) == key)
    return {**group, "site_id": str(group["site_id"]) if group["site_id"] else None, "date": str(group["date"]),
            "suggested_line_id": str(group["suggested_line_id"]) if group["suggested_line_id"] else None,
            "on_lines": [{**p, "line_id": str(p["line_id"])} for p in group["on_lines"]]}


# -- CC-07: green / amber / red per BOQ line -------------------------------------------------------------------------


def _money_or_none(v: Decimal | None) -> str | None:
    return _m(v) if v is not None else None


def _variance_out(v: dict, line: dict, section: str | None) -> dict:
    return {
        "line_id": str(v["line_id"]), "boq_code": line.get("boq_code"), "work": line["work_type"],
        "unit": line["unit"], "section": section,
        "done_quantity": _q3(v["done_quantity"]), "labour_man_days": _q(v["labour_man_days"]),
        "labour_unpriced_man_days": _q(v["labour_unpriced_man_days"]),
        "labour_rate": _money_or_none(v["labour_rate"]), "earned_labour": _money_or_none(v["earned_labour"]),
        "labour_cost": _money_or_none(v["labour_cost"]), "difference": _money_or_none(v["difference"]),
        "cost_per_unit": _money_or_none(v["cost_per_unit"]),
        "ratio": str(v["ratio"]) if v["ratio"] is not None else None,
        "colour": v["colour"], "reason": v["reason"],
    }


def _q3(v: Decimal) -> str:
    """A work quantity (3 decimals at most) as a short exact string."""
    return _plain(Decimal(v).quantize(Decimal("0.001")))


def _summary_out(s: dict) -> dict:
    return {**s, "earned_labour": _money_or_none(s["earned_labour"]), "labour_cost": _money_or_none(s["labour_cost"]),
            "difference": _money_or_none(s["difference"]), "ratio": str(s["ratio"]) if s["ratio"] is not None else None}


@router.get("/projects/{project_id}/variance")
async def project_variance(
    project_id: uuid.UUID,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    site_id: uuid.UUID | None = None,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Green / amber / red per BOQ line over a period (default: the last 7 days), worst first.

    Per line: work done in the period, the labour budget it earned, the labour put on the line (CC-05), the cost
    per unit against the rate, the colour and why (``domains/costing/variance.py``). The period's summary, each
    day's colour, the labour not on a line (not coloured, said), and materials for the project (earned against
    bought; not per line until the consumption register, CC-08). ``site_id``: one site's lines and labour.
    """
    from mesiri.domains.costing.variance import line_variance, sort_worst_first, summarise
    from mesiri.domains.progress.boq_router import counted_work
    from mesiri.infrastructure.postgres.repositories.labour_allocations import (
        PostgresLabourAllocationRepository,
    )
    from mesiri.infrastructure.postgres.repositories.workforce import (
        PostgresWorkforceReadRepository,
    )

    repo = await _project_repo(auth, conn, project_id)
    if site_id is not None and not await repo.site_in_project(project_id, site_id):
        raise HTTPException(status_code=422, detail="site_id is not a site of this project")
    org = auth.organization_id
    date_to = date_to or await _today(conn, org)
    date_from = date_from or date_to - datetime.timedelta(days=6)
    if date_from > date_to or (date_to - date_from).days > 731:
        raise HTTPException(status_code=422, detail="Pick a period of at most two years, start before end.")

    lines = await repo.list_lines(org, project_id)
    line_by_id = {ln["id"]: ln for ln in lines}
    sections = {s["id"]: s["name"] for s in await repo.list_sections(org, project_id)}

    def in_scope(site: uuid.UUID | None) -> bool:
        return site_id is None or site == site_id

    work = [w for w in await counted_work(repo, org, project_id, lines)
            if date_from <= w["work_date"] <= date_to and in_scope(w["site_id"])]
    groups = [g for g in await PostgresWorkforceReadRepository(conn).attendance_by_site_day_trade(
        organization_id=org, project_id=project_id, date_from=date_from, date_to=date_to) if in_scope(g["site_id"])]
    allocations = await PostgresLabourAllocationRepository(conn).list(org, project_id, date_from, date_to)
    current = await repo.current_revision_of(org, project_id)

    def judge(day: datetime.date | None) -> tuple[list[dict], dict]:
        done: dict = {}
        for w in work:
            if (day is None or w["work_date"] == day) and w["quantity"] is not None:
                done[w["line_id"]] = done.get(w["line_id"], Decimal(0)) + w["quantity"]
        labour = labour_by_line([g for g in groups if day is None or g["work_date"] == day], allocations, current)
        out = []
        for line_id in set(done) | set(labour["lines"]):
            if line_id not in line_by_id:
                continue
            v = line_variance(line_by_id[line_id], done.get(line_id, Decimal(0)), labour["lines"].get(line_id))
            if v:
                out.append(v)
        return sort_worst_first(out), labour

    period_lines, labour = judge(None)
    days = []
    for day in sorted({w["work_date"] for w in work} | {g["work_date"] for g in groups}, reverse=True):
        day_lines, day_labour = judge(day)
        days.append({"date": str(day), **_summary_out(summarise(day_lines)),
                     "attendance_cost": _m(day_labour["total"]["cost"]),
                     "not_on_a_line_cost": _m(day_labour["not_on_a_line"]["cost"])})

    # Materials, for the project: the material budget the period's work earned against what was bought in the
    # period (the cost read model's materials centre). Not coloured: bought is not used, the register (CC-08) is.
    earned_material = sum((w["quantity"] * Decimal(line_by_id[w["line_id"]]["material_rate"]) for w in work
                           if w["quantity"] is not None and line_by_id[w["line_id"]].get("material_rate") is not None),
                          Decimal(0))
    centres = await cost_centres(conn, org, date_from=date_from, date_to=date_to, **_scope(auth, project_id, site_id))
    bought = next((Decimal(c["amount"]) for c in centres["centres"] if c["key"] == "materials"), Decimal(0))

    return {
        "project_id": str(project_id), "site_id": str(site_id) if site_id else None,
        "date_from": str(date_from), "date_to": str(date_to),
        "thresholds": {"green_at": "1.00", "amber_at": "0.90"},
        "summary": _summary_out(summarise(period_lines)),
        "labour": {"attendance_cost": _m(labour["total"]["cost"]), "man_days": _q(labour["total"]["man_days"]),
                   "not_on_a_line": {"man_days": _q(labour["not_on_a_line"]["man_days"]),
                                     "cost": _m(labour["not_on_a_line"]["cost"])}},
        "materials": {"earned": _m(earned_material), "bought": _m(bought)},
        "work_in_other_unit": sum(1 for w in work if w["quantity"] is None),
        "lines": [_variance_out(v, line_by_id[v["line_id"]], sections.get(line_by_id[v["line_id"]]["work_package_id"]))
                  for v in period_lines],
        "days": days,
    }
