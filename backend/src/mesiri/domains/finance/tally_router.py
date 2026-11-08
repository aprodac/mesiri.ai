"""NXT-12: GET /finance/tally/export?date_from&date_to -- a period's expenses and payments as Tally XML (``tally.py``).

For the roles that manage money (owner, admin, finance): it is the company's books leaving Mesiri. Company-wide
(Tally keeps one set of books per company); a period of at most a year.
"""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException
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


@router.get("/summary")
async def tally_summary(
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """What the export for the period would hold (vouchers, ledgers, GST split), before downloading it."""
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    expenses, payments = await tally.fetch(conn, auth.organization_id, date_from, date_to)
    _, counts = tally.build("", expenses, payments)
    return {"date_from": str(date_from), "date_to": str(date_to), **counts}


@router.get("/export")
async def tally_export(
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    date_from, date_to = await _period(conn, auth, date_from, date_to)
    company = (await conn.execute(text("SELECT name FROM organizations WHERE id = :o"),
                                  {"o": auth.organization_id})).scalar() or "Company"
    expenses, payments = await tally.fetch(conn, auth.organization_id, date_from, date_to)
    xml, _ = tally.build(company, expenses, payments)
    return Response(content=xml, media_type="application/xml", headers={
        "Content-Disposition": f'attachment; filename="mesiri-tally-{date_from}-to-{date_to}.xml"'})
