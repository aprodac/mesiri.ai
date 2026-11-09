"""Accounts API, Phase A (ACC-01..ACC-05, ACC-22's scope). Behind the ``accounts`` module (D-ACC10, off by default).

  GET   /accounts/chart                         groups and ledgers, each ledger's balance today and where it is used
  POST  /accounts/groups                        add a group under another (it takes its parent's nature)
  PATCH /accounts/groups/{id}                   rename a group
  POST  /accounts/ledgers                       add a ledger to a group
  PATCH /accounts/ledgers/{id}                  rename (not a linked ledger: rename its record), move, notes, active
  GET   /accounts/trial-balance                 ?date_from&date_to&project_id&site_id (and /export: Excel)
  GET   /accounts/day-book                      ?date_from&date_to&voucher_type&ledger_id&project_id&site_id&q (/export)
  GET   /accounts/entries/{id}                  one voucher with its lines and the record it came from
  GET   /accounts/ledgers/{id}/statement        ?date_from&date_to&project_id&site_id (and /export: Excel)
  GET   /accounts/checks                        the books against Finance › Money, the supplier ledger, Receivables
  GET   /accounts/periods                       months: open or closed, entries, changed after close
  POST  /accounts/periods/{month}/close         month as YYYY-MM
  POST  /accounts/periods/{month}/reopen        {reason}: the owner or an admin
  POST  /accounts/post                          post now (every read posts first anyway); what it did

Who (D-ACC6): the books are the owner's, an admin's and finance's (``may_manage_money``): read, add ledgers, close a
month. Reopening a closed month is the owner's or an admin's, with a reason. A project manager's project P&L is ACC-08.
Every read posts first (``sweep.py``), so the books are never behind the records.
"""

from __future__ import annotations

import datetime
import re
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_manage_money
from mesiri.domains.accounts import chart, export, periods, reports, sweep
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(prefix="/accounts", tags=["accounts"], dependencies=[Depends(require_module("accounts"))])

REOPEN_ROLES = frozenset({"OWNER", "ADMIN", "SUPER_ADMIN"})
VOUCHER_TYPES = ("journal", "payment", "receipt", "contra", "sales", "purchase")
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _out(value: Any) -> Any:
    """Dates ISO, ids strings, money exact to the paisa ("1234.50"), never floats."""
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal("0.01")))
    if isinstance(value, datetime.date | datetime.datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _out(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_out(v) for v in value]
    return value


def _require(auth: AuthorizationContext) -> None:
    if not may_manage_money(auth.role):
        raise HTTPException(status_code=403, detail="The books are for the owner, an admin or finance.")


async def _ready(conn: AsyncConnection, auth: AuthorizationContext) -> dict[str, int]:
    """Who may read, then post what changed, so every read is up to date."""
    _require(auth)
    return await sweep.sweep(conn, auth.organization_id)


async def _period(conn: AsyncConnection, auth: AuthorizationContext, date_from: datetime.date | None,
                  date_to: datetime.date | None) -> tuple[datetime.date, datetime.date]:
    from mesiri.application.dpr import project_day

    today = await project_day.company_today(conn, auth.organization_id)
    date_to = date_to or today
    date_from = date_from or periods.fy_start(date_to)
    if date_from > date_to:
        raise HTTPException(status_code=422, detail="The period starts after it ends.")
    if (date_to - date_from).days > 366 * 3:
        raise HTTPException(status_code=422, detail="Pick a period of at most three years.")
    return date_from, date_to


async def _scope_words(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID | None,
                       site_id: uuid.UUID | None) -> str:
    """What the report covers, in words; a project or site of another company is refused."""
    if site_id is not None:
        name = (await conn.execute(text("SELECT name FROM sites WHERE id = :s AND organization_id = :org"),
                                   {"s": site_id, "org": org})).scalar()
        if name is None:
            raise HTTPException(status_code=404, detail="Site not found.")
        return f"site {name}"
    if project_id is not None:
        name = (await conn.execute(text("SELECT name FROM projects WHERE id = :p AND organization_id = :org"),
                                   {"p": project_id, "org": org})).scalar()
        if name is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        return f"project {name}"
    return "whole company"


async def _company(conn: AsyncConnection, org: uuid.UUID) -> str:
    return (await conn.execute(text("SELECT name FROM organizations WHERE id = :o"), {"o": org})).scalar() or "Company"


def _xlsx(content: bytes, name: str) -> Response:
    return Response(content=content, media_type=_XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


# --- chart of accounts ---------------------------------------------------------------------------------------------

@router.get("/chart")
async def get_chart(auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    org = auth.organization_id
    from mesiri.application.dpr import project_day

    today = await project_day.company_today(conn, org)
    bal = await reports.balances(conn, org, today)
    used = {r[0]: (r[1], r[2]) for r in (await conn.execute(text(
        "SELECT ledger_id, COUNT(*), MAX(entry_date) FROM journal_lines WHERE organization_id = :org GROUP BY ledger_id"),
        {"org": org}))}
    groups = await chart.groups(conn, org)
    ledgers = [{**r, "balance": bal.get(r["id"], Decimal(0)), "lines": used.get(r["id"], (0, None))[0],
                "last_used": used.get(r["id"], (0, None))[1], "seeded": r["code"] is not None,
                "purpose": r["notes"]} for r in await chart.ledgers(conn, org)]
    return _out({"as_of": today, "groups": groups, "ledgers": ledgers})


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: uuid.UUID


class GroupPatch(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class LedgerIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    group_id: uuid.UUID
    notes: str | None = Field(default=None, max_length=500)


class LedgerPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    group_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


async def _group(conn: AsyncConnection, org: uuid.UUID, group_id: uuid.UUID) -> dict[str, Any]:
    g = (await conn.execute(text("SELECT id, name, nature, code FROM ledger_groups WHERE id = :g AND organization_id = :org"),
                            {"g": group_id, "org": org})).mappings().first()
    if g is None:
        raise HTTPException(status_code=404, detail="Group not found.")
    return dict(g)


async def _name_free(conn: AsyncConnection, org: uuid.UUID, table: str, name: str, besides: uuid.UUID | None = None) -> None:
    taken = (await conn.execute(text(
        f"SELECT 1 FROM {table} WHERE organization_id = :org AND lower(btrim(name)) = lower(btrim(:n)) "  # noqa: S608
        "AND (CAST(:b AS uuid) IS NULL OR id <> CAST(:b AS uuid))"), {"org": org, "n": name, "b": besides})).first()
    if taken:
        raise HTTPException(status_code=409, detail=f"There is already one called {name.strip()}.")


@router.post("/groups", status_code=201)
async def add_group(body: GroupIn, auth: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    org = auth.organization_id
    parent = await _group(conn, org, body.parent_id)
    await _name_free(conn, org, "ledger_groups", body.name)
    gid = (await conn.execute(text(
        "INSERT INTO ledger_groups (organization_id, parent_id, name, nature, sort) VALUES (:org, :p, :n, :nat, 1000) "
        "RETURNING id"), {"org": org, "p": parent["id"], "n": body.name.strip(), "nat": parent["nature"]})).scalar_one()
    return _out({"id": gid, "name": body.name.strip(), "nature": parent["nature"], "parent_id": parent["id"]})


@router.patch("/groups/{group_id}")
async def rename_group(group_id: uuid.UUID, body: GroupPatch, auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    org = auth.organization_id
    await _group(conn, org, group_id)
    await _name_free(conn, org, "ledger_groups", body.name, group_id)
    await conn.execute(text("UPDATE ledger_groups SET name = :n WHERE id = :g"), {"n": body.name.strip(), "g": group_id})
    return _out(await _group(conn, org, group_id))


@router.post("/ledgers", status_code=201)
async def add_ledger(body: LedgerIn, auth: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    org = auth.organization_id
    await _group(conn, org, body.group_id)
    lid = (await conn.execute(text(
        "INSERT INTO ledgers (organization_id, group_id, name, notes, created_by) VALUES (:org, :g, :n, :notes, :u) "
        "RETURNING id"), {"org": org, "g": body.group_id, "n": body.name.strip(), "notes": body.notes,
                          "u": auth.user_id})).scalar_one()
    return _out({"id": lid, "name": body.name.strip(), "group_id": body.group_id})


@router.patch("/ledgers/{ledger_id}")
async def edit_ledger(ledger_id: uuid.UUID, body: LedgerPatch, auth: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    org = auth.organization_id
    led = (await conn.execute(text("SELECT id, link_kind, code FROM ledgers WHERE id = :l AND organization_id = :org"),
                              {"l": ledger_id, "org": org})).mappings().first()
    if led is None:
        raise HTTPException(status_code=404, detail="Ledger not found.")
    if body.name is not None and led["link_kind"]:
        where = {"vendor": "Vendors", "client": "Clients", "money_account": "Finance › Money",
                 "expense_category": "Finance › Settings (categories)", "staff": "the team list"}[led["link_kind"]]
        raise HTTPException(status_code=409, detail=f"This ledger is named after its record: rename it in {where}.")
    if body.is_active is False and led["code"]:
        raise HTTPException(status_code=409, detail="Mesiri posts to this ledger; it cannot be switched off.")
    changes: dict[str, Any] = {}
    if body.name is not None:
        changes["name"] = body.name.strip()
    if body.group_id is not None:
        await _group(conn, org, body.group_id)
        changes["group_id"] = body.group_id
    if body.notes is not None:
        changes["notes"] = body.notes.strip() or None
    if body.is_active is not None:
        changes["is_active"] = body.is_active
    if changes:
        sets = ", ".join(f"{k} = :{k}" for k in changes)
        await conn.execute(text(f"UPDATE ledgers SET {sets}, updated_at = now() WHERE id = :l"),  # noqa: S608
                           {**changes, "l": ledger_id})
    return _out(next(r for r in await chart.ledgers(conn, org) if r["id"] == ledger_id))


# --- reports -------------------------------------------------------------------------------------------------------

@router.get("/trial-balance")
async def trial_balance(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                        project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None,
                        auth: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn)):
    posted = await _ready(conn, auth)
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    scope = await _scope_words(conn, auth.organization_id, project_id, site_id)
    tb = await reports.trial_balance(conn, auth.organization_id, date_from, date_to, project_id, site_id)
    return _out({"date_from": date_from, "date_to": date_to, "scope": scope, "financial_year": periods.fy_label(date_to),
                 "posted": posted, **tb})


@router.get("/trial-balance/export")
async def trial_balance_export(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                               project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None,
                               auth: AuthorizationContext = Depends(get_auth_context),
                               conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    scope = await _scope_words(conn, auth.organization_id, project_id, site_id)
    tb = await reports.trial_balance(conn, auth.organization_id, date_from, date_to, project_id, site_id)
    content = export.trial_balance(await _company(conn, auth.organization_id), scope, date_from, date_to, tb)
    return _xlsx(content, f"trial-balance-{date_from}-to-{date_to}.xlsx")


async def _day_book(conn, auth, date_from, date_to, voucher_type, ledger_id, project_id, site_id, q, after_close,
                    limit, offset):
    if voucher_type and voucher_type not in VOUCHER_TYPES:
        raise HTTPException(status_code=422, detail=f"voucher_type is one of {', '.join(VOUCHER_TYPES)}.")
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    scope = await _scope_words(conn, auth.organization_id, project_id, site_id)
    book = await reports.entries(conn, auth.organization_id, date_from=date_from, date_to=date_to,
                                 voucher_type=voucher_type, ledger_id=ledger_id, project_id=project_id, site_id=site_id,
                                 q=q, after_close=after_close, limit=limit, offset=offset)
    return date_from, date_to, scope, book


@router.get("/day-book")
async def day_book(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                   voucher_type: str | None = None, ledger_id: uuid.UUID | None = None,
                   project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None, q: str | None = None,
                   after_close: bool = False, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                   auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    date_from, date_to, scope, book = await _day_book(conn, auth, date_from, date_to, voucher_type, ledger_id,
                                                      project_id, site_id, q, after_close, limit, offset)
    return _out({"date_from": date_from, "date_to": date_to, "scope": scope, **book})


@router.get("/day-book/export")
async def day_book_export(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                          voucher_type: str | None = None, ledger_id: uuid.UUID | None = None,
                          project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None, q: str | None = None,
                          auth: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    date_from, date_to, scope, book = await _day_book(conn, auth, date_from, date_to, voucher_type, ledger_id,
                                                      project_id, site_id, q, False, 20000, 0)
    content = export.day_book(await _company(conn, auth.organization_id), scope, date_from, date_to, book)
    return _xlsx(content, f"day-book-{date_from}-to-{date_to}.xlsx")


@router.get("/entries/{entry_id}")
async def get_entry(entry_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    book = await reports.entries(conn, auth.organization_id, date_from=datetime.date.min, date_to=datetime.date.max,
                                 entry_id=entry_id, limit=1)
    if not book["entries"]:
        raise HTTPException(status_code=404, detail="Voucher not found.")
    return _out(book["entries"][0])


@router.get("/ledgers/{ledger_id}/statement")
async def statement(ledger_id: uuid.UUID, date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                    project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None,
                    auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    scope = await _scope_words(conn, auth.organization_id, project_id, site_id)
    st = await reports.ledger_statement(conn, auth.organization_id, ledger_id, date_from, date_to, project_id, site_id)
    if st is None:
        raise HTTPException(status_code=404, detail="Ledger not found.")
    return _out({"date_from": date_from, "date_to": date_to, "scope": scope, **st})


@router.get("/ledgers/{ledger_id}/statement/export")
async def statement_export(ledger_id: uuid.UUID, date_from: datetime.date | None = None,
                           date_to: datetime.date | None = None, project_id: uuid.UUID | None = None,
                           site_id: uuid.UUID | None = None, auth: AuthorizationContext = Depends(get_auth_context),
                           conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    scope = await _scope_words(conn, auth.organization_id, project_id, site_id)
    st = await reports.ledger_statement(conn, auth.organization_id, ledger_id, date_from, date_to, project_id, site_id)
    if st is None:
        raise HTTPException(status_code=404, detail="Ledger not found.")
    content = export.ledger_statement(await _company(conn, auth.organization_id), scope, date_from, date_to, st)
    slug = re.sub(r"[^a-z0-9]+", "-", st["ledger"]["name"].lower()).strip("-") or "ledger"
    return _xlsx(content, f"{slug}-{date_from}-to-{date_to}.xlsx")


@router.get("/checks")
async def get_checks(auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    from mesiri.application.dpr import project_day

    await _ready(conn, auth)
    return _out(await reports.checks(conn, auth.organization_id, await project_day.company_today(conn, auth.organization_id)))


# --- months --------------------------------------------------------------------------------------------------------

class ReopenIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


def _month(value: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Month as YYYY-MM.") from exc


@router.get("/periods")
async def list_periods(auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    from mesiri.application.dpr import project_day

    await _ready(conn, auth)
    today = await project_day.company_today(conn, auth.organization_id)
    await periods.ensure_months(conn, auth.organization_id, {today})
    months = await periods.list_months(conn, auth.organization_id)
    return _out({"today": today, "financial_year": periods.fy_label(today),
                 "months": [{**m, "month": m["starts_on"].strftime("%Y-%m"), "financial_year": periods.fy_label(m["starts_on"]),
                             "is_current": m["starts_on"] <= today <= m["ends_on"]} for m in months]})


@router.post("/periods/{month}/close")
async def close_period(month: str, auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    from mesiri.application.dpr import project_day

    start = _month(month)
    await _ready(conn, auth)  # everything recorded so far is posted before the month closes
    today = await project_day.company_today(conn, auth.organization_id)
    if start > today.replace(day=1):
        raise HTTPException(status_code=409, detail="A month that has not started cannot be closed.")
    await periods.set_status(conn, auth.organization_id, start, "closed", auth.user_id)
    return await list_periods(auth, conn)


@router.post("/periods/{month}/reopen")
async def reopen_period(month: str, body: ReopenIn, auth: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn)):
    start = _month(month)
    _require(auth)
    if str(auth.role or "").upper() not in REOPEN_ROLES:
        raise HTTPException(status_code=403, detail="Only the owner or an admin can reopen a closed month.")
    await periods.set_status(conn, auth.organization_id, start, "open", auth.user_id, body.reason.strip())
    return await list_periods(auth, conn)


@router.post("/post")
async def post_now(auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    stats = await _ready(conn, auth)
    total = (await conn.execute(text("SELECT COUNT(*) FROM journal_entries WHERE organization_id = :org"),
                                {"org": auth.organization_id})).scalar()
    return _out({**stats, "entries": total})


# --- Phase B: statements (ACC-06..09, ACC-22, ACC-23) --------------------------------------------------------------

PROJECT_ROLES = frozenset({"PROJECT_MANAGER"})


async def _ready_projects(conn: AsyncConnection, auth: AuthorizationContext,
                          project_id: uuid.UUID | None = None) -> set[uuid.UUID] | None:
    """Project P&L and position (D-ACC6): the money roles see every project; a project manager only theirs. Returns
    the projects the caller may see (None: all), after posting what changed."""
    role = str(auth.role or "").upper()
    if may_manage_money(role):
        allowed = None
    elif role in PROJECT_ROLES:
        allowed = None if auth.project_scope.grants_all_org_projects else set(auth.project_scope.project_ids)
    else:
        raise HTTPException(status_code=403, detail="Project P&L is for the owner, an admin, finance or the project's manager.")
    if project_id is not None and allowed is not None and project_id not in allowed:
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    await sweep.sweep(conn, auth.organization_id)
    return allowed


@router.get("/pl")
async def profit_and_loss(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                          project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None,
                          compare: str | None = Query(None, pattern="^(previous|last_year)$"),
                          auth: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn)):
    """ACC-06: income and costs, gross and net profit, for the company, a project (its manager too) or a site."""
    from mesiri.domains.accounts import statements

    if project_id is not None and not may_manage_money(auth.role):
        await _ready_projects(conn, auth, project_id)
    else:
        await _ready(conn, auth)
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    scope = await _scope_words(conn, auth.organization_id, project_id, site_id)
    pl = await statements.profit_and_loss(conn, auth.organization_id, date_from, date_to, project_id, site_id, compare)
    return _out({"date_from": date_from, "date_to": date_to, "scope": scope, **pl})


@router.get("/balance-sheet")
async def balance_sheet(as_of: datetime.date | None = None, auth: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn)):
    """ACC-06: the company's balance sheet on a day (a project has its position instead)."""
    from mesiri.application.dpr import project_day
    from mesiri.domains.accounts import statements

    await _ready(conn, auth)
    as_of = as_of or await project_day.company_today(conn, auth.organization_id)
    return _out(await statements.balance_sheet(conn, auth.organization_id, as_of))


@router.get("/cash-bank")
async def cash_and_bank(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                        project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None,
                        auth: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn)):
    """ACC-07: every cash box and bank account, opening, in, out, closing, and each day's money in and out."""
    from mesiri.domains.accounts import statements

    await _ready(conn, auth)
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    scope = await _scope_words(conn, auth.organization_id, project_id, site_id)
    book = await statements.cash_bank(conn, auth.organization_id, date_from, date_to, project_id, site_id)
    return _out({"date_from": date_from, "date_to": date_to, "scope": scope, **book})


@router.get("/projects")
async def projects(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                   auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    """ACC-08: every project's P&L in the period (billed, cost, head-office share, profit, margin) and what it is
    owed and owes today, best first. A project manager sees their projects."""
    from mesiri.domains.accounts import statements

    allowed = await _ready_projects(conn, auth)
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    rows = await statements.projects_table(conn, auth.organization_id, date_from, date_to, allowed)
    total = {k: sum((Decimal(r[k]) for r in rows), Decimal(0)) for k in ("billed", "cost", "overheads", "profit",
                                                                         "receivable", "payable")}
    total["margin"] = statements.pct(total["profit"], total["billed"])
    return _out({"date_from": date_from, "date_to": date_to, "projects": rows, "total": total,
                 **await sweep.overhead_settings(conn, auth.organization_id)})


async def _budget(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID) -> dict[str, Any] | None:
    """Cost control's BOQ budget, spending and forecast for the project, when it has them (CC-18): beside the books."""
    try:
        from mesiri.domains.costing.router import _scope as cost_scope
        from mesiri.domains.costing.router import budget_for

        async with conn.begin_nested():
            b = await budget_for(conn, auth.organization_id, project_id, cost_scope(auth, project_id, None))
    except Exception:  # noqa: BLE001 -- no BOQ, or the cost module cannot read it: the books stand alone
        return None
    kinds = b.get("kinds") or []

    def total(key: str) -> Decimal | None:
        vals = [Decimal(str(k[key])) for k in kinds if k.get(key) not in (None, "")]
        return sum(vals, Decimal(0)) if vals else None
    return {"budget": total("budget"), "forecast": total("forecast"), "spent": Decimal(str(b.get("total_spent") or 0)),
            "kinds": [{"label": k["label"], "budget": k.get("budget"), "actual": k.get("actual"),
                       "forecast": k.get("forecast")} for k in kinds]}


@router.get("/projects/{project_id}")
async def project_books(project_id: uuid.UUID, date_from: datetime.date | None = None,
                        date_to: datetime.date | None = None, auth: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn)):
    """ACC-08: one project: its P&L by cost centre and group, its position today, its months, and Cost control's
    BOQ budget and forecast beside them."""
    from mesiri.domains.accounts import statements

    await _ready_projects(conn, auth, project_id)
    org = auth.organization_id
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    scope = await _scope_words(conn, org, project_id, None)
    pl = await statements.profit_and_loss(conn, org, date_from, date_to, project_id)
    centres = [{"cost_centre": r[0], "amount": Decimal(r[1])} for r in (await conn.execute(text(
        "SELECT COALESCE(jl.cost_centre, 'not_set'), SUM(jl.debit - jl.credit) FROM journal_lines jl "
        "JOIN ledgers l ON l.id = jl.ledger_id JOIN ledger_groups g ON g.id = l.group_id "
        "WHERE jl.organization_id = :org AND jl.project_id = :p AND g.nature = 'expense' "
        "AND COALESCE(l.code, '') <> :oh AND jl.entry_date BETWEEN :f AND :t GROUP BY 1 ORDER BY 2 DESC"),
        {"org": org, "p": project_id, "f": date_from, "t": date_to, "oh": statements.OVERHEADS}))]
    return _out({"date_from": date_from, "date_to": date_to, "scope": scope, "project_id": project_id,
                 "pl": pl, "centres": centres,
                 "position": await statements.position(conn, org, project_id, date_to),
                 "months": await statements.monthly(conn, org, periods.fy_start(date_to), date_to, project_id),
                 "budget": await _budget(conn, auth, project_id)})


@router.get("/home")
async def home(project_id: uuid.UUID | None = None, auth: AuthorizationContext = Depends(get_auth_context),
               conn: AsyncConnection = Depends(get_db_conn)):
    """ACC-09: the owner's one screen: cash and bank today, owed to us and by us, this month against last, the year
    by month, GST this month, TDS to deposit, the projects, what needs the accountant. ``project_id``: that
    project's own home (its position instead of the company's cash)."""
    from mesiri.application.dpr import project_day
    from mesiri.domains.accounts import statements

    if project_id is not None and not may_manage_money(auth.role):
        allowed = await _ready_projects(conn, auth, project_id)
    else:
        await _ready(conn, auth)
        allowed = None
    org = auth.organization_id
    today = await project_day.company_today(conn, org)
    month = today.replace(day=1)
    last_end = month - datetime.timedelta(days=1)
    last = last_end.replace(day=1)
    fy = periods.fy_start(today)
    this_pl = await statements.profit_and_loss(conn, org, month, today, project_id)
    last_pl = await statements.profit_and_loss(conn, org, last, last_end, project_id)
    year_pl = await statements.profit_and_loss(conn, org, fy, today, project_id)
    out: dict[str, Any] = {
        "today": today, "financial_year": periods.fy_label(today),
        "scope": await _scope_words(conn, org, project_id, None),
        "this_month": {"date_from": month, "date_to": today, **this_pl["totals"]},
        "last_month": {"date_from": last, "date_to": last_end, **last_pl["totals"]},
        "year": {"date_from": fy, "date_to": today, **year_pl["totals"]},
        "months": await statements.monthly(conn, org, fy, today, project_id),
        "projects": (await statements.projects_table(conn, org, fy, today, allowed))[:8] if project_id is None else [],
    }
    if project_id is None:
        cb = await statements.cash_bank(conn, org, today, today)
        ledgers = await chart.ledgers(conn, org)
        bal = await reports.balances(conn, org, today)
        from mesiri.domains.subcontracts.store import TDS_ACCOUNT

        tds = next((r for r in ledgers if r["link_kind"] == "money_account" and r["name"] == TDS_ACCOUNT), None)
        by_id = {r["id"]: r for r in ledgers}
        out.update({
            "cash_bank": {"accounts": cb["accounts"], "total": cb["total"]["closing"]},
            "receivable": sum((v for k, v in bal.items() if k in by_id and (by_id[k]["link_kind"] == "client"
                                                                              or by_id[k]["code"] == "no_client")), Decimal(0)),
            "payable": -sum((v for k, v in bal.items() if k in by_id and by_id[k]["link_kind"] in ("vendor", "staff")),
                            Decimal(0)),
            "gst_this_month": await statements.gst_for(conn, org, month, today),
            "tds_to_deposit": -bal.get(tds["id"], Decimal(0)) if tds else Decimal(0),
            "attention": await statements.attention(conn, org, today),
        })
    else:
        out["position"] = await statements.position(conn, org, project_id, today)
    return _out(out)


class SettingsIn(BaseModel):
    overhead_basis: str | None = Field(default=None, pattern="^(cost|billing)$")
    head_office_project_id: uuid.UUID | None = None


@router.get("/settings")
async def get_settings(auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    _require(auth)
    return await sweep.overhead_settings(conn, auth.organization_id)


@router.put("/settings")
async def put_settings(body: SettingsIn, auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    """ACC-23 (D-ACC11): share head-office costs over projects each finished month, by cost or billing; null: off.
    The owner or an admin (it changes every project's profit)."""
    _require(auth)
    if str(auth.role or "").upper() not in REOPEN_ROLES:
        raise HTTPException(status_code=403, detail="Only the owner or an admin can change how overheads are shared.")
    if body.head_office_project_id is not None:
        await _scope_words(conn, auth.organization_id, body.head_office_project_id, None)  # the company's own
    await conn.execute(text(
        "INSERT INTO accounting_settings (organization_id, overhead_basis, head_office_project_id, updated_by) "
        "VALUES (:org, :b, :p, :u) ON CONFLICT (organization_id) DO UPDATE SET overhead_basis = EXCLUDED.overhead_basis, "
        "head_office_project_id = EXCLUDED.head_office_project_id, updated_by = EXCLUDED.updated_by, updated_at = now()"),
        {"org": auth.organization_id, "b": body.overhead_basis, "p": body.head_office_project_id, "u": auth.user_id})
    stats = await sweep.sweep(conn, auth.organization_id)
    return {**await sweep.overhead_settings(conn, auth.organization_id), "posted": stats}


# --- Phase C: GST and TDS (ACC-10, ACC-11) -------------------------------------------------------------------------

async def _tax_period(conn, auth, date_from, date_to):
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    return date_from, date_to


@router.get("/gst")
async def gst_summary(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                      auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    """ACC-10: output and claimable input GST (IGST / CGST / SGST by place of supply), net payable per month, sales and
    purchases with GSTINs, credit missed and why, tied to the Output / Input GST ledgers. Company-wide (one return)."""
    from mesiri.domains.accounts import tax

    await _ready(conn, auth)
    date_from, date_to = await _tax_period(conn, auth, date_from, date_to)
    return _out({"date_from": date_from, "date_to": date_to,
                 **await tax.gst(conn, auth.organization_id, date_from, date_to)})


@router.get("/gst/export")
async def gst_export(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                     auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    from mesiri.domains.accounts import tax

    await _ready(conn, auth)
    date_from, date_to = await _tax_period(conn, auth, date_from, date_to)
    g = await tax.gst(conn, auth.organization_id, date_from, date_to)
    return _xlsx(export.gst(await _company(conn, auth.organization_id), date_from, date_to, g),
                 f"gst-{date_from}-to-{date_to}.xlsx")


@router.get("/tds")
async def tds_register(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                       auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    """ACC-11: TDS deducted from subcontractors (194C) with what is deposited and due by when; TDS clients deducted
    from our RA bills (for 26AS)."""
    from mesiri.application.dpr import project_day
    from mesiri.domains.accounts import tax

    await _ready(conn, auth)
    date_from, date_to = await _tax_period(conn, auth, date_from, date_to)
    today = await project_day.company_today(conn, auth.organization_id)
    return _out({"date_from": date_from, "date_to": date_to, "today": today,
                 **await tax.tds(conn, auth.organization_id, date_from, date_to, today)})


@router.get("/tds/export")
async def tds_export(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                     auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    from mesiri.application.dpr import project_day
    from mesiri.domains.accounts import tax

    await _ready(conn, auth)
    date_from, date_to = await _tax_period(conn, auth, date_from, date_to)
    today = await project_day.company_today(conn, auth.organization_id)
    t = await tax.tds(conn, auth.organization_id, date_from, date_to, today)
    return _xlsx(export.tds(await _company(conn, auth.organization_id), date_from, date_to, t),
                 f"tds-{date_from}-to-{date_to}.xlsx")
