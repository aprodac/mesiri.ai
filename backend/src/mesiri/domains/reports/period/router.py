"""REST API for the period report (PRC-19). Read only.

  GET /reports/period        one project (or one of its sites), a week, a month or custom dates: headline, key
                             figures, "Needs you", and the sections (work, schedule, labour, materials, money,
                             issues, photos, is the data complete)
  GET /reports/period/pdf    the same report as a PDF on the company's letterhead (page 1: the 10-second view)
  GET /reports/period/xlsx   the same report as an Excel workbook, one sheet per section
  GET /reports/portfolio     the owner's brief (RPT-01): every project the person sees, one row each, worst first
                             (+ /pdf, /xlsx)
  POST /reports/send         send a report on WhatsApp now (PRC-20): each person gets it as their own access shows
  GET /reports/sent          what was sent, to whom, and whether WhatsApp got it
  GET /reports/sent/{id}     one sent copy, frozen, with what changed since (+ /pdf: the PDF as sent)
  GET/POST /reports/schedules, DELETE /reports/schedules/{id}
                             a report that goes by itself every week or on the 1st: an ``automations`` row
                             (``SEND_PERIOD_REPORT``), fired by the automations runner, not behind the
                             automations module's switch

All three render one read (``engine.build``), so they never disagree. Mounted in the dashboard API and the
production app (``runtime/lifecycle.py``).
"""

from __future__ import annotations

import datetime
import re
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.organizations import settings as org_settings
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.reports.period import engine, periods
from mesiri.domains.shared.modules import read_enabled_modules
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(prefix="/reports", tags=["reports"])


async def _enabled(request: Request, auth: AuthorizationContext):
    stored = await read_enabled_modules(request, auth.organization_id)
    return lambda m: org_settings.module_enabled(m, stored)


def _period(period: str, today: datetime.date, date: datetime.date | None, date_from: datetime.date | None,
            date_to: datetime.date | None) -> periods.Period:
    try:
        chosen = periods.resolve(period, today, anchor=date, date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if chosen.start > today:
        raise HTTPException(status_code=422, detail="That period has not started yet.")
    return chosen


async def _report(request: Request, auth: AuthorizationContext, conn: AsyncConnection, storage: Any,
                  project_id: uuid.UUID, site_id: uuid.UUID | None, period: str, date: datetime.date | None,
                  date_from: datetime.date | None, date_to: datetime.date | None) -> dict[str, Any]:
    from mesiri.application.dpr.project_day import company_today

    today = await company_today(conn, auth.organization_id)
    chosen = _period(period, today, date, date_from, date_to)
    return await engine.build(conn, auth, project_id=project_id, site_id=site_id, period=chosen,
                              enabled=await _enabled(request, auth), storage=storage, today=today)


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


# -- the owner's brief (RPT-01) ---------------------------------------------------------------------------------------

async def _brief(request: Request, auth: AuthorizationContext, conn: AsyncConnection, period: str,
                 date: datetime.date | None, date_from: datetime.date | None,
                 date_to: datetime.date | None) -> dict[str, Any]:
    from mesiri.application.dpr.project_day import company_today
    from mesiri.domains.reports.period import portfolio

    today = await company_today(conn, auth.organization_id)
    return await portfolio.build(conn, auth, period=_period(period, today, date, date_from, date_to),
                                 enabled=await _enabled(request, auth), today=today)


@router.get("/portfolio")
async def portfolio_report(
    request: Request,
    period: Literal["week", "month", "custom"] = Query(default="week", description=_PERIOD_DOC),
    date: datetime.date | None = Query(default=None, description=_DATE_DOC),
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> dict[str, Any]:
    """All the projects this person sees in one view, the one that needs them most first: done against plan, cost,
    finish date, man-days, issues and (for the roles that see spending) what clients owe. Each row is the
    project's own period report."""
    return await _brief(request, auth, conn, period, date, date_from, date_to)


def _brief_filename(brief: dict[str, Any], ext: str) -> str:
    p = brief["period"]
    when = p["from"][:7] if p["kind"] == "month" else p["from"] if p["kind"] == "week" else f"{p['from']}-{p['to']}"
    return f"mesiri-all-projects-{p['kind']}-{when}.{ext}"


@router.get("/portfolio/pdf")
async def portfolio_report_pdf(
    request: Request,
    period: Literal["week", "month", "custom"] = Query(default="week", description=_PERIOD_DOC),
    date: datetime.date | None = Query(default=None, description=_DATE_DOC),
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    storage: Any = Depends(get_object_storage),
) -> Response:
    """The owner's brief as a PDF on the company's letterhead."""
    from mesiri.application.organizations.branding_admin import branding_view
    from mesiri.domains.reports.period.pdf import render_portfolio

    brief = await _brief(request, auth, conn, period, date, date_from, date_to)
    company = await branding_view(conn, storage, auth.organization_id) or {}
    return Response(content=render_portfolio(brief, company), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{_brief_filename(brief, "pdf")}"'})


@router.get("/portfolio/xlsx")
async def portfolio_report_xlsx(
    request: Request,
    period: Literal["week", "month", "custom"] = Query(default="week", description=_PERIOD_DOC),
    date: datetime.date | None = Query(default=None, description=_DATE_DOC),
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> Response:
    """The owner's brief as an Excel workbook: Summary and one row per project."""
    from mesiri.domains.reports.period.xlsx import portfolio_workbook

    brief = await _brief(request, auth, conn, period, date, date_from, date_to)
    return Response(content=portfolio_workbook(brief),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{_brief_filename(brief, "xlsx")}"'})


# -- sending (PRC-20) -------------------------------------------------------------------------------------------------

class SendRequest(BaseModel):
    scope: Literal["project", "portfolio"] = "project"
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    period: Literal["week", "month", "custom"] = "week"
    date: datetime.date | None = None
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    #: Who gets it; empty: the sender alone.
    recipient_user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    #: Or people's names as said ("Sajan", "Adarsh"): matched to the company's active people.
    recipient_names: list[str] = Field(default_factory=list, max_length=20)
    note: str | None = Field(default=None, max_length=300)


async def _recipients(conn: AsyncConnection, auth: AuthorizationContext, ids: list[uuid.UUID],
                      names: list[str]) -> list[uuid.UUID]:
    """The people a report goes to: ids as given, plus each name matched to one active person of the company (the
    whole name, else the start of a name). A name that fits nobody, or more than one person, is refused with the
    names to choose from: never a guess about who gets the company's figures."""
    out = list(ids)
    if names:
        people = (await conn.execute(text(
            "SELECT id, full_name FROM users WHERE organization_id = :org AND COALESCE(status, 'active') = 'active' "
            "AND full_name IS NOT NULL"), {"org": auth.organization_id})).mappings().all()
        for said in names:
            want = " ".join(said.lower().split())
            exact = [p for p in people if " ".join(p["full_name"].lower().split()) == want]
            fits = exact or [p for p in people if any(w.startswith(want) for w in p["full_name"].lower().split())
                             or p["full_name"].lower().startswith(want)]
            if len(fits) != 1:
                choose = ", ".join(sorted(p["full_name"] for p in fits)[:6])
                detail = (f'"{said}" fits {choose}: say which.' if fits
                          else f'No one called "{said}" in the company.')
                raise HTTPException(status_code=422, detail=detail)
            out.append(fits[0]["id"])
    return list(dict.fromkeys(out or [auth.user_id]))


@router.post("/send")
async def send_report(
    body: SendRequest,
    request: Request,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    storage: Any = Depends(get_object_storage),
) -> dict[str, Any]:
    """Send a weekly / monthly report on WhatsApp now: a short summary with the PDF. Each person gets it as their own
    access shows (their projects, rupees only for the roles that see spending); a person who cannot open it, or has
    no WhatsApp number, is skipped and named. Outside WhatsApp's 24-hour window it goes once the template is
    approved. Sending to others is for owners, admins and project managers; anyone may send one to themselves."""
    from mesiri.application.dpr.project_day import company_today
    from mesiri.authorization.roles import may_send_reports_to_others
    from mesiri.domains.reports.period import send

    if body.scope == "project" and body.project_id is None:
        raise HTTPException(status_code=422, detail="Say which project the report is for.")
    recipients = await _recipients(conn, auth, body.recipient_user_ids, body.recipient_names)
    if any(r != auth.user_id for r in recipients) and not may_send_reports_to_others(auth.role):
        raise HTTPException(status_code=403, detail="Owners, admins and project managers send reports to others. "
                                                    "You can send one to yourself.")
    if body.scope == "project":
        from mesiri.domains.schedule.router import _project

        await _project(conn, auth, body.project_id)  # the sender must reach the project themselves
    today = await company_today(conn, auth.organization_id)
    chosen = _period(body.period, today, body.date, body.date_from, body.date_to)
    sender = (await conn.execute(text("SELECT full_name FROM users WHERE id = :id"),
                                 {"id": auth.user_id})).scalar()
    return await send.deliver(conn, storage, org=auth.organization_id, scope=body.scope, period=chosen,
                              recipient_ids=recipients, enabled=await _enabled(request, auth), today=today,
                              project_id=body.project_id, site_id=body.site_id, note=body.note,
                              sent_by=auth.user_id, sent_by_name=sender, trigger="now")


@router.get("/sent")
async def sent_reports(
    project_id: uuid.UUID | None = None,
    scope: Literal["project", "portfolio"] = "project",
    limit: int = Query(default=20, ge=1, le=100),
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> dict[str, Any]:
    """Reports sent, newest first: when, by whom, the note, and per person whether WhatsApp got it (or why not).
    Owners, admins and project managers see every send of the project; others their own and what they were sent."""
    from mesiri.authorization.roles import may_send_reports_to_others
    from mesiri.domains.reports.period import send

    if scope == "project":
        if project_id is None:
            raise HTTPException(status_code=422, detail="Say which project.")
        from mesiri.domains.schedule.router import _project

        await _project(conn, auth, project_id)
    mine = None if may_send_reports_to_others(auth.role) else auth.user_id
    return {"sends": await send.list_sent(conn, auth.organization_id, project_id=project_id, scope=scope,
                                          sent_by=mine, limit=limit)}


async def _own_snapshot(conn: AsyncConnection, auth: AuthorizationContext, snapshot_id: uuid.UUID) -> dict[str, Any]:
    """A sent copy this person may open: their own, or one in a project they manage (owners, admins, PMs)."""
    from mesiri.authorization.roles import may_send_reports_to_others
    from mesiri.domains.reports.period import send

    snap = await send.snapshot(conn, auth.organization_id, snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="Sent report not found")
    own = auth.user_id in (snap["recipient_user_id"], snap["sent_by"])
    if not own:
        if not may_send_reports_to_others(auth.role):
            raise HTTPException(status_code=404, detail="Sent report not found")
        if snap["project_id"] is not None:
            from mesiri.domains.schedule.router import _project

            await _project(conn, auth, snap["project_id"])
    return snap


@router.get("/sent/{snapshot_id}")
async def sent_report(
    snapshot_id: uuid.UUID,
    request: Request,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> dict[str, Any]:
    """One sent copy exactly as it went, and which key figures have changed since (a late attendance, an expense
    entered after), read again as the person it was sent to sees them."""
    from mesiri.domains.reports.period import send

    snap = await _own_snapshot(conn, auth, snapshot_id)
    changed: list[dict[str, str]] = []
    try:
        async with conn.begin_nested():
            from mesiri.application.dpr.project_day import company_today
            from mesiri.authorization.service import AuthorizationService
            from mesiri.domains.reports.period import portfolio

            whose = snap["recipient_user_id"] or auth.user_id
            them = await AuthorizationService(conn).resolve_from_jwt(whose, auth.organization_id, "")
            p = periods.Period(snap["period_kind"], snap["date_from"], snap["date_to"])
            today = await company_today(conn, auth.organization_id)
            enabled = await _enabled(request, auth)
            now = (await engine.build(conn, them, project_id=snap["project_id"], site_id=snap["site_id"], period=p,
                                      enabled=enabled, today=today, with_waiting=False)
                   if snap["scope"] == "project" else
                   await portfolio.build(conn, them, period=p, enabled=enabled, today=today))
            changed = send.changed_since(snap["report"], now)
    except Exception:  # noqa: BLE001 -- the frozen copy still opens; "what changed" is a bonus
        changed = []
    return {"snapshot_id": str(snap["id"]), "send_id": str(snap["send_id"]), "scope": snap["scope"],
            "note": snap["note"], "created_at": snap["created_at"].isoformat(), "report": snap["report"],
            "changed_since": changed}


@router.get("/sent/{snapshot_id}/pdf")
async def sent_report_pdf(
    snapshot_id: uuid.UUID,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    storage: Any = Depends(get_object_storage),
) -> Response:
    """The PDF exactly as it was sent."""
    snap = await _own_snapshot(conn, auth, snapshot_id)
    if not snap["pdf_object_key"]:
        raise HTTPException(status_code=404, detail="This copy has no PDF")
    stored = await storage.get_object(snap["pdf_object_key"])
    return Response(content=stored.data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="sent-report-{snapshot_id}.pdf"'})


# -- schedules (PRC-20): rows of the automations table, fired by its runner -----------------------------------------

class ScheduleRequest(BaseModel):
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    #: WEEKLY: the week just finished, on ``day_of_week`` (0 = Monday). MONTHLY: last month, on the 1st.
    frequency: Literal["WEEKLY", "MONTHLY"] = "WEEKLY"
    day_of_week: int | None = Field(default=0, ge=0, le=6)
    time_of_day: str = Field(default="08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    #: Who gets it; empty: the person setting it up.
    recipient_user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    recipient_names: list[str] = Field(default_factory=list, max_length=20)
    note: str | None = Field(default=None, max_length=300)


def _schedule_out(row: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    ids = [str(u) for u in (row.get("audience_user_ids") or [])] or [str(row["created_by"])]
    return {"id": str(row["id"]), "project_id": str(row["project_id"]) if row.get("project_id") else None,
            "site_id": str(row["site_id"]) if row.get("site_id") else None, "frequency": row["frequency"],
            "day_of_week": row.get("day_of_week"), "time_of_day": row["time_of_day"], "timezone": row["timezone"],
            "note": row.get("message"), "enabled": row.get("enabled", True),
            "last_run_on": row["last_run_on"].isoformat() if row.get("last_run_on") else None,
            "recipients": [{"user_id": u, "name": names.get(u, "Someone")} for u in ids],
            "created_by": str(row["created_by"]) if row.get("created_by") else None}


async def _names(conn: AsyncConnection, org: uuid.UUID, rows: list[dict[str, Any]]) -> dict[str, str]:
    ids = {str(u) for r in rows for u in (r.get("audience_user_ids") or [])} | {str(r["created_by"]) for r in rows
                                                                                 if r.get("created_by")}
    if not ids:
        return {}
    got = (await conn.execute(text("SELECT id, full_name FROM users WHERE organization_id = :org AND id = ANY(:ids)"),
                              {"org": org, "ids": [uuid.UUID(i) for i in ids]})).mappings().all()
    return {str(r["id"]): r["full_name"] or "Someone" for r in got}


async def _report_schedules(conn: AsyncConnection, auth: AuthorizationContext) -> list[dict[str, Any]]:
    from mesiri.authorization.roles import may_send_reports_to_others
    from mesiri.infrastructure.postgres.repositories.automations import PostgresAutomationRepository

    rows = [r for r in await PostgresAutomationRepository(conn).list_for_org(organization_id=auth.organization_id)
            if r["action"] == "SEND_PERIOD_REPORT"]
    if not may_send_reports_to_others(auth.role):  # the rest see the ones they set up or receive
        me = str(auth.user_id)
        rows = [r for r in rows if str(r.get("created_by")) == me or me in [str(u) for u in r.get("audience_user_ids")
                                                                             or []]]
    return rows


@router.get("/schedules")
async def report_schedules(
    project_id: uuid.UUID | None = None,
    scope: Literal["project", "portfolio"] = "project",
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> dict[str, Any]:
    """The weekly / monthly reports that go by themselves: for one project, or the all-projects brief."""
    rows = [r for r in await _report_schedules(conn, auth)
            if (scope == "portfolio" and r.get("project_id") is None)
            or (scope == "project" and project_id is not None and str(r.get("project_id")) == str(project_id))]
    names = await _names(conn, auth.organization_id, rows)
    return {"schedules": [_schedule_out(r, names) for r in rows]}


@router.post("/schedules", status_code=201)
async def add_report_schedule(
    body: ScheduleRequest,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> dict[str, Any]:
    """Send a report by itself: every week (the week just finished, Monday to Sunday) on a day and time, or every
    month on the 1st (last month). For one project, or every project (the owner's brief) when none is given. Each
    person gets it as their own access shows. Sending to others is for owners, admins and project managers."""
    from mesiri.application.dpr.project_day import zone_sql
    from mesiri.authorization.roles import may_send_reports_to_others
    from mesiri.infrastructure.postgres.repositories.automations import PostgresAutomationRepository

    recipients = await _recipients(conn, auth, body.recipient_user_ids, body.recipient_names)
    if any(r != auth.user_id for r in recipients) and not may_send_reports_to_others(auth.role):
        raise HTTPException(status_code=403, detail="Owners, admins and project managers send reports to others. "
                                                    "You can set one up for yourself.")
    if body.project_id is not None:
        from mesiri.domains.schedule.router import _project

        await _project(conn, auth, body.project_id)
    if body.frequency == "WEEKLY" and body.day_of_week is None:
        raise HTTPException(status_code=422, detail="Say which day of the week.")
    found = (await conn.execute(text("SELECT count(*) FROM users WHERE organization_id = :org AND id = ANY(:ids)"),
                                {"org": auth.organization_id, "ids": recipients})).scalar()
    if found != len(recipients):
        raise HTTPException(status_code=422, detail="Someone on the list is not in this company.")
    zone = (await conn.execute(text(f"SELECT {zone_sql(':org_id')}"), {"org_id": auth.organization_id})).scalar()
    only_me = recipients == [auth.user_id]
    row = await PostgresAutomationRepository(conn).create(
        organization_id=auth.organization_id, project_id=body.project_id, site_id=body.site_id,
        action="SEND_PERIOD_REPORT", audience="SELF" if only_me else "USERS",
        audience_user_ids=None if only_me else [str(r) for r in recipients], audience_role=None,
        message=(body.note or "").strip() or None, frequency=body.frequency,
        day_of_week=body.day_of_week if body.frequency == "WEEKLY" else None, time_of_day=body.time_of_day,
        timezone=zone or "Asia/Kolkata", created_by=auth.user_id)
    return _schedule_out(row, await _names(conn, auth.organization_id, [row]))


@router.delete("/schedules/{schedule_id}")
async def stop_report_schedule(
    schedule_id: uuid.UUID,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> dict[str, Any]:
    """Stop a report going by itself. Owners, admins and project managers stop any; others the ones they set up."""
    from mesiri.authorization.roles import may_send_reports_to_others
    from mesiri.infrastructure.postgres.repositories.automations import PostgresAutomationRepository

    repo = PostgresAutomationRepository(conn)
    row = await repo.get(organization_id=auth.organization_id, automation_id=schedule_id)
    if row is None or row["action"] != "SEND_PERIOD_REPORT":
        raise HTTPException(status_code=404, detail="Report schedule not found")
    if str(row.get("created_by")) != str(auth.user_id) and not may_send_reports_to_others(auth.role):
        raise HTTPException(status_code=403, detail="Only the person who set it up, or an owner, admin or project "
                                                    "manager, can stop it.")
    await repo.delete(organization_id=auth.organization_id, automation_id=schedule_id)
    return {"stopped": str(schedule_id)}
