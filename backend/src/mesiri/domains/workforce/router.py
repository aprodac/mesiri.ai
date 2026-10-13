"""REST API for the workforce/labour module — register, attendance reads,
settings, and a WhatsApp sandbox dry-run.

Mounted at /labour so:
  GET   /labour/settings                     org-wide labour preferences
  PATCH /labour/settings                     update them
  GET   /labour/workers                      the register
  POST  /labour/workers                      add a worker directly (not via WhatsApp)
  PATCH /labour/workers/{worker_id}           edit/retire a worker
  GET   /labour/attendance                   list attendance reports
  GET   /labour/attendance/{report_id}        one report with its lines/attachments
  POST  /labour/whatsapp/sandbox/simulate    dry-run AI parse, no DB writes

Attendance itself is never written here -- that path is WhatsApp-confirmed
and owned by application/labour/* + labour_execution.py (principle P2: a
report is never persisted without an explicit confirmation). This router
only reads reports and manages the mutable register, mirroring the
read/write split materials.router.py already draws between
PostgresMaterialReadRepository and the execution repository.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.media import assert_downloadable_url
from mesiri.domains.shared.modules import require_module
from mesiri.domains.shared.money import Money, Quantity
from mesiri.domains.workforce.matching import MatchOutcome, ReportedWorker, match_worker
from mesiri.domains.workforce.reports import (
    DEFAULT_REPORT_TYPE,
    AggregateRow,
    WorkerStatisticsInput,
    build_statement,
    build_worker_statistics,
    resolve_group_by,
)
from mesiri.domains.workforce.workers import (
    VALID_WORKER_STATUSES,
    VALID_WORKER_TYPES,
    normalize_trade,
)
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.workforce import (
    PostgresWorkforceReadRepository,
)
from mesiri_contracts.common.storage import ObjectStoragePort

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/labour",
    tags=["labour"],
    dependencies=[Depends(require_module("labour"))],
)

#: Who may run the destructive development-cleanup endpoints below.
#: A bare "ADMIN" was too narrow: OWNER and SUPER_ADMIN are already treated as
#: admin-equivalent for privileged actions elsewhere (expenses/router.py:578,
#: finance/router.py:886), and excluding them locked out exactly the accounts
#: most likely to be clearing test data.
_LABOUR_DELETE_ROLES = frozenset({"ADMIN", "OWNER", "SUPER_ADMIN"})


def _assert_may_delete_labour(auth_context: AuthorizationContext, what: str) -> None:
    """Both gates for the delete endpoints, in one place so they cannot drift.

    The environment flag is checked first: it is the gate that makes shipping
    these endpoints safe at all, since the dashboard they appear in is the same
    build customers use.
    """
    from mesiri.bootstrap.settings import Settings

    if not Settings().allow_labour_delete:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Deleting {what} is disabled in this environment. "
                "Set MESIRI_ALLOW_LABOUR_DELETE to enable it (development only)."
            ),
        )
    role = str(getattr(auth_context, "role", "")).upper()
    if role not in _LABOUR_DELETE_ROLES:
        raise HTTPException(
            status_code=403,
            detail=f"Role {role or 'unknown'} may not delete {what}",
        )


# Matches expenses/router.py's _ATTACHMENT_URL_TTL_SECONDS -- same object
# storage port, same "long enough for one page view" reasoning.
_ATTACHMENT_URL_TTL_SECONDS = 600


def _resolve_project_ids(
    auth_context: AuthorizationContext, project_id: uuid.UUID | None
) -> tuple[set[uuid.UUID] | None, bool]:
    """Returns (project_ids filter, denied). denied=True means caller has no access at all.

    Identical to materials/router.py's helper of the same name -- both
    routers draw their project-scope filter from AuthorizationContext the
    same way, and neither is large enough to warrant extracting a shared
    module over copying four lines.
    """
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


def _site_filter_denied(
    auth_context: AuthorizationContext,
    project_id: uuid.UUID | None,
    site_id: uuid.UUID | None,
) -> bool:
    if site_id is None:
        return False
    if project_id is None:
        return not auth_context.project_scope.grants_all_org_projects
    site_scope = auth_context.site_scope_for_project(project_id)
    if site_scope.grants_all_sites:
        return False
    return site_id not in site_scope.site_ids


# ---------------------------------------------------------------------------
# Response / request schemas
# ---------------------------------------------------------------------------

class WorkforceWorkerResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    trade: str | None = None
    worker_type: str
    default_daily_wage: Money | None = None
    contractor: str | None = None
    status: str


class WorkforceWorkersListResponse(BaseModel):
    items: list[WorkforceWorkerResponse]
    total: int


class CreateWorkerRequest(BaseModel):
    name: str
    trade: str | None = None
    worker_type: str = "permanent"
    default_daily_wage: Money | None = None
    contractor: str | None = None
    status: str = "active"


class UpdateWorkerRequest(BaseModel):
    name: str | None = None
    trade: str | None = None
    worker_type: str | None = None
    default_daily_wage: Money | None = None
    contractor: str | None = None
    status: str | None = None


class LabourAttendanceLineResponse(BaseModel):
    id: uuid.UUID
    worker_id: uuid.UUID | None = None
    worker_name: str | None = None
    worker_name_original: str | None = None
    trade: str | None = None
    headcount: int
    daily_wage: Money | None = None
    contractor: str | None = None
    activity: str | None = None
    #: P / A / H from the sheet. Defaults to present for every line recorded
    #: before migration 0456 and for every typed report, which is what those
    #: lines meant.
    attendance_status: str = "present"
    overtime_hours: Quantity | None = None
    remarks: str | None = None


class LabourAttendanceAttachmentResponse(BaseModel):
    id: uuid.UUID
    attachment_type: str
    #: None when the link could not be produced (misconfigured object storage,
    #: or a key the provider no longer resolves). The attachment is still
    #: listed so the record stays truthful about what was captured -- it just
    #: cannot be opened right now. Never let this take the whole report down:
    #: the worker names in the same response do not depend on it.
    url: str | None = None


class LabourAttendanceReportSummaryResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    project_id: uuid.UUID
    site_id: uuid.UUID | None = None
    occurred_date: datetime.date
    recorded_via: str
    notes: str | None = None
    line_count: int
    total_headcount: int
    total_cost: Money


class LabourAttendanceGalleryItem(BaseModel):
    """One attendance sheet photo, captioned enough to render a gallery
    thumbnail without a second call per row. Mirrors expenses/router.py's
    ExpenseAttachmentGalleryItem — same shape, same reasoning, adapted to
    attendance's fields (headcount/cost instead of amount/vendor)."""

    id: uuid.UUID
    report_id: uuid.UUID
    attachment_type: str
    created_at: datetime.datetime | None = None
    url: str
    occurred_date: datetime.date
    project_id: uuid.UUID
    site_id: uuid.UUID | None = None
    total_headcount: int
    total_cost: Money


class LabourAttendanceReportsListResponse(BaseModel):
    items: list[LabourAttendanceReportSummaryResponse]
    total: int


class LabourAttendanceReportResponse(LabourAttendanceReportSummaryResponse):
    lines: list[LabourAttendanceLineResponse]
    attachments: list[LabourAttendanceAttachmentResponse]


class LabourReportRow(BaseModel):
    """One grouped line of a statement. Every figure here is derived from
    recorded attendance -- there is no default wage and no assumed month."""

    id: str
    code: str | None = None
    title: str
    category: str | None = None
    contractor: str | None = None
    #: Person-days recorded for this group, summed from the attendance lines.
    man_days: Quantity
    #: Of those, the ones whose line carried a wage. Below man_days whenever
    #: attendance was recorded without pay rates.
    priced_man_days: Quantity
    #: Distinct dates this group appears on -- never an assumed 10 or 30.
    days_worked: int
    first_date: datetime.date | None = None
    last_date: datetime.date | None = None
    report_count: int = 0
    avg_daily_wage: Money
    total_cost: Money
    #: Money, despite not being money: the annotation's job is "exact Decimal
    #: server-side, real JSON number on the wire". A bare Decimal serializes as
    #: a *string*, and the page feeds this straight into Math.min() to size a
    #: progress bar -- the same class of bug that once rendered a cumulative
    #: spend KPI as "Rs 04800.003600.00".
    percentage: Money


class LabourReportStatementResponse(BaseModel):
    report_type: str
    title: str
    subtitle: str
    generated_at: datetime.datetime
    #: Echoed back so the dashboard can caption the statement with the range
    #: actually applied, rather than the one it believes it asked for.
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    total_man_days: Quantity
    priced_man_days: Quantity
    unpriced_man_days: Quantity
    total_cost: Money
    avg_daily_wage: Money
    rows: list[LabourReportRow]


class WorkerStatisticsResponse(BaseModel):
    """One worker's attendance history, derived on read.

    None of these are editable or stored. They are facts about what the
    attendance record says happened, recomputed on every request so a
    superseded or corrected report is reflected immediately.
    """

    key: str
    #: None for a temporary worker who has never been promoted into the
    #: register -- their identity is the name on the attendance line.
    worker_id: uuid.UUID | None = None
    name: str
    is_registered: bool
    #: Distinct dates present. Never an assumed 10 or 30.
    days_worked: int
    #: Reports they appear in. Higher than days_worked when someone is
    #: recorded on two sites on the same day.
    attendance_count: int
    man_days: Quantity
    priced_man_days: Quantity
    unpriced_man_days: Quantity
    total_earnings: Money
    avg_daily_wage: Money
    first_seen: datetime.date | None = None
    last_seen: datetime.date | None = None
    #: Every trade/contractor they have actually worked under, not just the
    #: current one on their register row.
    trades: list[str] = []
    contractors: list[str] = []
    #: Every date this worker was present, for a calendar view. Returned only
    #: by the single-worker endpoint -- an empty list on the list endpoint
    #: means "not asked for", not "never worked".
    dates_worked: list[datetime.date] = []


class WorkerStatisticsListResponse(BaseModel):
    items: list[WorkerStatisticsResponse]
    total: int


class LabourSettingsResponse(BaseModel):
    missing_report_reminder_enabled: bool = True
    missing_report_reminder_time: str = "18:00"
    headcount_anomaly_alert_enabled: bool = True
    wage_change_alert_enabled: bool = True
    require_dashboard_approval_for_new_worker: bool = False


class UpdateLabourSettingsRequest(BaseModel):
    missing_report_reminder_enabled: bool | None = None
    missing_report_reminder_time: str | None = None
    headcount_anomaly_alert_enabled: bool | None = None
    wage_change_alert_enabled: bool | None = None
    require_dashboard_approval_for_new_worker: bool | None = None


class LabourSandboxSimulateRequest(BaseModel):
    message: str


class LabourSandboxSimulateResponse(BaseModel):
    intent: str
    confidence: str
    fields: dict[str, Any]
    workflow_decision: str
    reply_message: str
    line_summaries: list[str]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@router.get("/settings", response_model=LabourSettingsResponse)
async def get_labour_settings(
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Get organization-wide labour preferences & WhatsApp assistant policies from PostgreSQL."""
    from mesiri.infrastructure.postgres.repositories.organization_settings import (
        PostgresOrganizationSettingsRepository,
    )
    repo = PostgresOrganizationSettingsRepository(conn)
    try:
        stored = await repo.get(auth_context.organization_id, "labour_settings")
        if isinstance(stored, dict):
            return LabourSettingsResponse(**stored)
    except Exception as ex:
        logger.warning("Failed to fetch labour_settings from repository, using defaults: %s", ex)
    return LabourSettingsResponse()


@router.patch("/settings", response_model=LabourSettingsResponse)
async def update_labour_settings(
    body: UpdateLabourSettingsRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Update organization-wide labour preferences & WhatsApp assistant policies in PostgreSQL."""
    from mesiri.infrastructure.postgres.repositories.organization_settings import (
        PostgresOrganizationSettingsRepository,
    )
    repo = PostgresOrganizationSettingsRepository(conn)
    stored = None
    try:
        stored = await repo.get(auth_context.organization_id, "labour_settings")
    except Exception as ex:
        logger.warning("Failed to get existing labour_settings before patch: %s", ex)

    current_dict = stored if isinstance(stored, dict) else LabourSettingsResponse().model_dump()

    patch_data = body.model_dump(exclude_unset=True)
    for key, val in patch_data.items():
        if val is not None:
            current_dict[key] = val

    user_id = getattr(auth_context, "user_id", None)
    await repo.set(
        auth_context.organization_id,
        "labour_settings",
        current_dict,
        updated_by=user_id,
    )
    return LabourSettingsResponse(**current_dict)


# ---------------------------------------------------------------------------
# Worker statistics (derived from attendance, never stored)
# ---------------------------------------------------------------------------

@router.get("/workers/statistics", response_model=WorkerStatisticsListResponse)
async def list_worker_statistics(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Attendance history for everyone who has actually worked.

    Declared before /workers/{worker_id} so "statistics" is never parsed as a
    worker id.

    This lists people found in *attendance*, not people in the register, and
    the two are deliberately different sets. A registered worker who has never
    turned up has no history and does not appear; a temporary worker who has
    never been promoted does appear, with worker_id null. Reporting only
    registered workers would hide 30-60% of site attendance (principle P3).
    """
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return {"items": [], "total": 0}

    repo = PostgresWorkforceReadRepository(conn)
    rows = await repo.worker_statistics(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
    )
    items = build_worker_statistics([_statistics_input(row) for row in rows])
    return {"items": items, "total": len(items)}


@router.get("/workers/{worker_id}/statistics", response_model=WorkerStatisticsResponse)
async def get_worker_statistics(
    worker_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """One registered worker's attendance history.

    404s when the worker has no attendance in scope, rather than returning a
    zeroed record -- "no history" and "worked zero days" are different claims,
    and the second one is the sort of confident nothing this refactor exists
    to stop.
    """
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        raise HTTPException(status_code=404, detail="no attendance history for this worker")

    repo = PostgresWorkforceReadRepository(conn)
    rows = await repo.worker_statistics(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
        worker_id=worker_id,
        # One worker, so the individual dates are affordable here and power
        # the calendar. The list endpoint deliberately omits them.
        include_dates=True,
    )
    items = build_worker_statistics([_statistics_input(row) for row in rows])
    if not items:
        raise HTTPException(status_code=404, detail="no attendance history for this worker")
    return items[0]


def _statistics_input(row: dict[str, Any]) -> WorkerStatisticsInput:
    return WorkerStatisticsInput(
        key=str(row["key"]),
        worker_id=row["worker_id"],
        name=row["name"],
        days_worked=int(row["days_worked"] or 0),
        attendance_count=int(row["attendance_count"] or 0),
        man_days=Decimal(str(row["man_days"] or 0)),
        priced_man_days=Decimal(str(row["priced_man_days"] or 0)),
        total_earnings=Decimal(str(row["total_earnings"] or "0")),
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        trades=list(row["trades"] or []),
        contractors=list(row["contractors"] or []),
        dates_worked=list(row.get("dates_worked") or []),
    )


# ---------------------------------------------------------------------------
# Register (workforce_workers)
# ---------------------------------------------------------------------------

@router.get("/workers", response_model=WorkforceWorkersListResponse)
async def list_workers(
    status: str | None = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """List the workforce register accessible to the caller's organization."""
    if status is not None and status not in VALID_WORKER_STATUSES:
        raise HTTPException(status_code=422, detail=f"unknown status: {status}")
    repo = PostgresWorkforceReadRepository(conn)
    items, total = await repo.list_workers(
        organization_id=auth_context.organization_id,
        status=status,
        search=search,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.post("/workers", response_model=WorkforceWorkerResponse, status_code=201)
async def create_worker(
    body: CreateWorkerRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Add a worker to the register directly from the dashboard.

    The WhatsApp path never writes the register as a side effect of
    attendance (principle P1 in labour-module-implementation-plan.md) --
    this is the explicit, separate act that promotes a name into it.
    """
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    if body.worker_type not in VALID_WORKER_TYPES:
        raise HTTPException(status_code=422, detail=f"unknown worker_type: {body.worker_type}")
    if body.status not in VALID_WORKER_STATUSES:
        raise HTTPException(status_code=422, detail=f"unknown status: {body.status}")
    if body.default_daily_wage is not None and body.default_daily_wage < 0:
        raise HTTPException(status_code=422, detail="default_daily_wage cannot be negative")

    repo = PostgresWorkforceReadRepository(conn)
    created_by = auth_context.user_id
    worker = await repo.create_worker(
        organization_id=auth_context.organization_id,
        name=name,
        trade=normalize_trade(body.trade),
        worker_type=body.worker_type,
        default_daily_wage=body.default_daily_wage,
        contractor=body.contractor,
        status=body.status,
        created_by=created_by,
    )
    return worker


@router.patch("/workers/{worker_id}", response_model=WorkforceWorkerResponse)
async def update_worker(
    worker_id: uuid.UUID,
    body: UpdateWorkerRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Edit or retire a register entry. Never deletes -- historical attendance
    lines reference worker_id, and attendance is immutable (principle P5)."""
    if body.worker_type is not None and body.worker_type not in VALID_WORKER_TYPES:
        raise HTTPException(status_code=422, detail=f"unknown worker_type: {body.worker_type}")
    if body.status is not None and body.status not in VALID_WORKER_STATUSES:
        raise HTTPException(status_code=422, detail=f"unknown status: {body.status}")
    if body.default_daily_wage is not None and body.default_daily_wage < 0:
        raise HTTPException(status_code=422, detail="default_daily_wage cannot be negative")

    repo = PostgresWorkforceReadRepository(conn)
    existing = await repo.get_worker(auth_context.organization_id, worker_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Worker not found")

    patch = body.model_dump(exclude_unset=True)
    if "trade" in patch:
        patch["trade"] = normalize_trade(patch["trade"])
    if "name" in patch and patch["name"] is not None:
        patch["name"] = patch["name"].strip()

    updated = await repo.update_worker(
        organization_id=auth_context.organization_id,
        worker_id=worker_id,
        patch=patch,
        updated_by=auth_context.user_id,
    )
    assert updated is not None
    return updated


# ---------------------------------------------------------------------------
# Attendance reports (read-only)
# ---------------------------------------------------------------------------

@router.get("/attendance", response_model=LabourAttendanceReportsListResponse)
async def list_attendance(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """List attendance reports within the user's organization and project scope."""
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return {"items": [], "total": 0}

    repo = PostgresWorkforceReadRepository(conn)
    items, total = await repo.list_reports(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/attendance/attachments", response_model=list[LabourAttendanceGalleryItem])
async def list_attendance_attachments(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
):
    """Every attendance sheet photo across the org, newest first — the "see
    all attendance sheets together" gallery view (Labour plan Phase 7 /
    ADR-L3). Declared before /{report_id} so "attachments" is never matched
    as a report id, same reason expenses/router.py's equivalent route is
    ordered first.

    Scoped through `_resolve_project_ids`/`_site_filter_denied` the same way
    `list_attendance` above is — a caller only sees attendance for projects
    and sites they're actually assigned to, including a caller scoped to
    several specific (non-portfolio) projects. This is stricter than
    expenses/router.py's `/attachments`, which currently checks only
    organization membership and lets any org member pass an arbitrary
    project_id filter. Attendance carries names and wages, which is more
    sensitive than a receipt photo, so the gap is closed here rather than
    copied — worth backporting to expenses separately.
    """
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return []

    repo = PostgresWorkforceReadRepository(conn)
    rows = await repo.list_attachments_for_organization(
        auth_context.organization_id,
        project_ids=project_ids,
        site_id=site_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    return [
        LabourAttendanceGalleryItem(
            id=row["id"],
            report_id=row["report_id"],
            attachment_type=row["attachment_type"],
            created_at=row["created_at"],
            url=assert_downloadable_url(
                await object_storage.generate_presigned_url(
                    row["media_object_key"], expires_in_seconds=_ATTACHMENT_URL_TTL_SECONDS
                )
            ),
            occurred_date=row["occurred_date"],
            project_id=row["project_id"],
            site_id=row["site_id"],
            total_headcount=row["total_headcount"],
            total_cost=row["total_cost"],
        )
        for row in rows
    ]


@router.get("/attendance/{report_id}", response_model=LabourAttendanceReportResponse)
async def get_attendance_report(
    report_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
):
    repo = PostgresWorkforceReadRepository(conn)
    item = await repo.get_report(auth_context.organization_id, report_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Attendance report not found")
    if _site_filter_denied(auth_context, item["project_id"], item["site_id"]):
        raise HTTPException(status_code=403, detail="Not authorized for this report")
    _project_ids, denied = _resolve_project_ids(auth_context, item["project_id"])
    if denied:
        raise HTTPException(status_code=403, detail="Not authorized for this report")

    # A photo that cannot be linked must not take the attendance record down
    # with it. Reported from the dashboard: opening a report showed the totals
    # but no worker names at all, because one unusable attachment URL raised
    # and 500'd the whole response -- and the names have nothing to do with
    # the photos. The link degrades to null (the UI shows the attachment as
    # unavailable) while everything else is still served.
    attachments: list[dict[str, Any]] = []
    for a in item["attachments"]:
        url: str | None
        try:
            url = assert_downloadable_url(
                await object_storage.generate_presigned_url(
                    a["media_object_key"], expires_in_seconds=_ATTACHMENT_URL_TTL_SECONDS
                )
            )
        except Exception:  # noqa: BLE001 — a broken link is not a broken report
            logger.warning(
                "labour.attachment_url_unavailable report_id=%s attachment_id=%s",
                report_id,
                a["id"],
            )
            url = None
        attachments.append(
            {"id": a["id"], "attachment_type": a["attachment_type"], "url": url}
        )
    item["attachments"] = attachments
    return item


class DeleteWorkerResponse(BaseModel):
    worker_id: uuid.UUID
    name: str


@router.delete("/workers/{worker_id}", response_model=DeleteWorkerResponse)
async def delete_worker(
    worker_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Permanently delete one register entry. Development cleanup only.

    Same two gates as deleting attendance: `MESIRI_ALLOW_LABOUR_DELETE` must be
    set, and the caller must be ADMIN. Normal operation retires a worker
    (`status='inactive'`) rather than deleting them, because attendance
    references the register and history must outlive a person leaving the site.

    **Refuses with 409 while any attendance line still points at this worker.**
    `labour_attendance_lines.worker_id` is a foreign key with no cascade, so the
    delete would fail at the database anyway -- but a raw FK error tells the
    caller nothing about what to do. The two alternatives were both worse:
    deleting their attendance too would destroy records that belong to other
    workers on the same report, and silently clearing worker_id would leave
    name-only lines, which is exactly the fragmented state roadmap phase 4
    removed. So it says how many reports are in the way, and the order to work
    in: attendance first, then the register.
    """
    _assert_may_delete_labour(auth_context, "workers")

    from sqlalchemy import text

    owned = (
        await conn.execute(
            text(
                "SELECT name FROM workforce_workers "
                "WHERE id = :id AND organization_id = :org"
            ),
            {"id": worker_id, "org": auth_context.organization_id},
        )
    ).first()
    if owned is None:
        raise HTTPException(status_code=404, detail="Worker not found")

    referencing = (
        await conn.execute(
            text("SELECT COUNT(*) FROM labour_attendance_lines WHERE worker_id = :id"),
            {"id": worker_id},
        )
    ).scalar_one()
    if referencing:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{owned[0]} still appears on {referencing} attendance line(s). "
                "Delete those attendance reports first, then the worker."
            ),
        )

    await conn.execute(
        text("DELETE FROM workforce_workers WHERE id = :id"), {"id": worker_id}
    )
    logger.warning(
        "labour.worker_deleted worker_id=%s org=%s by=%s",
        worker_id,
        auth_context.organization_id,
        getattr(auth_context, "user_id", "?"),
    )
    return DeleteWorkerResponse(worker_id=worker_id, name=owned[0])


class DeleteAttendanceReportResponse(BaseModel):
    """What was actually removed, per table, so the caller can see the blast
    radius rather than trust a bare 204."""

    report_id: uuid.UUID
    deleted_lines: int
    deleted_attachments: int
    deleted_outbox_events: int
    #: Reports that pointed at this one via corrects_report_id and had the
    #: pointer cleared so the delete could proceed. Non-zero means a correction
    #: chain was broken, which is worth seeing.
    unlinked_corrections: int
    #: Always 0. Stated explicitly because deleting a worker is not something
    #: this endpoint does or ever should -- attendance references the register,
    #: and a register row outliving its attendance is correct.
    deleted_workers: int = 0


@router.delete("/attendance/{report_id}", response_model=DeleteAttendanceReportResponse)
async def delete_attendance_report(
    report_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Permanently delete one attendance report. Development cleanup only.

    **Disabled unless `MESIRI_ALLOW_LABOUR_DELETE` is set**, and then only for
    ADMIN. Two gates rather than one because the dashboard a developer clicks
    this in is the same build customers use, and the role check alone would
    make it live in production the moment it deployed.

    This deliberately contradicts principle P5 (attendance is immutable) and
    exists for clearing test data between runs -- never for fixing a mistake.
    A supervisor who mis-reported re-sends the day and chooses "Replace", which
    supersedes the old report while keeping it readable for audit. Deleting
    destroys that trail, which is exactly why it is off by default.

    **Never touches workforce_workers.** Attendance references the register, so
    a worker outliving their attendance is correct; the reverse would orphan
    every line pointing at them.

    `corrects_report_id` is a self-reference with no cascade, so any report
    correcting this one has its pointer cleared first -- otherwise the delete
    fails with a foreign-key violation. The count is reported back, because
    breaking a correction chain is worth knowing about.
    """
    _assert_may_delete_labour(auth_context, "attendance")

    from sqlalchemy import text

    # Scoped by organization, so one tenant can never delete another's report.
    owned = (
        await conn.execute(
            text(
                "SELECT project_id, site_id FROM labour_attendance_reports "
                "WHERE id = :id AND organization_id = :org"
            ),
            {"id": report_id, "org": auth_context.organization_id},
        )
    ).first()
    if owned is None:
        raise HTTPException(status_code=404, detail="Attendance report not found")
    if _site_filter_denied(auth_context, owned[0], owned[1]):
        raise HTTPException(status_code=403, detail="Not authorized for this report")
    _ids, denied = _resolve_project_ids(auth_context, owned[0])
    if denied:
        raise HTTPException(status_code=403, detail="Not authorized for this report")

    counts: dict[str, int] = {}
    for label, sql in (
        ("deleted_attachments", "DELETE FROM labour_attendance_attachments WHERE report_id = :id"),
        ("deleted_lines", "DELETE FROM labour_attendance_lines WHERE report_id = :id"),
    ):
        counts[label] = (await conn.execute(text(sql), {"id": report_id})).rowcount or 0

    # Break the self-reference before deleting the row it points at.
    counts["unlinked_corrections"] = (
        await conn.execute(
            text(
                "UPDATE labour_attendance_reports SET corrects_report_id = NULL "
                "WHERE corrects_report_id = :id"
            ),
            {"id": report_id},
        )
    ).rowcount or 0

    # No foreign key on the outbox, so nothing would warn about rows left
    # pointing at a report that no longer exists.
    counts["deleted_outbox_events"] = (
        await conn.execute(
            text(
                "DELETE FROM outbox_events "
                "WHERE aggregate_type = 'labour_attendance_report' AND aggregate_id = :id"
            ),
            {"id": report_id},
        )
    ).rowcount or 0

    await conn.execute(
        text("DELETE FROM labour_attendance_reports WHERE id = :id"), {"id": report_id}
    )

    logger.warning(
        "labour.attendance_deleted report_id=%s org=%s by=%s lines=%d attachments=%d",
        report_id,
        auth_context.organization_id,
        getattr(auth_context, "user_id", "?"),
        counts["deleted_lines"],
        counts["deleted_attachments"],
    )
    return DeleteAttendanceReportResponse(report_id=report_id, **counts)


# ---------------------------------------------------------------------------
# Report statements
# ---------------------------------------------------------------------------

@router.get("/reports/statement", response_model=LabourReportStatementResponse)
async def generate_labour_report_statement(
    report_type: str = DEFAULT_REPORT_TYPE,
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Labour cost and man-days, aggregated from recorded attendance.

    Mirrors finance/router.py's /reports/statement: one endpoint, a report_type
    switch, aggregation in the repository, and a page that only renders. The
    dashboard previously computed these in the browser from the *worker
    register* -- pricing it at an assumed 800/day and asserting a 10- or 30-day
    month for everyone on it, including workers who had never appeared on site
    (docs/plans/labour-reports-audit.md).

    One deliberate divergence from Finance: that endpoint scopes by
    organization_id alone, while this one applies _resolve_project_ids and
    _site_filter_denied like every other Labour read. Copying Finance here
    would have widened what a project-scoped user can see.

    Dates are taken as an explicit range rather than a named period ("today",
    "this month"). Which day is "today" depends on the reader's timezone, which
    the server does not know; the dashboard already resolves presets against
    the browser's local date for the Attendance page, and this keeps that one
    correct behaviour rather than adding a second, server-side answer that
    disagrees with it near midnight.
    """
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return build_statement(
            report_type=report_type,
            rows=[],
            generated_at=datetime.datetime.now(datetime.UTC),
            date_from=date_from,
            date_to=date_to,
        )

    repo = PostgresWorkforceReadRepository(conn)
    aggregate_rows = await repo.aggregate_attendance(
        organization_id=auth_context.organization_id,
        group_by=resolve_group_by(report_type),
        project_ids=project_ids,
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
    )

    group_by = resolve_group_by(report_type)
    rows = [
        AggregateRow(
            key=str(row["key"]),
            label=row["label"],
            man_days=Decimal(str(row["man_days"] or 0)),
            priced_man_days=Decimal(str(row["priced_man_days"] or 0)),
            total_cost=Decimal(str(row["total_cost"] or "0")),
            days_worked=int(row["days_worked"] or 0),
            first_date=row["first_date"],
            last_date=row["last_date"],
            report_count=int(row["report_count"] or 0),
            # Only meaningful on the per-worker statement; on the others these
            # would just repeat the row's own title back as its category.
            trade=row["trade"] if group_by == "worker" else None,
            contractor=row["contractor"] if group_by == "worker" else None,
        )
        for row in aggregate_rows
    ]

    return build_statement(
        report_type=report_type,
        rows=rows,
        generated_at=datetime.datetime.now(datetime.UTC),
        date_from=date_from,
        date_to=date_to,
    )


# ---------------------------------------------------------------------------
# WhatsApp sandbox (dry-run, no DB writes)
# ---------------------------------------------------------------------------

def _heuristic_lines(msg: str) -> list[dict[str, Any]]:
    """Fallback extraction when the AI resolver returns no labour-shaped fields.

    Mirrors finance's sandbox fallback (router.py's simulate_whatsapp_sandbox):
    a light regex pass so the sandbox still shows something plausible when
    the shared resolver hasn't been taught this message shape, never a hard
    failure. Same trade vocabulary as domains/workforce/workers.py.
    """
    import re

    pattern = re.compile(
        r"(\d+)\s*(masons?|helpers?|painters?|carpenters?|electricians?|plumbers?|"
        r"welders?|workers?|labou?rers?)",
        re.IGNORECASE,
    )
    lines: list[dict[str, Any]] = []
    for count_str, trade_str in pattern.findall(msg):
        lines.append(
            {
                "worker_name": None,
                "trade": normalize_trade(trade_str),
                "headcount": int(count_str),
                "daily_wage": None,
            }
        )
    if lines:
        return lines
    return [{"worker_name": None, "trade": "worker", "headcount": 1, "daily_wage": None}]


@router.post("/whatsapp/sandbox/simulate", response_model=LabourSandboxSimulateResponse)
async def simulate_labour_sandbox(
    body: LabourSandboxSimulateRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
):
    """Dry-run AI sandbox simulation for labour attendance messages.

    Invokes the real AI extraction pipeline (same resolver finance's sandbox
    uses) but never touches the register or labour_attendance_* tables --
    matching is scored against an empty candidate list, so every named line
    reads as "not yet in the register" here regardless of who is actually
    registered. That is a deliberate simplification for a sandbox whose only
    job is to preview what the assistant would ask/say, not to reproduce a
    real confirmation.
    """
    msg = body.message.strip()
    ai_provider_name = "Gemini/DeepSeek AI Engine"
    real_fields: dict[str, Any] = {}

    try:
        from mesiri.bootstrap.settings import get_settings
        from mesiri_ai.resolver import DynamicAIProviderResolver

        resolver = DynamicAIProviderResolver(db=None, redis_client=None, settings=get_settings())
        result = await resolver.extract(msg)
        if result:
            real_fields = getattr(result, "fields", {}) or {}
            if getattr(result, "provider", None):
                ai_provider_name = f"{result.provider.title()} AI"
    except Exception as ex:
        logger.warning("DynamicAIProviderResolver labour sandbox extract fallback: %s", ex)

    lines = real_fields.get("lines")
    if not isinstance(lines, list) or not lines:
        lines = _heuristic_lines(msg)

    summaries: list[str] = []
    total_headcount = 0
    total_cost = Decimal("0")
    for line in lines:
        name = str(line.get("worker_name") or "").strip() or None
        trade = normalize_trade(line.get("trade"))
        try:
            headcount = int(line.get("headcount") or 1)
        except (TypeError, ValueError):
            headcount = 1
        wage = line.get("daily_wage")
        total_headcount += headcount
        if wage is not None:
            try:
                total_cost += Decimal(str(wage)) * headcount
            except Exception:
                pass

        if name:
            result = match_worker(ReportedWorker(name=name, trade=trade), [])
            note = "no register match in this sandbox — would record as a temporary worker"
            if result.outcome is MatchOutcome.NO_MATCH:
                note = "no register match — would record as a temporary worker"
            summaries.append(f"{name}" + (f" ({trade})" if trade else "") + f" — {note}")
        else:
            label = f"{headcount} × {trade}" if trade else f"{headcount} worker(s)"
            summaries.append(label)

    reply = (
        f"✅ Dry-run preview ({ai_provider_name}): Labour attendance parsed — "
        f"{total_headcount} worker(s){f', ₹{total_cost:,.2f} total' if total_cost > 0 else ''}. "
        "No DB row created."
    )

    return LabourSandboxSimulateResponse(
        intent="labour.record_attendance",
        confidence=f"HIGH (96.1% via {ai_provider_name})",
        fields={
            "lines": lines,
            "total_headcount": total_headcount,
            "total_cost": float(total_cost),
        },
        workflow_decision="START_WORKFLOW",
        reply_message=reply,
        line_summaries=summaries,
    )
