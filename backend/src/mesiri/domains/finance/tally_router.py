"""NXT-12: GET /finance/tally/export?date_from&date_to -- a period's expenses, payments, RA bills and money received
from clients as Tally XML (``tally.py``).

ACC-19 (10 Nov 2026): when the company has the Accounts module on, both routes read the **posted journals** instead
(``accounts/tally_books.py``, after posting what changed): one source of truth, so Tally gets exactly what the trial
balance shows (manual vouchers, depreciation, the month-end accrual and changes after close too). Companies without
Accounts keep NXT-12's export from the records, unchanged.

For the roles that manage money (owner, admin, finance): it is the company's books leaving Mesiri. Company-wide
(Tally keeps one set of books per company); a period of at most a year.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_manage_money
from mesiri.domains.finance import tally
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(prefix="/finance/tally", tags=["tally"], dependencies=[Depends(require_module("finance"))])


async def _period(conn: AsyncConnection, auth: AuthorizationContext, date_from, date_to):
    from mesiri.application.dpr import project_day

    if not may_manage_money(auth.role):
        raise HTTPException(status_code=403, detail="Only the owner, an admin or finance can export the books.")
    date_to = date_to or await project_day.company_today(conn, auth.organization_id)
    date_from = date_from or date_to.replace(day=1)
    if date_from > date_to or (date_to - date_from).days > 366:
        raise HTTPException(status_code=422, detail="Pick a period of at most a year, start before end.")
    return date_from, date_to


async def _from_books(request: Request, conn: AsyncConnection, auth: AuthorizationContext) -> bool:
    """Accounts on: the export is the books (posted first, so they are current)."""
    from mesiri.domains.accounts import sweep
    from mesiri.domains.organizations import settings as org_settings
    from mesiri.domains.shared import modules  # looked up when called, as the module gate does

    if not org_settings.module_enabled("accounts", await modules.read_enabled_modules(request, auth.organization_id)):
        return False
    await sweep.sweep(conn, auth.organization_id)
    return True


async def _company(conn: AsyncConnection, auth: AuthorizationContext) -> str:
    return (await conn.execute(text("SELECT name FROM organizations WHERE id = :o"),
                               {"o": auth.organization_id})).scalar() or "Company"


@router.get("/summary")
async def tally_summary(
    request: Request,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """What the export for the period would hold (vouchers, ledgers, GST split), before downloading it."""
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    if await _from_books(request, conn, auth):
        from mesiri.domains.accounts import tally_books

        _, counts = await tally_books.export(conn, auth.organization_id, "", date_from, date_to)
        return {"date_from": str(date_from), "date_to": str(date_to), **counts}
    expenses, payments = await tally.fetch(conn, auth.organization_id, date_from, date_to)
    sales, received = await tally.fetch_clients(conn, auth.organization_id, date_from, date_to)
    _, counts = tally.build("", expenses, payments, sales, received)
    return {"date_from": str(date_from), "date_to": str(date_to), **counts}


@router.get("/export")
async def tally_export(
    request: Request,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    company = await _company(conn, auth)
    if await _from_books(request, conn, auth):
        from mesiri.domains.accounts import tally_books

        xml, _ = await tally_books.export(conn, auth.organization_id, company, date_from, date_to)
        return Response(content=xml, media_type="application/xml", headers={
            "Content-Disposition": f'attachment; filename="mesiri-books-tally-{date_from}-to-{date_to}.xml"'})
    expenses, payments = await tally.fetch(conn, auth.organization_id, date_from, date_to)
    sales, received = await tally.fetch_clients(conn, auth.organization_id, date_from, date_to)
    xml, _ = tally.build(company, expenses, payments, sales, received)
    return Response(content=xml, media_type="application/xml", headers={
        "Content-Disposition": f'attachment; filename="mesiri-tally-{date_from}-to-{date_to}.xml"'})
