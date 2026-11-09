"""REST API for the period report (PRC-19). Read only.

  GET /reports/period        one project (or one of its sites), a week, a month or custom dates: headline, key
                             figures, "Needs you", and the sections (work, schedule, labour, materials, money,
                             issues, photos, is the data complete)
  GET /reports/period/pdf    the same report as a PDF on the company's letterhead (page 1: the 10-second view)
  GET /reports/period/xlsx   the same report as an Excel workbook, one sheet per section

All three render one read (``engine.build``), so they never disagree. Mounted in the dashboard API and the
production app (``runtime/lifecycle.py``).
"""

from __future__ import annotations

import datetime
import re
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.organizations import settings as org_settings
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.reports.period import engine, periods
from mesiri.domains.shared.modules import read_enabled_modules
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(prefix="/reports", tags=["reports"])


async def _report(request: Request, auth: AuthorizationContext, conn: AsyncConnection, storage: Any,
                  project_id: uuid.UUID, site_id: uuid.UUID | None, period: str, date: datetime.date | None,
                  date_from: datetime.date | None, date_to: datetime.date | None) -> dict[str, Any]:
    from mesiri.application.dpr.project_day import company_today

    today = await company_today(conn, auth.organization_id)
    try:
        chosen = periods.resolve(period, today, anchor=date, date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if chosen.start > today:
        raise HTTPException(status_code=422, detail="That period has not started yet.")
    stored = await read_enabled_modules(request, auth.organization_id)
    return await engine.build(conn, auth, project_id=project_id, site_id=site_id, period=chosen,
                              enabled=lambda m: org_settings.module_enabled(m, stored), storage=storage, today=today)


_PERIOD_DOC = "week (Monday to Sunday), month, or custom (date_from and date_to, at most 92 days)"
_DATE_DOC = "Any day in the week or month wanted; default: the last finished week or month"


@router.get("/period")
async def period_report(
    request: Request,
    project_id: uuid.UUID,
    site_id: uuid.UUID | None = None,
    period: Literal["week", "month", "custom"] = Query(default="week", description=_PERIOD_DOC),
    date: datetime.date | None = Query(default=None, description=_DATE_DOC),
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    storage: Any = Depends(get_object_storage),
) -> dict[str, Any]:
    """A week or a month of one project: a headline sentence, the key figures against plan and the last period,
    what needs you, and each section. Money only for the roles that see spending; client bills only for the roles
    that see them; a section whose module is switched off is left out."""
    return engine.public(await _report(request, auth, conn, storage, project_id, site_id, period, date, date_from,
                                       date_to))


def _filename(report: dict[str, Any], ext: str) -> str:
    name = re.sub(r"[^A-Za-z0-9]+", "-", report["project"]["name"]).strip("-").lower() or "project"
    p = report["period"]
    when = p["from"][:7] if p["kind"] == "month" else f"{p['from']}" if p["kind"] == "week" else f"{p['from']}-{p['to']}"
    kind = {"week": "week", "month": "month"}.get(p["kind"], "report")
    return f"mesiri-{name}-{kind}-{when}.{ext}"


@router.get("/period/pdf")
async def period_report_pdf(
    request: Request,
    project_id: uuid.UUID,
    site_id: uuid.UUID | None = None,
    period: Literal["week", "month", "custom"] = Query(default="week", description=_PERIOD_DOC),
    date: datetime.date | None = Query(default=None, description=_DATE_DOC),
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    storage: Any = Depends(get_object_storage),
) -> Response:
    """The period report as a PDF: page 1 is the letterhead, the headline, four figures, one row per area and up to
    four photos; the sections follow."""
    from mesiri.application.organizations.branding_admin import branding_view
    from mesiri.domains.reports.period.pdf import photo_bytes, render

    report = await _report(request, auth, conn, storage, project_id, site_id, period, date, date_from, date_to)
    company = await branding_view(conn, storage, auth.organization_id) or {}
    images = await photo_bytes(storage, report["sections"].get("photos"))
    data = render(report, company, images)
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{_filename(report, "pdf")}"'})


@router.get("/period/xlsx")
async def period_report_xlsx(
    request: Request,
    project_id: uuid.UUID,
    site_id: uuid.UUID | None = None,
    period: Literal["week", "month", "custom"] = Query(default="week", description=_PERIOD_DOC),
    date: datetime.date | None = Query(default=None, description=_DATE_DOC),
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    storage: Any = Depends(get_object_storage),
) -> Response:
    """The period report as an Excel workbook: Summary, then one sheet per section, plain columns (numbers as
    numbers), ready for a pivot table."""
    from mesiri.domains.reports.period.xlsx import workbook

    report = await _report(request, auth, conn, None, project_id, site_id, period, date, date_from, date_to)
    return Response(content=workbook(report),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{_filename(report, "xlsx")}"'})
