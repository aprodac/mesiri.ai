from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.domains.timeline.responses import (
    TimelineDaySummaryResponse,
    TimelineEntriesListResponse,
)
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.timeline import PostgresTimelineReadRepository

router = APIRouter(
    prefix="/timeline",
    tags=["timeline"],
    dependencies=[Depends(require_module("dpr"))],
)


def _resolve_project_ids(
    auth_context: AuthorizationContext, project_id: uuid.UUID | None
) -> tuple[set[uuid.UUID] | None, bool]:
    """Resolve the project_ids filter from scope + an optional explicit project_id.

    Returns (project_ids, out_of_scope) — out_of_scope=True means the caller
    should short-circuit to an empty result.
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
    """True if the requested site_id filter must be denied under the caller's site scope.

    Mirrors mesiri.domains.materials.router._site_filter_denied: site access is
    resolved per-project, so a site_id without a project_id can only be trusted
    for org-wide (all_projects) callers.
    """
    if site_id is None:
        return False
    if project_id is None:
        return not auth_context.project_scope.grants_all_org_projects
    site_scope = auth_context.site_scope_for_project(project_id)
    if site_scope.grants_all_sites:
        return False
    return site_id not in site_scope.site_ids


@router.get("", response_model=TimelineEntriesListResponse)
async def list_timeline(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    event_type: str | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """List timeline entries within the user's organization and project scope."""
    project_ids, out_of_scope = _resolve_project_ids(auth_context, project_id)
    if out_of_scope:
        return {"items": [], "total": 0}
    if _site_filter_denied(auth_context, project_id, site_id):
        return {"items": [], "total": 0}

    repo = PostgresTimelineReadRepository(conn)
    items, total = await repo.list_entries(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        site_id=site_id,
        event_type=event_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total}


@router.get("/day-summary", response_model=TimelineDaySummaryResponse)
async def timeline_day_summary(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Aggregated per-day, per-event-type counts within the user's scope."""
    project_ids, out_of_scope = _resolve_project_ids(auth_context, project_id)
    if out_of_scope:
        return {"items": []}
    if _site_filter_denied(auth_context, project_id, site_id):
        return {"items": []}

    repo = PostgresTimelineReadRepository(conn)
    items = await repo.day_summary(
        organization_id=auth_context.organization_id,
        project_ids=project_ids,
        site_id=site_id,
        date_from=date_from,
        date_to=date_to,
    )
    return {"items": items}
