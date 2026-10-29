"""REST API for the Progress (Daily Reporting) module.

Mounted at /progress so:
  GET    /progress/activities                        list activities
  GET    /progress/activities/{activity_id}           one activity with
                                                       quantities/progress
                                                       updates/attachments
  PATCH  /progress/activities/{activity_id}           correct header fields
  DELETE /progress/activities/{activity_id}           undo (soft delete)
  PATCH  /progress/activities/{id}/updates/{update_id} correct a quantity
  DELETE /progress/activities/{id}/updates/{update_id} undo a progress update
  GET    /progress/activities/{id}/corrections        the audit trail

A brand-new Activity/Progress Update is always WhatsApp-confirmed (plan
principle P2), owned by application/progress/* + progress_execution.py --
never created here. Correcting or undoing one already recorded IS written
here, dashboard-direct with no confirm step (ADR-D14/D15,
docs/execution/DAILY_REPORTING_PLAN.md), the same pattern Site Issues
below already use for their own dashboard-direct writes.
"""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.media import signed_media_url
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.progress import PostgresProgressReadRepository
from mesiri_contracts.common.storage import ObjectStoragePort

from .responses import (
    ActivitiesListResponse,
    ActivityCorrectionsListResponse,
    ActivityDetailResponse,
    CorrectActivityRequest,
    CorrectProgressUpdateRequest,
    CreateSiteIssueRequest,
    OperationsSettingsResponse,
    ResolveSiteIssueRequest,
    SiteIssueResponse,
    SiteIssuesListResponse,
    UpdateOperationsSettingsRequest,
    VoidActivityRequest,
    VoidProgressUpdateRequest,
    WontFixSiteIssueRequest,
)

router = APIRouter(
    prefix="/progress",
    tags=["progress"],
    dependencies=[Depends(require_module("dpr"))],
)



def _resolve_project_ids(
    auth_context: AuthorizationContext, project_id: uuid.UUID | None
) -> tuple[set[uuid.UUID] | None, bool]:
    """Returns (project_ids filter, denied). denied=True means caller has no
    access at all. Identical to materials/router.py and workforce/router.py's
    helper of the same name."""
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


@router.get("/activities", response_model=ActivitiesListResponse)
async def list_activities(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    status: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """List activities within the caller's organization and project scope."""
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return {"items": [], "total": 0}

    repo = PostgresProgressReadRepository(conn)
    items, total = await repo.list_activities(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/activities/{activity_id}", response_model=ActivityDetailResponse)
async def get_activity(
    activity_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = PostgresProgressReadRepository(conn)
    item = await repo.get_activity(auth_context.organization_id, activity_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    if _site_filter_denied(auth_context, item["project_id"], item["site_id"]):
        raise HTTPException(status_code=403, detail="Not authorized for this activity")
    _project_ids, denied = _resolve_project_ids(auth_context, item["project_id"])
    if denied:
        raise HTTPException(status_code=403, detail="Not authorized for this activity")

    return item


async def _authorized_activity_or_404(
    repo: PostgresProgressReadRepository, auth_context: AuthorizationContext, activity_id: uuid.UUID
) -> dict:
    """Shared existence + scope check every correction/undo endpoint below
    needs before touching anything -- mirrors get_activity's own checks."""
    item = await repo.get_activity(auth_context.organization_id, activity_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    if _site_filter_denied(auth_context, item["project_id"], item["site_id"]):
        raise HTTPException(status_code=403, detail="Not authorized for this activity")
    _project_ids, denied = _resolve_project_ids(auth_context, item["project_id"])
    if denied:
        raise HTTPException(status_code=403, detail="Not authorized for this activity")
    return item


@router.patch("/activities/{activity_id}", response_model=ActivityDetailResponse)
async def correct_activity(
    activity_id: uuid.UUID,
    payload: CorrectActivityRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Correct one or more Activity header fields (ADR-D14) -- work_type,
    location_id, contractor, narrative, activity_date. Allowed even once
    the day is part of an approved daily report; that report is revised
    instead of left silently wrong."""
    repo = PostgresProgressReadRepository(conn)
    await _authorized_activity_or_404(repo, auth_context, activity_id)

    changes = payload.model_dump(exclude_unset=True, exclude={"reason"})
    try:
        updated = await repo.correct_activity_fields(
            organization_id=auth_context.organization_id,
            activity_id=activity_id,
            changes=changes,
            reason=payload.reason,
            corrected_by_user_id=auth_context.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    return updated


@router.delete("/activities/{activity_id}")
async def void_activity(
    activity_id: uuid.UUID,
    payload: VoidActivityRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Undo an Activity entirely (ADR-D15) -- soft delete, refused once the
    day is part of an approved daily report (unlike correction)."""
    repo = PostgresProgressReadRepository(conn)
    await _authorized_activity_or_404(repo, auth_context, activity_id)

    rejection = await repo.void_activity(
        organization_id=auth_context.organization_id,
        activity_id=activity_id,
        reason=payload.reason,
        corrected_by_user_id=auth_context.user_id,
    )
    if rejection is not None:
        raise HTTPException(status_code=400, detail=rejection)
    return {"status": "success", "message": "Activity removed"}


@router.patch("/activities/{activity_id}/updates/{update_id}", response_model=ActivityDetailResponse)
async def correct_progress_update(
    activity_id: uuid.UUID,
    update_id: uuid.UUID,
    payload: CorrectProgressUpdateRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Correct a Progress Update's quantity/unit/narrative (ADR-D14) by
    appending a new row that supersedes this one -- the old row is never
    edited or deleted, so both remain visible in the activity's detail
    view. Returns the whole activity (the new update is now in its list)."""
    repo = PostgresProgressReadRepository(conn)
    await _authorized_activity_or_404(repo, auth_context, activity_id)

    changes = payload.model_dump(exclude_unset=True, exclude={"reason"})
    try:
        corrected = await repo.correct_progress_update(
            organization_id=auth_context.organization_id,
            update_id=update_id,
            changes=changes,
            reason=payload.reason,
            corrected_by_user_id=auth_context.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if corrected is None or corrected["activity_id"] != activity_id:
        raise HTTPException(status_code=404, detail="Progress update not found")

    updated_activity = await repo.get_activity(auth_context.organization_id, activity_id)
    return updated_activity


@router.delete("/activities/{activity_id}/updates/{update_id}")
async def void_progress_update(
    activity_id: uuid.UUID,
    update_id: uuid.UUID,
    payload: VoidProgressUpdateRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Undo a single Progress Update (ADR-D15) -- soft delete, refused once
    the day is part of an approved daily report."""
    repo = PostgresProgressReadRepository(conn)
    await _authorized_activity_or_404(repo, auth_context, activity_id)

    rejection = await repo.void_progress_update(
        organization_id=auth_context.organization_id,
        update_id=update_id,
        reason=payload.reason,
        corrected_by_user_id=auth_context.user_id,
    )
    if rejection is not None:
        status_code = 404 if rejection == "progress update not found" else 400
        raise HTTPException(status_code=status_code, detail=rejection)
    return {"status": "success", "message": "Progress update removed"}


@router.get("/activities/{activity_id}/corrections", response_model=ActivityCorrectionsListResponse)
async def list_activity_corrections(
    activity_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """The audit trail for one Activity (ADR-D14) -- every header
    correction, progress-update correction, and void, newest first."""
    repo = PostgresProgressReadRepository(conn)
    await _authorized_activity_or_404(repo, auth_context, activity_id)

    items = await repo.list_corrections(auth_context.organization_id, activity_id)
    return {"items": items}


@router.get("/issues", response_model=SiteIssuesListResponse)
async def list_issues(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    status: str | None = None,
    severity: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """List site issues within the caller's organization and project scope."""
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return {"items": [], "total": 0}

    repo = PostgresProgressReadRepository(conn)
    items, total = await repo.list_issues(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        site_id=site_id,
        status=status,
        severity=severity,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/issues/{issue_id}", response_model=SiteIssueResponse)
async def get_issue(
    issue_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = PostgresProgressReadRepository(conn)
    item = await repo.get_issue(auth_context.organization_id, issue_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if _site_filter_denied(auth_context, item["project_id"], item["site_id"]):
        raise HTTPException(status_code=403, detail="Not authorized for this issue")
    _project_ids, denied = _resolve_project_ids(auth_context, item["project_id"])
    if denied:
        raise HTTPException(status_code=403, detail="Not authorized for this issue")

    return item


@router.post("/issues", response_model=SiteIssueResponse, status_code=201)
async def create_issue(
    payload: CreateSiteIssueRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Create a new site issue / blocker."""
    _project_ids, denied = _resolve_project_ids(auth_context, payload.project_id)
    if denied or _site_filter_denied(auth_context, payload.project_id, payload.site_id):
        raise HTTPException(status_code=403, detail="Not authorized for target project or site")

    repo = PostgresProgressReadRepository(conn)
    try:
        item = await repo.create_issue(
            organization_id=auth_context.organization_id,
            user_id=auth_context.user_id,
            payload=payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return item


@router.post("/issues/{issue_id}/acknowledge")
async def acknowledge_issue(
    issue_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Mark a site issue as ACKNOWLEDGED (OPEN -> ACKNOWLEDGED only)."""
    repo = PostgresProgressReadRepository(conn)
    existing = await repo.get_issue(auth_context.organization_id, issue_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if _site_filter_denied(auth_context, existing["project_id"], existing["site_id"]):
        raise HTTPException(status_code=403, detail="Not authorized for this issue")

    success = await repo.acknowledge_issue(
        organization_id=auth_context.organization_id,
        issue_id=issue_id,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Issue must be OPEN to be acknowledged")

    return {"status": "success", "message": "Site issue acknowledged"}


@router.post("/issues/{issue_id}/wont-fix")
async def wont_fix_issue(
    issue_id: uuid.UUID,
    payload: WontFixSiteIssueRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Mark a site issue as WONT_FIX (OPEN/ACKNOWLEDGED -> WONT_FIX)."""
    repo = PostgresProgressReadRepository(conn)
    existing = await repo.get_issue(auth_context.organization_id, issue_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if _site_filter_denied(auth_context, existing["project_id"], existing["site_id"]):
        raise HTTPException(status_code=403, detail="Not authorized for this issue")

    success = await repo.wont_fix_issue(
        organization_id=auth_context.organization_id,
        issue_id=issue_id,
        notes=payload.resolution_notes,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Issue is already resolved/won't-fix or cannot be updated")

    return {"status": "success", "message": "Site issue marked as won't fix"}


@router.post("/issues/{issue_id}/resolve")
async def resolve_issue(
    issue_id: uuid.UUID,
    payload: ResolveSiteIssueRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Mark a site issue as RESOLVED with resolution notes."""
    repo = PostgresProgressReadRepository(conn)
    existing = await repo.get_issue(auth_context.organization_id, issue_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if _site_filter_denied(auth_context, existing["project_id"], existing["site_id"]):
        raise HTTPException(status_code=403, detail="Not authorized for this issue")

    success = await repo.resolve_issue(
        organization_id=auth_context.organization_id,
        issue_id=issue_id,
        notes=payload.resolution_notes,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Issue is already resolved or cannot be updated")

    return {"status": "success", "message": "Site issue resolved"}


@router.get("/gallery")
async def list_gallery(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    attachment_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
):
    """List site media gallery attachments within organization & scope.
    Each item carries `url`, a short-lived link to the photo (WEB-24), or
    null when storage can't give one."""
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return {"items": [], "total": 0}

    repo = PostgresProgressReadRepository(conn)
    items, total = await repo.list_gallery(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        site_id=site_id,
        attachment_type=attachment_type,
        limit=limit,
        offset=offset,
    )
    for item in items:
        item["url"] = await signed_media_url(object_storage, item.get("media_object_key"))
    return {"items": items, "total": total}


@router.get("/settings", response_model=OperationsSettingsResponse)
async def get_operations_settings(
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Return site operations settings for the caller's organization."""
    from mesiri.infrastructure.postgres.repositories.organization_settings import (
        PostgresOrganizationSettingsRepository,
    )

    repo = PostgresOrganizationSettingsRepository(conn)
    try:
        stored = await repo.get(auth_context.organization_id, "progress_settings")
        if stored:
            return OperationsSettingsResponse(**stored)
    except Exception:
        pass
    return OperationsSettingsResponse()


@router.patch("/settings", response_model=OperationsSettingsResponse)
async def update_operations_settings(
    body: UpdateOperationsSettingsRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Patch site operations settings for the caller's organization."""
    from mesiri.infrastructure.postgres.repositories.organization_settings import (
        PostgresOrganizationSettingsRepository,
    )

    repo = PostgresOrganizationSettingsRepository(conn)
    stored = None
    try:
        stored = await repo.get(auth_context.organization_id, "progress_settings")
    except Exception:
        pass

    current_dict = stored if isinstance(stored, dict) else OperationsSettingsResponse().model_dump()
    patch_data = body.model_dump(exclude_unset=True)
    current_dict.update(patch_data)

    await repo.set(auth_context.organization_id, "progress_settings", current_dict)
    return OperationsSettingsResponse(**current_dict)



