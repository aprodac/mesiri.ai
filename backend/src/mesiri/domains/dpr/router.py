"""REST API for Daily Progress Reports (DPR).

Mounted at /dpr so:
  GET   /dpr/site-days?date=YYYY-MM-DD     every active site's working day (BE-08)
  GET   /dpr/daily-reports                 list daily reports
  GET   /dpr/daily-reports/{report_id}     get daily report details
  POST  /dpr/daily-reports                 create daily report draft
  POST  /dpr/daily-reports/{report_id}/approve approve a report
  POST  /dpr/daily-reports/{report_id}/revise  correct an approved/published report
"""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.dpr.pdf import render_dpr_pdf_bytes
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository
from mesiri_contracts.common.storage import ObjectStoragePort

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/dpr",
    tags=["dpr"],
    dependencies=[Depends(require_module("dpr"))],
)


class CreateDprRequest(BaseModel):
    report_date: str
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    weather: str = "sunny"
    temperature_celsius: float | None = None
    shift: str = "day"
    narrative_summary: str | None = None
    work_items: list[dict[str, Any]] = []
    labour_items: list[dict[str, Any]] = []
    equipment_items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []


class ApproveDprRequest(BaseModel):
    notes: str | None = None


class ReviseDprRequest(BaseModel):
    revision_reason: str
    narrative_summary: str | None = None


def _resolve_project_ids(
    auth_context: AuthorizationContext, project_id: uuid.UUID | None
) -> tuple[set[uuid.UUID] | None, bool]:
    if project_id is not None:
        if not auth_context.project_scope.grants_all_org_projects:
            if project_id not in auth_context.project_scope.project_ids:
                return None, True
        return {project_id}, False
    if not auth_context.project_scope.grants_all_org_projects:
        if not auth_context.project_scope.project_ids:
            return None, True
        return auth_context.project_scope.project_ids, False
    return None, False


@router.get("/daily-reports")
async def list_daily_reports(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    status: str | None = None,
    category: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied:
        return {"items": [], "total": 0}

    repo = PostgresDprRepository(conn)
    items, total = await repo.list_reports(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        site_id=site_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/site-days")
async def list_site_days(
    report_date: datetime.date = Query(alias="date"),
    project_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Every active site's working day for one date (BE-08): status
    (draft = collecting, needs_details, ready, in_review = with engineer,
    approved = confirmed, published = sent) and what is missing."""
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied:
        return {"items": []}

    repo = PostgresDprRepository(conn)
    items = await repo.list_site_days(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        report_date=report_date,
    )
    return {"items": items}


@router.get("/daily-reports/{report_id}")
async def get_daily_report_detail(
    report_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = PostgresDprRepository(conn)
    report = await repo.get_report(
        organization_id=auth_context.organization_id,
        report_id=report_id,
    )
    if not report:
        raise HTTPException(status_code=404, detail="Daily report not found")
    return report


@router.post("/daily-reports")
async def create_daily_report(
    req: CreateDprRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = PostgresDprRepository(conn)
    created = await repo.create_report(
        organization_id=auth_context.organization_id,
        user_id=auth_context.user_id,
        payload=req.model_dump(),
    )
    return created


@router.post("/daily-reports/{report_id}/submit-for-review")
async def submit_daily_report_for_review(
    report_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """DRAFT -> IN_REVIEW."""
    repo = PostgresDprRepository(conn)
    success = await repo.submit_for_review(
        organization_id=auth_context.organization_id,
        report_id=report_id,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Report not found or not in DRAFT status")
    return {"status": "success"}


@router.post("/daily-reports/{report_id}/approve")
async def approve_daily_report(
    report_id: uuid.UUID,
    req: ApproveDprRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = PostgresDprRepository(conn)
    success = await repo.approve_report(
        organization_id=auth_context.organization_id,
        user_id=auth_context.user_id,
        report_id=report_id,
        notes=req.notes,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Report not found or already approved")
    return {"status": "success"}


@router.post("/daily-reports/{report_id}/publish")
async def publish_daily_report(
    report_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """APPROVED -> PUBLISHED."""
    repo = PostgresDprRepository(conn)
    success = await repo.publish_report(
        organization_id=auth_context.organization_id,
        report_id=report_id,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Report not found or not in APPROVED status")
    return {"status": "success"}


@router.post("/daily-reports/{report_id}/revise")
async def revise_daily_report(
    report_id: uuid.UUID,
    req: ReviseDprRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Correct an already APPROVED/PUBLISHED report: re-assembles the
    payload from what's actually recorded now (same composition
    create_version uses) and inserts it as a new version superseding the
    current one, with a stated `revision_reason`. Status resets to DRAFT so
    the correction goes back through submit-for-review/approve/publish.

    Works for both SITE reports (re-assembled from current activities/
    issues/labour/materials) and PROJECT roll-ups (re-assembled from
    whichever SITE versions are current now, ADR-D9/P8 -- a site whose own
    report changed since the roll-up was generated is what a project-level
    revision exists to pick up).

    404s for a report with no live data to re-assemble from at all -- the
    manual-entry path (POST /dpr/daily-reports with a hand-typed payload),
    which never gets composed from real records.
    """
    if not req.revision_reason or not req.revision_reason.strip():
        raise HTTPException(status_code=400, detail="revision_reason is required")

    repo = PostgresDprRepository(conn)
    scope = await repo.get_report_scope(
        organization_id=auth_context.organization_id, report_id=report_id
    )
    if scope is None:
        raise HTTPException(status_code=404, detail="Daily report not found")

    sources: list[tuple[uuid.UUID, uuid.UUID | None]] | None = None
    if scope["level"] == "SITE" and scope["site_id"] is not None:
        payload = await repo.assemble_site_report_payload(
            organization_id=auth_context.organization_id,
            project_id=scope["project_id"],
            site_id=scope["site_id"],
            report_date=scope["report_date"],
        )
    elif scope["level"] == "PROJECT":
        payload, sources = await repo.assemble_project_report_payload(
            organization_id=auth_context.organization_id,
            project_id=scope["project_id"],
            report_date=scope["report_date"],
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="Only a generated site-level or project-level report can be revised",
        )

    try:
        version = await repo.revise_version(
            daily_report_id=report_id,
            payload=payload,
            narrative_summary=req.narrative_summary,
            revision_reason=req.revision_reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if sources is not None:
        await repo.record_project_sources(project_version_id=version["id"], sources=sources)

    return {"status": "success", **{k: str(v) if v is not None else v for k, v in version.items()}}


@router.get("/daily-reports/{report_id}/pdf")
async def get_daily_report_pdf(
    report_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
):
    """Serve one DPR as a downloadable PDF.

    If the nightly cron (runtime/render_pending_dpr_pdfs.py) has already
    rendered this version, that polished Playwright/Jinja artifact is
    fetched from object storage and returned as-is (best fidelity, matches
    what WhatsApp sees). Otherwise a plain-tabular PDF is rendered on the
    spot from the same payload via fpdf2 (see domains/dpr/pdf.py) so the
    dashboard never has to show "come back later" for a report that has a
    real payload but hasn't been picked up by the cron yet.

    404s (not 200-with-empty-body) for a report with no current version at
    all -- the manual-entry creation path (POST /dpr/daily-reports with no
    activities behind it) has nothing real to render.
    """
    repo = PostgresDprRepository(conn)
    report = await repo.get_report_for_pdf(
        organization_id=auth_context.organization_id, report_id=report_id
    )
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="This report has no generated content yet (no activities recorded, or it "
            "was created manually without a payload).",
        )

    filename = f"{report['code'] or 'DPR'}.pdf"

    if report["rendered_object_key"]:
        stored = await object_storage.get_object(report["rendered_object_key"])
        pdf_bytes = stored.data
    else:
        payload = report["payload"]
        if isinstance(payload, str):
            import json

            payload = json.loads(payload)
        pdf_bytes = render_dpr_pdf_bytes(
            code=report["code"],
            report_date=report["report_date"],
            project_name=report["project_name"],
            site_name=report["site_name"],
            workflow_status=report["workflow_status"],
            payload=payload,
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
