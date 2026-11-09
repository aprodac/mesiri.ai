"""REST API for wages, advances, the muster roll and labour teams (LW-01..LW-05; docs/plans/wages-and-labour-plan.md,
approved by Ilan 9 Nov 2026). Mounted under /labour with the labour module switch.

  GET  /labour/pay/summary                       wages due, drafts waiting, advances outstanding (Home, project hub)
  GET  /labour/advances                          advances given (project / site), newest first
  GET  /labour/advances/balances                 each payee's outstanding advance
  POST /labour/advances                          give an advance (from a money account)
  POST /labour/advances/{id}/void                take it back (the money returns to its account)
  GET  /labour/wage-sheets                       sheets (project / site), newest first
  GET  /labour/wage-sheets/open                  the sheet for the pay week a date falls in, made on first open
  GET  /labour/wage-sheets/{id}                  rows, payments, slips, what changed since approval
  PATCH /labour/wage-sheets/{id}/rows/{row_id}   advance recovered, deductions (a draft only)
  POST /labour/wage-sheets/{id}/approve          draft -> approved;  /reopen  approved -> draft (nothing paid)
  POST /labour/wage-sheets/{id}/pay              pay one row or every row still due, from a money account
  GET  /labour/muster                            a site's month: each worker's days (P / ½ / A, overtime)
  GET  /labour/teams                             labour contractors (vendors of kind labour) with their workers

Who may (D-W5): anyone who can reach the site records an advance, from an account they hold unless they manage money;
wage figures, approving and paying are for the roles that see the company's spending (EXPENSE_VIEW_ROLES).
"""

from __future__ import annotations

import calendar
import datetime
import uuid
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_manage_money, may_view_expenses
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.domains.workforce import pay
from mesiri.domains.workforce import pay_store as store
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.workforce import counted_line_sql

router = APIRouter(prefix="/labour", tags=["labour"], dependencies=[Depends(require_module("labour"))])

Source = Literal["web", "whatsapp"]


def _scope(auth: AuthorizationContext) -> set | None:
    return None if auth.project_scope.grants_all_org_projects else set(auth.project_scope.project_ids)


def _reach(auth: AuthorizationContext, project_id: uuid.UUID, site_id: uuid.UUID | None = None) -> None:
    if not (auth.project_scope.grants_all_org_projects or project_id in auth.project_scope.project_ids):
        raise HTTPException(status_code=404, detail="Project not found")
    if site_id is not None:
        scope = auth.site_scope_for_project(project_id)
        if not (scope.grants_all_sites or site_id in scope.site_ids):
            raise HTTPException(status_code=404, detail="Site not found")


def _money_role(auth: AuthorizationContext) -> None:
    if not may_view_expenses(auth.role):
        raise HTTPException(status_code=403, detail="Wages are for the owner, finance and project managers")


async def _site_project(conn: AsyncConnection, org: uuid.UUID, site_id: uuid.UUID) -> uuid.UUID:
    p = (await conn.execute(text("SELECT project_id FROM sites WHERE id = :s AND organization_id = :org"),
                            {"s": site_id, "org": org})).scalar()
    if p is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return p


# -- summary -----------------------------------------------------------------------------------------------------------

@router.get("/pay/summary")
async def pay_summary(project_id: uuid.UUID | None = None, auth: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    _money_role(auth)
    if project_id is not None:
        _reach(auth, project_id)
    return await store.owed_summary(conn, auth.organization_id, _scope(auth), project_id)


# -- advances ----------------------------------------------------------------------------------------------------------

class AdvanceIn(BaseModel):
    project_id: uuid.UUID | None = Field(default=None, description="The project; taken from site_id when only that is sent")
    site_id: uuid.UUID | None = None
    worker_id: uuid.UUID | None = Field(default=None, description="A worker on the register")
    vendor_id: uuid.UUID | None = Field(default=None, description="A labour contractor (their team)")
    payee_name: str | None = Field(default=None, max_length=120, description="Who, in words, when not on the register")
    amount: Decimal = Field(gt=0)
    given_on: datetime.date | None = None
    account_id: uuid.UUID | None = Field(default=None, description="The money account it came out of (petty cash)")
    note: str | None = Field(default=None, max_length=500)
    source: Source = "web"


class VoidIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


@router.get("/advances")
async def advances(project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None,
                   auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    rows = await store.list_advances(conn, auth.organization_id, _scope(auth), project_id, site_id)
    if not may_view_expenses(auth.role):  # a site engineer sees their sites' advances only
        rows = [r for r in rows if r["site_id"] is None or _site_ok(auth, r["project_id"], r["site_id"])]
    return {"items": rows}


def _site_ok(auth: AuthorizationContext, project_id: uuid.UUID, site_id: uuid.UUID) -> bool:
    scope = auth.site_scope_for_project(project_id)
    return scope.grants_all_sites or site_id in scope.site_ids


@router.get("/advances/balances")
async def advance_balances(project_id: uuid.UUID | None = None, auth: AuthorizationContext = Depends(get_auth_context),
                           conn: AsyncConnection = Depends(get_db_conn)):
    _money_role(auth)
    org = auth.organization_id
    scope = _scope(auth)
    balances = await store.advance_balances(conn, org, project_id, project_ids=scope)
    team = await store.worker_team(conn, org)
    named = await store.teams(conn, org)
    workers, vendors = await store.payee_names(conn, org)
    rows: dict[str, dict[str, Any]] = {}
    for a in await store.list_advances(conn, org, scope, project_id):
        if a["voided_at"]:
            continue
        key = store.advance_key(a, team, named)
        kind, _, ident = key.partition(":")
        name = vendors.get(ident) if kind == "vendor" else workers.get(ident) if kind == "worker" else a["payee_name"]
        r = rows.setdefault(key, {"payee_key": key, "payee_name": name or a["payee_name"], "given": Decimal(0),
                                  "last_given_on": a["given_on"], "count": 0,
                                  "vendor_id": ident if kind == "vendor" else None,
                                  "worker_id": ident if kind == "worker" else None})
        r["given"] += Decimal(a["amount"])
        r["count"] += 1
    for key, r in rows.items():
        r["outstanding"] = balances.get(key, Decimal(0))
        r["recovered"] = pay.money(r["given"] - r["outstanding"])
    items = sorted(rows.values(), key=lambda r: -r["outstanding"])
    return {"items": items, "outstanding": pay.money(sum((r["outstanding"] for r in items if r["outstanding"] > 0), Decimal(0)))}


@router.post("/advances", status_code=201)
async def give_advance(body: AdvanceIn, auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    org = auth.organization_id
    project_id = body.project_id or (await _site_project(conn, org, body.site_id) if body.site_id else None)
    if project_id is None:
        raise HTTPException(status_code=422, detail="Say which project or site the advance is for")
    _reach(auth, project_id, body.site_id)
    if body.worker_id and body.vendor_id:
        raise HTTPException(status_code=422, detail="An advance goes to a worker or a team, not both")
    name = body.payee_name
    if body.worker_id:
        name = (await conn.execute(text("SELECT name FROM workforce_workers WHERE id = :id AND organization_id = :org"),
                                   {"id": body.worker_id, "org": org})).scalar()
    elif body.vendor_id:
        name = (await conn.execute(text("SELECT name FROM vendors WHERE id = :id AND organization_id = :org"),
                                   {"id": body.vendor_id, "org": org})).scalar()
    if not name:
        raise HTTPException(status_code=422, detail="Say who the advance is for")
    if body.account_id is not None:
        acct = (await conn.execute(text(
            "SELECT owner_user_id, status FROM money_accounts WHERE id = :id AND organization_id = :org"),
            {"id": body.account_id, "org": org})).mappings().first()
        if acct is None or acct["status"] != "active":
            raise HTTPException(status_code=404, detail="Money account not found")
        if not may_manage_money(auth.role) and acct["owner_user_id"] != auth.user_id:
            raise HTTPException(status_code=403, detail="You can give an advance from your own cash box only")
    advance_id = await store.give_advance(conn, org, {
        "project_id": project_id, "site_id": body.site_id, "worker_id": body.worker_id, "vendor_id": body.vendor_id,
        "payee_name": name, "amount": pay.money(body.amount), "given_on": body.given_on or datetime.date.today(),
        "account_id": body.account_id, "note": body.note, "source": body.source}, auth.user_id)
    return await store.get_advance(conn, org, advance_id)


@router.post("/advances/{advance_id}/void")
async def void_advance(advance_id: uuid.UUID, body: VoidIn, auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    a = await store.get_advance(conn, auth.organization_id, advance_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Advance not found")
    _reach(auth, a["project_id"], a["site_id"])
    if a["created_by"] != auth.user_id and not may_manage_money(auth.role):
        raise HTTPException(status_code=403, detail="Only who gave it, or the owner or finance, can take it back")
    if not await store.void_advance(conn, auth.organization_id, advance_id, auth.user_id, body.reason):
        raise HTTPException(status_code=409, detail="Already taken back")
    return await store.get_advance(conn, auth.organization_id, advance_id)


# -- wage sheets -------------------------------------------------------------------------------------------------------

class RowPatch(BaseModel):
    advances_recovered: Decimal | None = Field(default=None, ge=0, description="Advance to take back from this row")
    reset_recovery: bool = Field(default=False, description="Back to the default: all outstanding, up to what it earns")
    deductions: list[dict[str, Any]] | None = Field(default=None, description="[{reason, amount}]; replaces the list")


class PayIn(BaseModel):
    row_id: uuid.UUID | None = Field(default=None, description="One row; omitted: every row still due")
    amount: Decimal | None = Field(default=None, gt=0, description="Part payment of one row; omitted: what is due")
    account_id: uuid.UUID | None = Field(default=None, description="The money account it is paid from")
    paid_on: datetime.date | None = None
    note: str | None = Field(default=None, max_length=300)
    source: Source = "web"


@router.get("/wage-sheets")
async def wage_sheets(project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None,
                      auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    _money_role(auth)
    return {"items": await store.list_sheets(conn, auth.organization_id, _scope(auth), project_id, site_id)}


async def _detail(conn: AsyncConnection, org: uuid.UUID, sheet: dict[str, Any]) -> dict[str, Any]:
    rows = await store.sheet_rows(conn, sheet["id"])
    paid = await store.payments(conn, [r["id"] for r in rows])
    by_row: dict[Any, list] = {}
    for p in paid:
        by_row.setdefault(p["row_id"], []).append(p)
    owed = await store.advance_balances(conn, org, sheet["project_id"], exclude_sheet=sheet["id"], until=sheet["period_to"])
    for r in rows:
        r["payments"] = by_row.get(r["id"], [])
        r["due"] = pay.money(Decimal(r["net"]) - Decimal(r["paid"]))
        r["advance_outstanding"] = owed.get(r["payee_key"], Decimal(0))
        r["slip"] = pay.slip_text(r, sheet["period_from"], sheet["period_to"], sheet["project_name"])
    totals = {k: pay.money(sum((Decimal(r[k]) for r in rows), Decimal(0)))
              for k in ("man_days", "gross", "overtime_amount", "advances_recovered", "net", "paid", "due")}
    totals["deductions"] = pay.money(sum((pay.deductions_total(r["deductions"]) for r in rows), Decimal(0)))
    totals["unpriced_man_days"] = sum((Decimal(r["unpriced_man_days"]) for r in rows), Decimal(0))
    return {**sheet, "rows": rows, "totals": totals, "changed": await store.changed_since_approval(conn, org, sheet, rows)}


@router.get("/wage-sheets/open")
async def open_sheet(project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None,
                     date: datetime.date | None = None, auth: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    _money_role(auth)
    org = auth.organization_id
    project_id = project_id or (await _site_project(conn, org, site_id) if site_id else None)
    if project_id is None:
        raise HTTPException(status_code=422, detail="Pick a project or a site")
    _reach(auth, project_id, site_id)
    period_from, period_to = pay.week_of(date or datetime.date.today())
    sheet = await store.open_sheet(conn, org, project_id, site_id, period_from, period_to, auth.user_id)
    return await _detail(conn, org, await store.get_sheet(conn, org, sheet["id"]))


async def _sheet(conn: AsyncConnection, auth: AuthorizationContext, sheet_id: uuid.UUID) -> dict[str, Any]:
    _money_role(auth)
    sheet = await store.get_sheet(conn, auth.organization_id, sheet_id)
    if sheet is None:
        raise HTTPException(status_code=404, detail="Wage sheet not found")
    _reach(auth, sheet["project_id"], sheet["site_id"])
    return sheet


@router.get("/wage-sheets/{sheet_id}")
async def wage_sheet(sheet_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    sheet = await _sheet(conn, auth, sheet_id)
    if sheet["status"] == "draft":
        await store.refresh(conn, auth.organization_id, sheet)
    return await _detail(conn, auth.organization_id, sheet)


@router.patch("/wage-sheets/{sheet_id}/rows/{row_id}")
async def edit_row(sheet_id: uuid.UUID, row_id: uuid.UUID, body: RowPatch,
                   auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    sheet = await _sheet(conn, auth, sheet_id)
    if sheet["status"] != "draft":
        raise HTTPException(status_code=409, detail="Reopen the sheet to change it")
    if body.deductions is not None:
        for d in body.deductions:
            if not str(d.get("reason") or "").strip() or Decimal(str(d.get("amount") or 0)) <= 0:
                raise HTTPException(status_code=422, detail="Each deduction needs a reason and an amount")
    await store.set_row(conn, auth.organization_id, sheet, row_id, body.advances_recovered, body.reset_recovery,
                        body.deductions)
    return await _detail(conn, auth.organization_id, sheet)


@router.post("/wage-sheets/{sheet_id}/approve")
async def approve(sheet_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                  conn: AsyncConnection = Depends(get_db_conn)):
    sheet = await _sheet(conn, auth, sheet_id)
    if sheet["status"] != "draft":
        raise HTTPException(status_code=409, detail="Already approved")
    await store.refresh(conn, auth.organization_id, sheet)
    await store.set_status(conn, sheet_id, "approved", auth.user_id)
    return await _detail(conn, auth.organization_id, await store.get_sheet(conn, auth.organization_id, sheet_id))


@router.post("/wage-sheets/{sheet_id}/reopen")
async def reopen(sheet_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                 conn: AsyncConnection = Depends(get_db_conn)):
    sheet = await _sheet(conn, auth, sheet_id)
    if sheet["status"] != "approved":
        raise HTTPException(status_code=409, detail="Not approved")
    if any(Decimal(r["paid"]) > 0 for r in await store.sheet_rows(conn, sheet_id)):
        raise HTTPException(status_code=409, detail="Some of it is paid: a change goes on next week's sheet")
    await store.set_status(conn, sheet_id, "draft", auth.user_id)
    sheet = await store.get_sheet(conn, auth.organization_id, sheet_id)
    await store.refresh(conn, auth.organization_id, sheet)
    return await _detail(conn, auth.organization_id, sheet)


@router.post("/wage-sheets/{sheet_id}/pay")
async def pay_sheet(sheet_id: uuid.UUID, body: PayIn, auth: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    sheet = await _sheet(conn, auth, sheet_id)
    org = auth.organization_id
    if sheet["status"] != "approved":
        raise HTTPException(status_code=409, detail="Approve the sheet before paying it")
    if body.account_id is not None:
        ok = (await conn.execute(text("SELECT 1 FROM money_accounts WHERE id = :id AND organization_id = :org "
                                      "AND status = 'active'"), {"id": body.account_id, "org": org})).first()
        if not ok:
            raise HTTPException(status_code=404, detail="Money account not found")
    rows = await store.sheet_rows(conn, sheet_id)
    chosen = [r for r in rows if (body.row_id is None or r["id"] == body.row_id)
              and Decimal(r["net"]) - Decimal(r["paid"]) > 0]
    if body.row_id is not None and not chosen:
        raise HTTPException(status_code=409, detail="Nothing due on this row")
    if body.amount is not None and body.row_id is None:
        raise HTTPException(status_code=422, detail="A part payment is for one row")
    for r in chosen:
        due = Decimal(r["net"]) - Decimal(r["paid"])
        amount = pay.money(body.amount) if body.amount is not None else due
        if amount > due:
            raise HTTPException(status_code=422, detail=f"Only ₹{due:,.2f} is due to {r['payee_name']}")
        await store.pay_row(conn, org, sheet, r, amount, body.paid_on or datetime.date.today(), body.account_id,
                            body.note, body.source, auth.user_id)
    return await _detail(conn, org, sheet)


# -- muster roll -------------------------------------------------------------------------------------------------------

@router.get("/muster")
async def muster(site_id: uuid.UUID, month: str = Query(pattern=r"^\d{4}-\d{2}$"),
                 auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    """A site's month as the grid sites keep: each worker (or headcount group) down, each day across."""
    org = auth.organization_id
    project_id = await _site_project(conn, org, site_id)
    _reach(auth, project_id, site_id)
    y, m = (int(x) for x in month.split("-"))
    first, last = datetime.date(y, m, 1), datetime.date(y, m, calendar.monthrange(y, m)[1])
    lines = await store.attendance_lines(conn, org, project_id, site_id, first, last)
    team = await store.worker_team(conn, org)
    named = await store.teams(conn, org)
    people: dict[str, dict[str, Any]] = {}
    for ln in lines:
        if ln["worker_id"]:
            key, name = f"worker:{ln['worker_id']}", ln["worker_name"] or "Worker"
        elif (ln["worker_name"] or "").strip():
            key, name = f"name:{ln['worker_name'].strip().lower()}", ln["worker_name"].strip()
        else:
            key, name = f"headcount:{(ln['trade'] or 'labour').lower()}", f"{(ln['trade'] or 'labour').title()} (headcount)"
        team_key = pay.payee_of(ln, team, named)[1]["payee_name"] if pay.team_of(ln, team, named) else None
        p = people.setdefault(key, {"key": key, "name": name, "trade": ln["trade"], "team": team_key,
                                    "worker_id": ln["worker_id"], "days": {}, "man_days": Decimal(0),
                                    "overtime_hours": Decimal(0)})
        factor = pay.DAY_FACTOR.get(ln["attendance_status"] or "present", Decimal(1))
        heads = Decimal(int(ln["headcount"] or 1))
        day = ln["date"].isoformat()
        cell = p["days"].setdefault(day, {"mark": "A", "count": Decimal(0), "ot": Decimal(0)})
        cell["count"] += heads * factor
        cell["ot"] += Decimal(str(ln["overtime_hours"] or 0)) * heads
        # A person: P, ½ or A; a headcount group: how many came.
        cell["mark"] = (f"{cell['count'].normalize():f}" if key.startswith("headcount:")
                        else "A" if cell["count"] == 0 else "½" if cell["count"] < 1 else "P")
        p["man_days"] += heads * factor
        p["overtime_hours"] += Decimal(str(ln["overtime_hours"] or 0)) * heads
    rows = sorted(people.values(), key=lambda r: ((r["team"] or ""), (r["trade"] or ""), r["name"]))
    return {"site_id": site_id, "project_id": project_id, "month": month, "days": (last - first).days + 1,
            "first": first, "rows": rows, "man_days": sum((r["man_days"] for r in rows), Decimal(0))}


# -- teams -------------------------------------------------------------------------------------------------------------

@router.get("/teams")
async def teams(auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    """Labour contractors (vendors of kind labour) with how many workers each has on the register and their days."""
    org = auth.organization_id
    rows = [dict(r) for r in (await conn.execute(text(
        "SELECT v.id, v.name, v.phone, (SELECT COUNT(*) FROM workforce_workers w WHERE w.vendor_id = v.id "
        "AND w.status = 'active') AS workers, (SELECT COALESCE(SUM(COALESCE(l.headcount, 1) * CASE l.attendance_status "
        "WHEN 'absent' THEN 0 WHEN 'half_day' THEN 0.5 ELSE 1 END), 0) "
        "FROM labour_attendance_lines l JOIN labour_attendance_reports r ON r.id = l.report_id "
        "LEFT JOIN workforce_workers ww ON ww.id = l.worker_id "
        "WHERE r.organization_id = v.organization_id AND (l.vendor_id = v.id OR ww.vendor_id = v.id "
        "OR (l.vendor_id IS NULL AND lower(btrim(l.contractor)) = lower(btrim(v.name)))) "
        f"AND r.occurred_date >= CURRENT_DATE - 30 AND {counted_line_sql('l', 'r')}) AS man_days_30 "
        "FROM vendors v WHERE v.organization_id = :org AND v.kind = 'labour' ORDER BY v.name"), {"org": org})).mappings()]
    return {"items": rows}
