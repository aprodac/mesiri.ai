"""The DPR as a document, live (WEB-27): the site DPR page shows the day as
the PDF will look, refreshing as updates arrive.

Returns the HTML the PDF is printed from -- channel/dpr_document's template,
filled from the day as it stands now (the same assembly the report itself
is built from, without what the sender cancelled) -- so the page and the PDF
cannot drift apart. Read-only; nothing is stored or sent. Lives in this app,
not backend/, because the template does (ADR-D8 keeps Playwright and the
document template out of the backend package).

Access is each page's own rule (dpr/router.py get_site_day and
get_project_day): the company's site, a project the caller can see, and
BE-42's custom site scope.
"""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.dpr.router import _resolve_project_ids, _site_denied
from mesiri.domains.projects.router import get_auth_context
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

router = APIRouter(prefix="/dpr", tags=["dpr"])

#: The document's code line until the engineer confirms the day.
LIVE_CODE = "Live preview · not confirmed yet"

#: The project document's code line until it is sent.
PROJECT_PREVIEW_CODE = "Preview · not sent yet"

FROZEN = ("approved", "published")


@router.get("/site-days/{site_id}/document", response_class=HTMLResponse)
async def site_day_document(
    site_id: uuid.UUID,
    report_date: datetime.date = Query(alias="date"),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    object_storage=Depends(get_object_storage),
) -> HTMLResponse:
    from channel.dpr_document.data import build_document_data
    from channel.dpr_document.template import render_html
    from runtime.dpr_request_query import for_document, only_kept

    repo = PostgresDprRepository(conn)
    site = await repo.find_site(organization_id=auth_context.organization_id, site_id=site_id)
    if site is None or site["project_id"] is None:
        raise HTTPException(status_code=404, detail="Site not found")
    project_id = site["project_id"]
    if _site_denied(auth_context, project_id, site_id):
        raise HTTPException(status_code=404, detail="Site not found")

    payload, items = await repo.assemble_site_day(
        organization_id=auth_context.organization_id,
        project_id=project_id,
        site_id=site_id,
        report_date=report_date,
    )
    # The day's report row, if the cutoff or a confirm has made one: its code
    # names the document once confirmed; its letterhead brands it.
    report = await _report_row(conn, auth_context.organization_id, project_id, report_date, site_id)
    confirmed = report is not None and report["status"].lower() in FROZEN
    code = (report["code"] if confirmed else None) or LIVE_CODE
    summary = (
        await repo.get_current_summary(
            organization_id=auth_context.organization_id, report_id=report["id"]
        )
        if report is not None
        else None
    )

    letterhead = await _letterhead(
        conn, object_storage, auth_context.organization_id, project_id, report
    )

    return _document(
        render_html(
            build_document_data(
                code=code, payload=for_document(only_kept(payload, items)), summary=summary
            ),
            letterhead,
        )
    )


@router.get("/project-days/{project_id}/document", response_class=HTMLResponse)
async def project_day_document(
    project_id: uuid.UUID,
    report_date: datetime.date = Query(alias="date"),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    object_storage=Depends(get_object_storage),
) -> HTMLResponse:
    """The project DPR as a document: as it was sent once it has gone out,
    otherwise what would go out now from the sites confirmed so far (the
    project DPR page's own preview; writes nothing)."""
    from channel.dpr_document.data import build_document_data
    from channel.dpr_document.template import render_html

    _, denied = _resolve_project_ids(auth_context, project_id)
    if denied:
        raise HTTPException(status_code=404, detail="Project not found")
    repo = PostgresDprRepository(conn)
    report = await _report_row(conn, auth_context.organization_id, project_id, report_date)
    sent = report is not None and report["status"].lower() in FROZEN
    payload = (
        await repo.get_current_payload(
            organization_id=auth_context.organization_id, report_id=report["id"]
        )
        if sent
        else None
    )
    if payload is None:
        sent = False
        payload, _ = await repo.assemble_project_report_payload(
            organization_id=auth_context.organization_id,
            project_id=project_id,
            report_date=report_date,
            preview=True,
        )
    if not payload:
        raise HTTPException(status_code=404, detail="Project not found")
    summary = (
        await repo.get_current_summary(
            organization_id=auth_context.organization_id, report_id=report["id"]
        )
        if sent
        else None
    )
    letterhead = await _letterhead(
        conn, object_storage, auth_context.organization_id, project_id, report
    )
    code = (report["code"] if sent else None) or PROJECT_PREVIEW_CODE
    return _document(
        render_html(build_document_data(code=code, payload=payload, summary=summary), letterhead)
    )


async def _report_row(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    report_date: datetime.date,
    site_id: uuid.UUID | None = None,
) -> dict | None:
    """The day's SITE (with ``site_id``) or PROJECT ``daily_reports`` row, if
    the cutoff or a confirm has made one -- never creates it."""
    level = "SITE" if site_id else "PROJECT"
    row = (
        (
            await conn.execute(
                text(
                    "SELECT id, code, status::text AS status FROM daily_reports"
                    " WHERE organization_id = :org AND project_id = :p AND report_date = :d"
                    f" AND level = '{level}'" + (" AND site_id = :s" if site_id else "")
                ),
                {"org": org_id, "p": project_id, "d": report_date, "s": site_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


async def _letterhead(
    conn: AsyncConnection, object_storage, org_id: uuid.UUID, project_id: uuid.UUID, report
):
    """The letterhead hangs off a report row; before the cutoff makes the
    day's, borrow the project's latest so the preview still carries the
    company's branding."""
    from channel.dpr_document.letterhead import load_letterhead

    report_id = report["id"] if report is not None else None
    if report_id is None:
        report_id = (
            await conn.execute(
                text(
                    "SELECT id FROM daily_reports WHERE organization_id = :org AND project_id = :p"
                    " ORDER BY report_date DESC, created_at DESC LIMIT 1"
                ),
                {"org": org_id, "p": project_id},
            )
        ).scalar()
    return await load_letterhead(conn, object_storage, report_id) if report_id else None


def _document(html: str) -> HTMLResponse:
    # Shown in a sandboxed frame on the dashboard; never cache a live day.
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
