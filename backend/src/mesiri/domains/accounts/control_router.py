"""Accounts API, Phases D to F (ACC-12, 13, 16, 17, 18, 21). Included in ``router.py``'s router, so it sits behind
the same ``accounts`` module gate and ``/accounts`` prefix.

  GET    /accounts/vouchers                     manual vouchers of a period (?date_from&date_to)
  POST   /accounts/vouchers                     {date, narration, lines[{ledger_id, debit|credit, project_id, site_id,
                                                cost_centre}]}: a manual journal (ACC-12)
  GET    /accounts/vouchers/{id}                one, with its lines and the journal it posted as
  PUT    /accounts/vouchers/{id}                change it (its month must be open)
  POST   /accounts/vouchers/{id}/cancel         {reason}
  GET    /accounts/bank                         each money account with its statement lines open (ACC-13)
  GET    /accounts/bank/{account_id}            lines, suggestions, what the bank has not shown, the reconciliation
  POST   /accounts/bank/{account_id}/statements multipart file (Excel / CSV); ?preview=true reads without saving
  POST   /accounts/bank/lines/{id}/match|book|ignore|undo
  GET    /accounts/bank/{account_id}/export     ?format=xlsx|pdf
  GET    /accounts/assets                       the register (ACC-16); /export; /candidates (bills that look like one)
  POST   /accounts/assets, PUT /accounts/assets/{id}, POST /accounts/assets/{id}/dispose, DELETE /accounts/assets/{id}
  PUT    /accounts/assets/method                {method: wdv|slm}: the company's default (owner, admin)
  GET    /accounts/years                        each financial year: open or closed, profit (ACC-17)
  GET    /accounts/years/{fy}                   its checklist and what it carries forward; /export
  POST   /accounts/years/{fy}/close             {acknowledge}: the owner or an admin
  POST   /accounts/years/{fy}/reopen            {reason}: the owner or an admin
  GET    /accounts/cash-flow                    ?date_from&date_to&project_id&site_id (ACC-18); /export
  GET    /accounts/pl|balance-sheet|cash-bank/export   ?format=xlsx|pdf (ACC-21; /accounts/projects/export is in
                                                router.py, ahead of /accounts/projects/{id})

Who (D-ACC6): the money roles (owner, admin, finance) for everything; closing and reopening a year, and the
depreciation method, are the owner's or an admin's. A project manager may export their project's P&L.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_manage_money
from mesiri.domains.accounts import assets, bank, export, statements, sweep, vouchers, years
from mesiri.domains.accounts.router import (
    FORMAT,
    REOPEN_ROLES,
    _company,
    _file,
    _out,
    _period,
    _ready,
    _ready_projects,
    _require,
    _scope_words,
)
from mesiri.domains.projects.router import get_auth_context
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter()
_MAX_STATEMENT = 5 * 1024 * 1024


async def _today(conn: AsyncConnection, org: uuid.UUID) -> datetime.date:
    from mesiri.application.dpr import project_day

    return await project_day.company_today(conn, org)


def _owner_or_admin(auth: AuthorizationContext, what: str) -> None:
    _require(auth)
    if str(auth.role or "").upper() not in REOPEN_ROLES:
        raise HTTPException(status_code=403, detail=f"Only the owner or an admin can {what}.")


# --- ACC-12: manual vouchers ---------------------------------------------------------------------------------------

class VoucherLineIn(BaseModel):
    ledger_id: uuid.UUID
    debit: Decimal = Field(default=Decimal(0), ge=0, max_digits=16, decimal_places=2)
    credit: Decimal = Field(default=Decimal(0), ge=0, max_digits=16, decimal_places=2)
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    cost_centre: str | None = Field(default=None, max_length=40)


class VoucherIn(BaseModel):
    date: datetime.date
    narration: str = Field(min_length=3, max_length=500)
    lines: list[VoucherLineIn] = Field(min_length=2, max_length=60)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


def _voucher_error(exc: vouchers.VoucherError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


async def _one_voucher(conn: AsyncConnection, org: uuid.UUID, voucher_id: uuid.UUID) -> dict[str, Any]:
    found = await vouchers.listing(conn, org, datetime.date.min, datetime.date.max, voucher_id)
    if not found:
        raise HTTPException(status_code=404, detail="Voucher not found.")
    return found[0]


@router.get("/vouchers")
async def list_vouchers(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                        auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    rows = await vouchers.listing(conn, auth.organization_id, date_from, date_to)
    return _out({"date_from": date_from, "date_to": date_to, "vouchers": rows,
                 "total": sum((r["amount"] for r in rows if r["status"] == "posted"), Decimal(0))})


@router.post("/vouchers", status_code=201)
async def add_voucher(body: VoucherIn, auth: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    _require(auth)
    try:
        vid = await vouchers.create(conn, auth.organization_id, auth.user_id, body.date, body.narration,
                                    [ln.model_dump() for ln in body.lines])
    except vouchers.VoucherError as exc:
        raise _voucher_error(exc) from exc
    await sweep.sweep(conn, auth.organization_id)
    return _out(await _one_voucher(conn, auth.organization_id, vid))


@router.get("/vouchers/{voucher_id}")
async def get_voucher(voucher_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    return _out(await _one_voucher(conn, auth.organization_id, voucher_id))


@router.put("/vouchers/{voucher_id}")
async def edit_voucher(voucher_id: uuid.UUID, body: VoucherIn, auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    _require(auth)
    try:
        await vouchers.update(conn, auth.organization_id, auth.user_id, voucher_id, body.date, body.narration,
                              [ln.model_dump() for ln in body.lines])
    except vouchers.VoucherError as exc:
        raise _voucher_error(exc) from exc
    await sweep.sweep(conn, auth.organization_id)
    return _out(await _one_voucher(conn, auth.organization_id, voucher_id))


@router.post("/vouchers/{voucher_id}/cancel")
async def cancel_voucher(voucher_id: uuid.UUID, body: ReasonIn, auth: AuthorizationContext = Depends(get_auth_context),
                         conn: AsyncConnection = Depends(get_db_conn)):
    _require(auth)
    try:
        await vouchers.cancel(conn, auth.organization_id, auth.user_id, voucher_id, body.reason)
    except vouchers.VoucherError as exc:
        raise _voucher_error(exc) from exc
    await sweep.sweep(conn, auth.organization_id)
    return _out(await _one_voucher(conn, auth.organization_id, voucher_id))


# --- ACC-13: bank reconciliation -----------------------------------------------------------------------------------

def _bank_error(exc: bank.StatementError) -> HTTPException:
    words = str(exc)
    return HTTPException(status_code=404 if words.endswith("not found.") else 422, detail=words)


class MatchIn(BaseModel):
    money_transaction_id: uuid.UUID


class BookIn(BaseModel):
    ledger_id: uuid.UUID
    project_id: uuid.UUID | None = None


@router.get("/bank")
async def bank_accounts(auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    return _out({"accounts": await bank.accounts_summary(conn, auth.organization_id)})


@router.get("/bank/{account_id}")
async def bank_account(account_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    try:
        return _out(await bank.overview(conn, auth.organization_id, account_id, await _today(conn, auth.organization_id)))
    except bank.StatementError as exc:
        raise _bank_error(exc) from exc


@router.get("/bank/{account_id}/export")
async def bank_export(account_id: uuid.UUID, fmt: str = FORMAT, auth: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    try:
        o = await bank.overview(conn, auth.organization_id, account_id, await _today(conn, auth.organization_id))
    except bank.StatementError as exc:
        raise _bank_error(exc) from exc
    return _file(export.bank_reco(await _company(conn, auth.organization_id), o), fmt,
                 f"bank-reconciliation-{o['account']['name']}".replace(" ", "-").lower())


@router.post("/bank/{account_id}/statements", status_code=201)
async def upload_statement(account_id: uuid.UUID, file: UploadFile = File(...), preview: bool = False,
                           auth: AuthorizationContext = Depends(get_auth_context),
                           conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    content = await file.read(_MAX_STATEMENT + 1)
    if len(content) > _MAX_STATEMENT:
        raise HTTPException(status_code=413, detail="A statement of at most 5 MB: download a shorter period.")
    try:
        out = await bank.import_statement(conn, auth.organization_id, auth.user_id, account_id, content,
                                          file.filename or "", preview=preview)
    except bank.StatementError as exc:
        raise _bank_error(exc) from exc
    if not preview:
        await sweep.sweep(conn, auth.organization_id)
    return _out(out)


async def _line_action(conn: AsyncConnection, auth: AuthorizationContext, line_id: uuid.UUID, action) -> dict:
    _require(auth)
    try:
        await action()
    except bank.StatementError as exc:
        raise _bank_error(exc) from exc
    await sweep.sweep(conn, auth.organization_id)
    account_id = (await conn.execute(text(
        "SELECT money_account_id FROM bank_statement_lines WHERE id = :id"), {"id": line_id})).scalar()
    return _out(await bank.overview(conn, auth.organization_id, account_id, await _today(conn, auth.organization_id)))


@router.post("/bank/lines/{line_id}/match")
async def match_line(line_id: uuid.UUID, body: MatchIn, auth: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    return await _line_action(conn, auth, line_id, lambda: bank.match(
        conn, auth.organization_id, auth.user_id, line_id, body.money_transaction_id))


@router.post("/bank/lines/{line_id}/book")
async def book_line(line_id: uuid.UUID, body: BookIn, auth: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    if body.project_id is not None:
        await _scope_words(conn, auth.organization_id, body.project_id, None)
    return await _line_action(conn, auth, line_id, lambda: bank.book(
        conn, auth.organization_id, auth.user_id, line_id, body.ledger_id, body.project_id))


@router.post("/bank/lines/{line_id}/ignore")
async def ignore_line(line_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    return await _line_action(conn, auth, line_id, lambda: bank.ignore(conn, auth.organization_id, auth.user_id, line_id))


@router.post("/bank/lines/{line_id}/undo")
async def undo_line(line_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    return await _line_action(conn, auth, line_id, lambda: bank.undo(conn, auth.organization_id, auth.user_id, line_id))


# --- ACC-16: fixed assets ------------------------------------------------------------------------------------------

class AssetIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    asset_class: str
    cost: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    acquired_on: datetime.date
    put_to_use_on: datetime.date | None = None
    method: str | None = Field(default=None, pattern="^(wdv|slm)$")
    rate: Decimal | None = Field(default=None, gt=0, le=100)
    useful_life_years: Decimal | None = Field(default=None, gt=0, le=100)
    salvage_value: Decimal = Field(default=Decimal(0), ge=0)
    opening_depreciation: Decimal = Field(default=Decimal(0), ge=0)
    books_from: datetime.date | None = None
    expense_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=500)


class DisposeIn(BaseModel):
    disposed_on: datetime.date | None = None
    disposal_value: Decimal | None = Field(default=None, ge=0)


class MethodIn(BaseModel):
    method: str = Field(pattern="^(wdv|slm)$")


def _asset_error(exc: assets.AssetError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


async def _register(conn: AsyncConnection, auth: AuthorizationContext) -> dict[str, Any]:
    return await assets.register(conn, auth.organization_id, await _today(conn, auth.organization_id))


@router.get("/assets")
async def asset_register(auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    return _out(await _register(conn, auth))


@router.get("/assets/export")
async def asset_export(fmt: str = FORMAT, auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    r = await _register(conn, auth)
    return _file(export.assets_register(await _company(conn, auth.organization_id), r), fmt, f"fixed-assets-{r['today']}")


@router.get("/assets/candidates")
async def asset_candidates(auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    _require(auth)
    return _out({"bills": await assets.candidates(conn, auth.organization_id)})


@router.put("/assets/method")
async def asset_method(body: MethodIn, auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    """D-ACC9: WDV (Income-tax) or SLM (Companies Act) for new assets; each asset keeps the method it was entered with."""
    _owner_or_admin(auth, "change how assets are depreciated")
    await conn.execute(text(
        "INSERT INTO accounting_settings (organization_id, depreciation_method, updated_by) VALUES (:org, :m, :u) "
        "ON CONFLICT (organization_id) DO UPDATE SET depreciation_method = EXCLUDED.depreciation_method, "
        "updated_by = EXCLUDED.updated_by, updated_at = now()"), {"org": auth.organization_id, "m": body.method, "u": auth.user_id})
    return {"method": body.method}


@router.post("/assets", status_code=201)
async def add_asset(body: AssetIn, auth: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn)):
    _require(auth)
    try:
        aid = await assets.create(conn, auth.organization_id, auth.user_id, body.model_dump())
    except assets.AssetError as exc:
        raise _asset_error(exc) from exc
    await sweep.sweep(conn, auth.organization_id)
    r = await _register(conn, auth)
    return _out(next(a for a in r["assets"] if a["id"] == aid))


@router.put("/assets/{asset_id}")
async def edit_asset(asset_id: uuid.UUID, body: AssetIn, auth: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    _require(auth)
    try:
        await assets.update(conn, auth.organization_id, asset_id, body.model_dump())
    except assets.AssetError as exc:
        raise _asset_error(exc) from exc
    await sweep.sweep(conn, auth.organization_id)
    r = await _register(conn, auth)
    return _out(next(a for a in r["assets"] if a["id"] == asset_id))


@router.post("/assets/{asset_id}/dispose")
async def dispose_asset(asset_id: uuid.UUID, body: DisposeIn, auth: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn)):
    _require(auth)
    try:
        await assets.dispose(conn, auth.organization_id, asset_id, body.disposed_on, body.disposal_value)
    except assets.AssetError as exc:
        raise _asset_error(exc) from exc
    await sweep.sweep(conn, auth.organization_id)
    r = await _register(conn, auth)
    return _out(next(a for a in r["assets"] if a["id"] == asset_id))


@router.delete("/assets/{asset_id}", status_code=204)
async def delete_asset(asset_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    _require(auth)
    try:
        await assets.delete(conn, auth.organization_id, asset_id)
    except assets.AssetError as exc:
        raise _asset_error(exc) from exc
    await sweep.sweep(conn, auth.organization_id)


# --- ACC-17: year end ----------------------------------------------------------------------------------------------

class CloseYearIn(BaseModel):
    acknowledge: bool = False


def _fy(label: str) -> datetime.date:
    try:
        return years.fy_from_label(label)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="A year as 2025-26.") from exc


@router.get("/years")
async def list_years(auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    today = await _today(conn, auth.organization_id)
    return _out({"today": today, "years": await years.years(conn, auth.organization_id, today)})


async def _year(conn: AsyncConnection, auth: AuthorizationContext, fy: str) -> dict[str, Any]:
    start = _fy(fy)
    today = await _today(conn, auth.organization_id)
    row = next((y for y in await years.years(conn, auth.organization_id, today) if y["financial_year"] == fy), None)
    if row is None:
        raise HTTPException(status_code=404, detail="The books have nothing in that year.")
    return {**row, "checklist": await years.checklist(conn, auth.organization_id, start, today),
            "carried": await years.carried(conn, auth.organization_id, start)}


@router.get("/years/{fy}")
async def get_year(fy: str, auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    return _out(await _year(conn, auth, fy))


@router.get("/years/{fy}/export")
async def year_export(fy: str, fmt: str = FORMAT, auth: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    y = await _year(conn, auth, fy)
    return _file(export.year_end(await _company(conn, auth.organization_id), fy, y["carried"], y["profit"],
                                 y["earlier_profit"]), fmt,
                 f"carried-forward-{fy}")


@router.post("/years/{fy}/close")
async def close_year(fy: str, body: CloseYearIn, auth: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    _owner_or_admin(auth, "close a year")
    await _ready(conn, auth)
    y = await _year(conn, auth, fy)
    if y["status"] == "closed":
        raise HTTPException(status_code=409, detail=f"{fy} is already closed.")
    blocking = [c for c in y["checklist"] if c["blocks"]]
    if blocking:
        raise HTTPException(status_code=409, detail=blocking[0]["words"])
    warnings = [c for c in y["checklist"] if not c["ok"] and c["key"] != "months"]
    if warnings and not body.acknowledge:
        raise HTTPException(status_code=409, detail={"code": "YEAR_END_WARNINGS", "message":
                            "Some checks are not done. Close anyway only if the CA agrees.",
                            "warnings": _out(warnings)})
    await years.close(conn, auth.organization_id, auth.user_id, _fy(fy))
    return _out(await _year(conn, auth, fy))


@router.post("/years/{fy}/reopen")
async def reopen_year(fy: str, body: ReasonIn, auth: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    _owner_or_admin(auth, "reopen a year")
    await years.reopen(conn, auth.organization_id, auth.user_id, _fy(fy), body.reason.strip())
    return _out(await _year(conn, auth, fy))


# --- ACC-18: cash flow; ACC-21: the statements as files -----------------------------------------------------------

async def _cash_flow(conn, auth, date_from, date_to, project_id, site_id):
    await _ready(conn, auth)
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    scope = await _scope_words(conn, auth.organization_id, project_id, site_id)
    cf = await statements.cash_flow(conn, auth.organization_id, date_from, date_to, project_id, site_id)
    return date_from, date_to, scope, cf


@router.get("/cash-flow")
async def cash_flow(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                    project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None,
                    auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    date_from, date_to, scope, cf = await _cash_flow(conn, auth, date_from, date_to, project_id, site_id)
    return _out({"date_from": date_from, "date_to": date_to, "scope": scope, **cf})


@router.get("/cash-flow/export")
async def cash_flow_export(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                           project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None, fmt: str = FORMAT,
                           auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    date_from, date_to, scope, cf = await _cash_flow(conn, auth, date_from, date_to, project_id, site_id)
    return _file(export.cash_flow(await _company(conn, auth.organization_id), scope, date_from, date_to, cf), fmt,
                 f"cash-flow-{date_from}-to-{date_to}")


@router.get("/pl/export")
async def pl_export(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                    project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None,
                    compare: str | None = Query(None, pattern="^(previous|last_year)$"), fmt: str = FORMAT,
                    auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    if project_id is not None and not may_manage_money(auth.role):
        await _ready_projects(conn, auth, project_id)
    else:
        await _ready(conn, auth)
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    scope = await _scope_words(conn, auth.organization_id, project_id, site_id)
    p = await statements.profit_and_loss(conn, auth.organization_id, date_from, date_to, project_id, site_id, compare)
    return _file(export.pl(await _company(conn, auth.organization_id), scope, date_from, date_to, p), fmt,
                 f"profit-and-loss-{date_from}-to-{date_to}")


@router.get("/balance-sheet/export")
async def balance_sheet_export(as_of: datetime.date | None = None, fmt: str = FORMAT,
                               auth: AuthorizationContext = Depends(get_auth_context),
                               conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    as_of = as_of or await _today(conn, auth.organization_id)
    b = await statements.balance_sheet(conn, auth.organization_id, as_of)
    return _file(export.balance_sheet(await _company(conn, auth.organization_id), b), fmt, f"balance-sheet-{as_of}")


@router.get("/cash-bank/export")
async def cash_bank_export(date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                           project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None, fmt: str = FORMAT,
                           auth: AuthorizationContext = Depends(get_auth_context), conn: AsyncConnection = Depends(get_db_conn)):
    await _ready(conn, auth)
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    scope = await _scope_words(conn, auth.organization_id, project_id, site_id)
    c = await statements.cash_bank(conn, auth.organization_id, date_from, date_to, project_id, site_id)
    return _file(export.cash_bank(await _company(conn, auth.organization_id), scope, date_from, date_to, c), fmt,
                 f"cash-and-bank-{date_from}-to-{date_to}")
