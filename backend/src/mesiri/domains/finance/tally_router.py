"""NXT-12: GET /finance/tally/export?date_from&date_to -- a period's expenses, payments, RA bills and money received
from clients as Tally XML (``tally.py``).

ACC-19: a company with the Accounts module on is exported from its posted journals (``tally.from_books``), after the
sweep has posted what changed, so Tally holds what the trial balance holds (manual vouchers included). A company
without Accounts keeps the records path (D-ACC10). Same routes, same file name.

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
from mesiri.domains.shared import modules
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


async def _xml(request: Request, conn: AsyncConnection, auth: AuthorizationContext, company: str,
               date_from: datetime.date, date_to: datetime.date) -> tuple[str, dict]:
    """From the books when Accounts is on, else from the records."""
    from mesiri.domains.organizations import settings as org_settings

    org = auth.organization_id
    if org_settings.module_enabled("accounts", await modules.read_enabled_modules(request, org)):
        from mesiri.domains.accounts import chart, reports, sweep

        await sweep.sweep(conn, org)
        book = await reports.entries(conn, org, date_from=date_from, date_to=date_to, limit=100_000)
        return tally.from_books(company, await chart.groups(conn, org), await chart.ledgers(conn, org), book["entries"])
    expenses, payments = await tally.fetch(conn, org, date_from, date_to)
    sales, received = await tally.fetch_clients(conn, org, date_from, date_to)
    xml, counts = tally.build(company, expenses, payments, sales, received)
    return xml, {"source": "records", **counts}


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
    _, counts = await _xml(request, conn, auth, "", date_from, date_to)
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
    company = (await conn.execute(text("SELECT name FROM organizations WHERE id = :o"),
                                  {"o": auth.organization_id})).scalar() or "Company"
    xml, _ = await _xml(request, conn, auth, company, date_from, date_to)
    return Response(content=xml, media_type="application/xml", headers={
        "Content-Disposition": f'attachment; filename="mesiri-tally-{date_from}-to-{date_to}.xml"'})
