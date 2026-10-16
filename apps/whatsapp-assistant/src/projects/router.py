"""Projects router — live, tenant-scoped project management for the Mesiri app.

Reads/writes the control-plane ``projects`` table, scoped to the caller's
organization (the JWT ``org`` claim). Mirrors the users router's standalone
engine + JWT auth pattern so the mobile app has a real backend instead of mock
data.
"""

from __future__ import annotations

import os
import uuid

import jwt
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine

from mesiri.authorization.roles import policy_is_org_wide, role_is_org_wide
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY
from mesiri.infrastructure.postgres.tenant import TenantScopedEngine, bind_tenant

router = APIRouter(prefix="/projects", tags=["projects"])

# SECRET_KEY / ALGORITHM: the one shared definition (identity/auth_service).
# A hardcoded copy here ignored MESIRI_JWT_SECRET, so setting the secret in
# production would have locked these routes out while leaving them forgeable.

# Roles allowed to create projects.
_CREATE_ROLES = {"ADMIN", "PROJECT_MANAGER"}
_VALID_STATUS = {"on_track", "at_risk", "critical"}

# status -> (StatusType for the UI badge, human label)
_STATUS_DISPLAY = {
    "on_track": ("success", "On Track"),
    "at_risk": ("warning", "At Risk"),
    "critical": ("critical", "Critical"),
    "archived": ("neutral", "Archived"),
}


def _get_engine():
    host = os.environ.get("MESIRI_POSTGRES__HOST", "localhost")
    port = os.environ.get("MESIRI_POSTGRES__PORT", "5432")
    user = os.environ.get("MESIRI_POSTGRES__USER", "mesiri")
    password = os.environ.get("MESIRI_POSTGRES__PASSWORD", "mesiri_local_dev")
    database = os.environ.get("MESIRI_POSTGRES__DATABASE", "mesiri")
    dsn = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
    return create_async_engine(dsn, echo=False, pool_pre_ping=True)


_engine = None


def get_engine():
    """Scoped to the caller's company on every transaction (BE-03)."""
    global _engine
    if _engine is None:
        _engine = TenantScopedEngine(_get_engine())
    return _engine


projects_table = sa.Table(
    "projects",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("organization_id", sa.UUID),
    sa.Column("name", sa.String),
    sa.Column("code", sa.String),
    sa.Column("location", sa.String),
    sa.Column("client", sa.String),
    sa.Column("description", sa.String),
    sa.Column("status", sa.String),
    sa.Column("progress", sa.Integer),
    sa.Column("open_issues", sa.Integer),
    sa.Column("client_logo_object_key", sa.String),
    # Reporting settings (0260, 0469). Until BE-35 this router -- the one
    # production mounts -- ignored them, so the dashboard's Reporting tab
    # saved nothing and the automatic DPR could not be switched on.
    sa.Column("reporting_timezone", sa.String),
    sa.Column("reporting_cutoff_time", sa.String),
    sa.Column("auto_generate_dpr", sa.Boolean),
    sa.Column("dpr_send_deadline", sa.String),
    sa.Column("required_report_types", sa.JSON),
)

sites_table = sa.Table(
    "sites",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("project_id", sa.UUID),
    sa.Column("organization_id", sa.UUID),
    sa.Column("name", sa.String),
    sa.Column("status", sa.String),
)

project_members_table = sa.Table(
    "project_members",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("project_id", sa.UUID),
    sa.Column("user_id", sa.UUID),
    sa.Column("role", sa.String),
    sa.Column("site_access_mode", sa.String),
)

site_members_table = sa.Table(
    "site_members",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("site_id", sa.UUID),
    sa.Column("user_id", sa.UUID),
)

# Who bypasses explicit project_members rows is defined once in
# mesiri/authorization/roles.py -- see role_is_org_wide / is_org_wide.

# Minimal shim -- only the columns this router needs (email/full_name/status
# for rendering a member row, organization_id to scope user lookups). See
# users/router.py for the fuller shim used by user-management endpoints.
users_table = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("organization_id", sa.UUID),
    sa.Column("email", sa.String),
    sa.Column("full_name", sa.String),
    sa.Column("status", sa.String),
    sa.Column("role", sa.String),
    sa.Column("access_policy", sa.JSON),
)

timeline_entries_table = sa.Table(
    "timeline_entries",
    sa.MetaData(),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("organization_id", sa.UUID),
    sa.Column("project_id", sa.UUID),
    sa.Column("site_id", sa.UUID),
    sa.Column("event_type", sa.String),
    sa.Column("summary", sa.String),
    sa.Column("occurred_at", sa.DateTime(timezone=True)),
)


# ---------------------------------------------------------------------------
# Schemas — shaped for the mobile ProjectHealthCard.
# ---------------------------------------------------------------------------
class ProjectResponse(BaseModel):
    id: uuid.UUID
    name: str
    location: str | None = None
    code: str | None = None
    client: str | None = None
    description: str | None = None
    status: str  # StatusType: success | warning | critical
    statusLabel: str
    progress: int
    openIssues: int
    reportingRatio: str | None = None
    # The client's logo for this project's DPRs (BE-33); fetch the image
    # through GET /projects/{id}/client-logo.
    hasClientLogo: bool = False
    # Reporting settings (BE-35): when the day closes, whether the DPR is
    # built automatically, and when it is sent at the latest (BE-16).
    reportingTimezone: str = "UTC"
    reportingCutoffTime: str = "18:00"
    autoGenerateDpr: bool = False
    dprSendDeadline: str = "21:00"
    requiredReportTypes: list[str] | None = None


class ProjectCreate(BaseModel):
    name: str
    location: str | None = None
    code: str | None = None
    client: str | None = None
    description: str | None = None
    status: str = "on_track"
    progress: int = 0
    reportingTimezone: str | None = None
    reportingCutoffTime: str | None = None
    autoGenerateDpr: bool | None = None
    dprSendDeadline: str | None = None
    requiredReportTypes: list[str] | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    location: str | None = None
    code: str | None = None
    client: str | None = None
    description: str | None = None
    status: str | None = None
    reportingTimezone: str | None = None
    reportingCutoffTime: str | None = None
    autoGenerateDpr: bool | None = None
    dprSendDeadline: str | None = None
    requiredReportTypes: list[str] | None = None


def _reporting_values(body: ProjectCreate | ProjectUpdate) -> dict:
    """The reporting settings a request sets, checked and normalised to the
    column shapes. 400 on a bad value: an unknown timezone or a time that
    isn't HH:MM would make the cutoff or the send never fire."""
    from zoneinfo import ZoneInfo

    from mesiri.application.automations.scheduling import parse_time_of_day

    values: dict = {}
    if body.reportingTimezone is not None:
        try:
            ZoneInfo(body.reportingTimezone)
        except Exception:  # noqa: BLE001 -- any lookup failure is a bad name
            raise HTTPException(status_code=400, detail="Unknown reporting timezone") from None
        values["reporting_timezone"] = body.reportingTimezone
    for field, column in (
        ("reportingCutoffTime", "reporting_cutoff_time"),
        ("dprSendDeadline", "dpr_send_deadline"),
    ):
        raw = getattr(body, field)
        if raw is None:
            continue
        try:
            values[column] = parse_time_of_day(raw).strftime("%H:%M")
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail=f"{field} must be HH:MM") from None
    if body.autoGenerateDpr is not None:
        values["auto_generate_dpr"] = body.autoGenerateDpr
    if body.requiredReportTypes is not None:
        values["required_report_types"] = body.requiredReportTypes
    return values


class SiteResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    status: str


class SiteCreate(BaseModel):
    name: str
    status: str = "active"


class SiteOverviewFieldActivityItem(BaseModel):
    eventType: str
    count: int


class SiteOverviewTimelineEntry(BaseModel):
    id: uuid.UUID
    eventType: str
    summary: str
    occurredAt: object


class SiteOverviewSiteRef(BaseModel):
    id: uuid.UUID
    name: str
    status: str


class SiteOverviewProjectRef(BaseModel):
    id: uuid.UUID
    name: str
    location: str | None = None
    requiredReportTypes: list[str] | None = None


class SiteOverviewData(BaseModel):
    site: SiteOverviewSiteRef
    project: SiteOverviewProjectRef
    reportingToday: bool
    lastActivityAt: object | None = None
    fieldActivityToday: list[SiteOverviewFieldActivityItem]
    recentActivity: list[SiteOverviewTimelineEntry]


class SiteUpdate(BaseModel):
    name: str | None = None
    status: str | None = None


class ProjectMemberResponse(BaseModel):
    userId: uuid.UUID
    email: str
    fullName: str
    role: str
    status: str


class ProjectMemberAdd(BaseModel):
    userId: uuid.UUID
    role: str = "SITE_ENGINEER"


def _to_response(row) -> ProjectResponse:
    status = row.status if row.status in _STATUS_DISPLAY else "on_track"
    ui_status, label = _STATUS_DISPLAY[status]
    return ProjectResponse(
        id=row.id,
        name=row.name,
        location=row.location,
        code=row.code,
        client=row.client,
        description=row.description,
        status=ui_status,
        statusLabel=label,
        progress=row.progress or 0,
        openIssues=row.open_issues or 0,
        reportingRatio=None,  # no sites/reporting subsystem yet
        hasClientLogo=bool(getattr(row, "client_logo_object_key", None)),
        reportingTimezone=getattr(row, "reporting_timezone", None) or "UTC",
        reportingCutoffTime=getattr(row, "reporting_cutoff_time", None) or "18:00",
        autoGenerateDpr=bool(getattr(row, "auto_generate_dpr", False)),
        dprSendDeadline=getattr(row, "dpr_send_deadline", None) or "21:00",
        requiredReportTypes=getattr(row, "required_report_types", None) or None,
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def _decode(authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    try:
        return jwt.decode(authorization.split(" ")[1], SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


async def get_current_user(authorization: str = Header(None)) -> dict:
    payload = _decode(authorization)
    bind_tenant(payload.get("org"))  # BE-03
    return payload


async def _is_org_wide(conn, payload: dict) -> bool:
    """True if this request's caller bypasses project_members entirely --
    an org-wide role, or a non-admin whose access_policy.mode is
    "all_projects". The latter is a live check against the DB, not read off
    the JWT: it's a standing bypass (see users/router.py's update_user_access
    and context/main_table_repositories.py, which apply the same rule), not
    a project_members snapshot, so it can't be baked into the
    token at login and must be re-checked on every request."""
    if role_is_org_wide(payload.get("role")):
        return True
    user_id = payload.get("sub")
    if not user_id:
        return False
    result = await conn.execute(
        sa.select(users_table.c.access_policy).where(users_table.c.id == user_id)
    )
    row = result.first()
    return policy_is_org_wide(row.access_policy if row else None)


def _member_project_ids_clause(user_id: uuid.UUID):
    """id IN (...) clause: a direct project_members row, or a site_members row
    on one of the project's sites (site access implies its project) -- same
    rule context/main_table_repositories.py's _AUTHORIZED_PROJECT_IDS applies
    for the WhatsApp side, kept consistent here for the REST side."""
    return projects_table.c.id.in_(
        sa.select(project_members_table.c.project_id).where(
            project_members_table.c.user_id == user_id
        )
    ) | projects_table.c.id.in_(
        sa.select(sites_table.c.project_id)
        .select_from(
            site_members_table.join(sites_table, sites_table.c.id == site_members_table.c.site_id)
        )
        .where(site_members_table.c.user_id == user_id)
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("", response_model=list[ProjectResponse])
async def list_projects(payload: dict = Depends(get_current_user)):
    org_id = payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    user_id = payload.get("sub")

    engine = get_engine()
    async with engine.connect() as conn:
        query = sa.select(projects_table).where(projects_table.c.organization_id == org_id)
        if not await _is_org_wide(conn, payload):
            query = query.where(_member_project_ids_clause(user_id))
        result = await conn.execute(query.order_by(projects_table.c.name))
        rows = result.fetchall()
    return [_to_response(r) for r in rows]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: uuid.UUID, payload: dict = Depends(get_current_user)):
    org_id = payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    user_id = payload.get("sub")

    engine = get_engine()
    async with engine.connect() as conn:
        query = sa.select(projects_table).where(
            projects_table.c.id == project_id,
            projects_table.c.organization_id == org_id,
        )
        if not await _is_org_wide(conn, payload):
            query = query.where(_member_project_ids_clause(user_id))
        result = await conn.execute(query)
        row = result.first()

    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _to_response(row)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: uuid.UUID,
    project_in: ProjectUpdate,
    payload: dict = Depends(get_current_user),
):
    org_id = payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    if (payload.get("role") or "").upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required to edit project")

    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.select(projects_table).where(
                projects_table.c.id == project_id,
                projects_table.c.organization_id == org_id,
            )
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Project not found")

        values: dict = {}
        if project_in.name is not None:
            values["name"] = project_in.name
        if project_in.location is not None:
            values["location"] = project_in.location
        if project_in.code is not None:
            values["code"] = project_in.code
        if project_in.client is not None:
            values["client"] = project_in.client
        if project_in.description is not None:
            values["description"] = project_in.description
        if project_in.status is not None:
            if project_in.status not in _VALID_STATUS:
                raise HTTPException(status_code=400, detail="Invalid status")
            values["status"] = project_in.status
        values.update(_reporting_values(project_in))

        if values:
            await conn.execute(
                projects_table.update().where(projects_table.c.id == project_id).values(**values)
            )

        refetch = await conn.execute(
            sa.select(projects_table).where(projects_table.c.id == project_id)
        )
        row = refetch.first()

    return _to_response(row)


@router.delete("/{project_id}", status_code=204)
async def archive_project(project_id: uuid.UUID, payload: dict = Depends(get_current_user)):
    org_id = payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    if (payload.get("role") or "").upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required to archive project")

    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.select(projects_table.c.id).where(
                projects_table.c.id == project_id,
                projects_table.c.organization_id == org_id,
            )
        )
        if result.first() is None:
            raise HTTPException(status_code=404, detail="Project not found")

        await conn.execute(
            projects_table.update().where(projects_table.c.id == project_id).values(status="archived")
        )



@router.get("/{project_id}/sites", response_model=list[SiteResponse])
async def list_project_sites(project_id: uuid.UUID, payload: dict = Depends(get_current_user)):
    org_id = payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    user_id = payload.get("sub")

    engine = get_engine()
    async with engine.connect() as conn:
        org_wide = await _is_org_wide(conn, payload)
        project_query = sa.select(projects_table.c.id).where(
            projects_table.c.id == project_id,
            projects_table.c.organization_id == org_id,
        )
        if not org_wide:
            project_query = project_query.where(_member_project_ids_clause(user_id))
        project_result = await conn.execute(project_query)
        if project_result.first() is None:
            raise HTTPException(status_code=404, detail="Project not found")

        sites_query = sa.select(sites_table).where(
            sites_table.c.project_id == project_id,
            sites_table.c.organization_id == org_id,
        )
        if not org_wide:
            # project_members.site_access_mode governs whether membership on
            # this project implies every site or only explicitly granted
            # ones -- mirrors backend/postgres/actor.py's _MEMBER_SITES_SQL.
            all_sites_member = sa.exists(
                sa.select(project_members_table.c.id).where(
                    project_members_table.c.project_id == project_id,
                    project_members_table.c.user_id == user_id,
                    project_members_table.c.site_access_mode == "all_sites",
                )
            )
            explicit_site_ids = sa.select(site_members_table.c.site_id).where(
                site_members_table.c.user_id == user_id
            )
            sites_query = sites_query.where(all_sites_member | sites_table.c.id.in_(explicit_site_ids))
        result = await conn.execute(sites_query.order_by(sites_table.c.name))
        rows = result.fetchall()

    return [
        SiteResponse(
            id=row.id,
            project_id=row.project_id,
            name=row.name,
            status=row.status or "active",
        )
        for row in rows
    ]


@router.post("/{project_id}/sites", response_model=SiteResponse)
async def create_project_site(
    project_id: uuid.UUID,
    site_in: SiteCreate,
    payload: dict = Depends(get_current_user),
):
    org_id = payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    if (payload.get("role") or "").upper() not in _CREATE_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to create sites")

    name = site_in.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Site name is required")

    engine = get_engine()
    async with engine.begin() as conn:
        project_result = await conn.execute(
            sa.select(projects_table.c.id).where(
                projects_table.c.id == project_id,
                projects_table.c.organization_id == org_id,
            )
        )
        if project_result.first() is None:
            raise HTTPException(status_code=404, detail="Project not found")

        site_id = uuid.uuid4()
        status = site_in.status.strip() or "active"
        await conn.execute(
            sites_table.insert().values(
                id=site_id,
                project_id=project_id,
                organization_id=org_id,
                name=name,
                status=status,
            )
        )

    return SiteResponse(id=site_id, project_id=project_id, name=name, status=status)


@router.put("/{project_id}/sites/{site_id}", response_model=SiteResponse)
async def update_project_site(
    project_id: uuid.UUID,
    site_id: uuid.UUID,
    site_in: SiteUpdate,
    payload: dict = Depends(get_current_user),
):
    org_id = payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    if (payload.get("role") or "").upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required to edit site")

    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.select(sites_table).where(
                sites_table.c.id == site_id,
                sites_table.c.project_id == project_id,
                sites_table.c.organization_id == org_id,
            )
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Site not found")

        values: dict = {}
        if site_in.name is not None:
            values["name"] = site_in.name
        if site_in.status is not None:
            values["status"] = site_in.status

        if values:
            await conn.execute(sites_table.update().where(sites_table.c.id == site_id).values(**values))

        refetch = await conn.execute(sa.select(sites_table).where(sites_table.c.id == site_id))
        row = refetch.first()

    return SiteResponse(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        status=row.status or "active",
    )


@router.delete("/{project_id}/sites/{site_id}", status_code=204)
async def archive_project_site(
    project_id: uuid.UUID,
    site_id: uuid.UUID,
    payload: dict = Depends(get_current_user),
):
    org_id = payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    if (payload.get("role") or "").upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required to archive site")

    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.select(sites_table.c.id).where(
                sites_table.c.id == site_id,
                sites_table.c.project_id == project_id,
                sites_table.c.organization_id == org_id,
            )
        )
        if result.first() is None:
            raise HTTPException(status_code=404, detail="Site not found")

        await conn.execute(
            sites_table.update().where(sites_table.c.id == site_id).values(status="archived")
        )



@router.get("/{project_id}/sites/{site_id}/overview", response_model=SiteOverviewData)
async def get_site_overview(
    project_id: uuid.UUID,
    site_id: uuid.UUID,
    payload: dict = Depends(get_current_user),
):
    org_id = payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    engine = get_engine()
    async with engine.connect() as conn:
        project_row = (
            await conn.execute(
                sa.text(
                    "SELECT id, name, location, required_report_types FROM projects "
                    "WHERE id = :project_id AND organization_id = :org_id"
                ),
                {"project_id": project_id, "org_id": org_id},
            )
        ).mappings().first()
        if project_row is None:
            raise HTTPException(status_code=404, detail="Project not found")

        site_row = await conn.execute(
            sa.select(sites_table).where(
                sites_table.c.id == site_id,
                sites_table.c.project_id == project_id,
                sites_table.c.organization_id == org_id,
            )
        )
        site = site_row.first()
        if site is None:
            raise HTTPException(status_code=404, detail="Site not found")

        today_counts = (
            await conn.execute(
                sa.text(
                    "SELECT event_type, COUNT(*) AS cnt FROM timeline_entries "
                    "WHERE site_id = :site_id AND occurred_at >= CURRENT_DATE "
                    "GROUP BY event_type"
                ),
                {"site_id": site_id},
            )
        ).mappings().all()

        last_activity = (
            await conn.execute(
                sa.text("SELECT MAX(occurred_at) AS last FROM timeline_entries WHERE site_id = :site_id"),
                {"site_id": site_id},
            )
        ).mappings().first()

        recent_rows = (
            await conn.execute(
                sa.text(
                    "SELECT id, event_type, summary, occurred_at FROM timeline_entries "
                    "WHERE site_id = :site_id ORDER BY occurred_at DESC LIMIT 20"
                ),
                {"site_id": site_id},
            )
        ).mappings().all()

    field_activity = [
        SiteOverviewFieldActivityItem(eventType=r["event_type"], count=r["cnt"]) for r in today_counts
    ]
    reporting_today = any(
        r["event_type"] in ("MaterialReceived", "MaterialUsed") for r in today_counts
    )

    return SiteOverviewData(
        site=SiteOverviewSiteRef(id=site.id, name=site.name, status=site.status or "active"),
        project=SiteOverviewProjectRef(
            id=project_row["id"],
            name=project_row["name"],
            location=project_row["location"],
            requiredReportTypes=project_row["required_report_types"],
        ),
        reportingToday=reporting_today,
        lastActivityAt=last_activity["last"] if last_activity else None,
        fieldActivityToday=field_activity,
        recentActivity=[
            SiteOverviewTimelineEntry(
                id=r["id"], eventType=r["event_type"], summary=r["summary"], occurredAt=r["occurred_at"]
            )
            for r in recent_rows
        ],
    )


@router.post("", response_model=ProjectResponse)
async def create_project(project_in: ProjectCreate, payload: dict = Depends(get_current_user)):
    org_id = payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    if (payload.get("role") or "").upper() not in _CREATE_ROLES:
        raise HTTPException(status_code=403, detail="Not authorized to create projects")
    if not project_in.name.strip():
        raise HTTPException(status_code=400, detail="Project name is required")

    status = project_in.status if project_in.status in _VALID_STATUS else "on_track"
    progress = max(0, min(100, project_in.progress))
    project_id = uuid.uuid4()
    creator_id = payload.get("sub")
    # Only what was sent; the rest take the column defaults (UTC, 18:00,
    # automatic DPR off, send by 21:00).
    reporting = _reporting_values(project_in)

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            projects_table.insert().values(
                id=project_id,
                organization_id=org_id,
                name=project_in.name.strip(),
                code=project_in.code,
                location=project_in.location,
                client=project_in.client,
                description=project_in.description,
                status=status,
                progress=progress,
                open_issues=0,
                **reporting,
            )
        )

        # A creator who isn't already org-wide (an ADMIN, or an access_policy
        # "all_projects" grant) needs an explicit project_members row for
        # their own project -- without one, list_projects/get_project's
        # membership scoping (see _member_project_ids_clause above) hides
        # the project from the person who just created it. PROJECT_MANAGER
        # is the role this actually bites: it's in _CREATE_ROLES but not
        # an org-wide role.
        grant_creator = creator_id is not None and not await _is_org_wide(conn, payload)
        if grant_creator:
            await conn.execute(
                project_members_table.insert().values(
                    id=uuid.uuid4(),
                    project_id=project_id,
                    user_id=creator_id,
                    role=payload.get("role") or "PROJECT_MANAGER",
                    site_access_mode="all_sites",
                )
            )


    # Built from what was inserted; settings not sent show their column
    # defaults (_to_response's fallbacks), which is what the row holds.
    from types import SimpleNamespace

    return _to_response(
        SimpleNamespace(
            id=project_id,
            name=project_in.name.strip(),
            location=project_in.location,
            code=project_in.code,
            client=project_in.client,
            description=project_in.description,
            status=status,
            progress=progress,
            open_issues=0,
            client_logo_object_key=None,
            **reporting,
        )
    )


# ---------------------------------------------------------------------------
# Project members -- the source of truth AuthorizationService and the
# WhatsApp context resolver both now read (see project/site membership audit
# and context/main_table_repositories.py). These endpoints
# were previously only defined in backend/src/mesiri/domains/projects/router
# .py, a router that is never mounted by the app actually deployed in
# production (this one) -- the dashboard's Project Members tab has been
# calling a 404 the whole time. Same URL paths and response shape as that
# router's ProjectMemberResponse/ProjectMemberAdd, so the dashboard needs no
# changes.
# ---------------------------------------------------------------------------
def _to_member_response(row) -> ProjectMemberResponse:
    return ProjectMemberResponse(
        userId=row.user_id,
        email=row.email,
        fullName=row.full_name,
        role=row.role,
        status=row.status,
    )


@router.get("/{project_id}/members", response_model=list[ProjectMemberResponse])
async def list_project_members(project_id: uuid.UUID, payload: dict = Depends(get_current_user)):
    org_id = payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    engine = get_engine()
    async with engine.connect() as conn:
        project_result = await conn.execute(
            sa.select(projects_table.c.id).where(
                projects_table.c.id == project_id,
                projects_table.c.organization_id == org_id,
            )
        )
        if project_result.first() is None:
            raise HTTPException(status_code=404, detail="Project not found")

        result = await conn.execute(
            sa.select(
                project_members_table.c.user_id,
                project_members_table.c.role,
                users_table.c.email,
                users_table.c.full_name,
                users_table.c.status,
            )
            .select_from(
                project_members_table.join(
                    users_table, users_table.c.id == project_members_table.c.user_id
                )
            )
            .where(project_members_table.c.project_id == project_id)
        )
        rows = result.fetchall()

    return [_to_member_response(r) for r in rows]


@router.post("/{project_id}/members", response_model=ProjectMemberResponse, status_code=201)
async def add_project_member(
    project_id: uuid.UUID,
    body: ProjectMemberAdd,
    payload: dict = Depends(get_current_user),
):
    if (payload.get("role") or "").upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required to add member")
    org_id = payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    engine = get_engine()
    async with engine.begin() as conn:
        project_result = await conn.execute(
            sa.select(projects_table.c.id).where(
                projects_table.c.id == project_id,
                projects_table.c.organization_id == org_id,
            )
        )
        if project_result.first() is None:
            raise HTTPException(status_code=404, detail="Project not found")

        user_result = await conn.execute(
            sa.select(users_table).where(
                users_table.c.id == body.userId,
                users_table.c.organization_id == org_id,
            )
        )
        user_row = user_result.first()
        if user_row is None:
            raise HTTPException(status_code=404, detail="User not found in organization")

        try:
            await conn.execute(
                project_members_table.insert().values(
                    id=uuid.uuid4(),
                    project_id=project_id,
                    user_id=body.userId,
                    role=body.role,
                )
            )
        except Exception as exc:
            if "unique" in str(exc).lower() or "23505" in str(exc):
                raise HTTPException(
                    status_code=409, detail="User is already a member of this project"
                ) from exc
            raise

    return ProjectMemberResponse(
        userId=user_row.id,
        email=user_row.email,
        fullName=user_row.full_name,
        role=body.role,
        status=user_row.status,
    )


@router.delete("/{project_id}/members/{user_id}", status_code=204)
async def remove_project_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: dict = Depends(get_current_user),
):
    if (payload.get("role") or "").upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required to remove member")
    org_id = payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    engine = get_engine()
    async with engine.begin() as conn:
        project_result = await conn.execute(
            sa.select(projects_table.c.id).where(
                projects_table.c.id == project_id,
                projects_table.c.organization_id == org_id,
            )
        )
        if project_result.first() is None:
            raise HTTPException(status_code=404, detail="Project not found")

        await conn.execute(
            project_members_table.delete().where(
                project_members_table.c.project_id == project_id,
                project_members_table.c.user_id == user_id,
            )
        )



# ---------------------------------------------------------------------------
# Client logo (BE-33) -- shown on this project's DPRs
# ---------------------------------------------------------------------------
_LOGO_LINK_SECONDS = 900


class ClientLogoUpload(BaseModel):
    content_type: str
    # The image file, base64-encoded (PNG, JPEG or WebP, up to 700 KB).
    data_base64: str


class ClientLogoResponse(BaseModel):
    hasClientLogo: bool
    # Short-lived link to the image; None when there is no logo or storage
    # cannot hand out links.
    url: str | None = None


def _storage(request: Request):
    from mesiri.infrastructure.objectstorage.dependency import get_object_storage

    return get_object_storage(request)


async def _client_logo_response(storage, key: str | None) -> ClientLogoResponse:
    if not key:
        return ClientLogoResponse(hasClientLogo=False)
    url = await storage.generate_presigned_url(key, expires_in_seconds=_LOGO_LINK_SECONDS)
    return ClientLogoResponse(
        hasClientLogo=True, url=url if url.startswith(("http://", "https://")) else None
    )


async def _require_admin_project(conn, payload: dict, project_id: uuid.UUID) -> tuple:
    """(org_id, current logo key) for a project an admin of its company may edit."""
    org_id = payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    if (payload.get("role") or "").upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required to edit project")
    row = (
        await conn.execute(
            sa.select(projects_table.c.client_logo_object_key).where(
                projects_table.c.id == project_id,
                projects_table.c.organization_id == org_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return uuid.UUID(str(org_id)), row.client_logo_object_key


@router.get("/{project_id}/client-logo", response_model=ClientLogoResponse)
async def get_client_logo(
    project_id: uuid.UUID, request: Request, payload: dict = Depends(get_current_user)
):
    org_id = payload.get("org")
    if not org_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    async with get_engine().connect() as conn:
        query = sa.select(projects_table.c.client_logo_object_key).where(
            projects_table.c.id == project_id,
            projects_table.c.organization_id == org_id,
        )
        if not await _is_org_wide(conn, payload):
            query = query.where(_member_project_ids_clause(payload.get("sub")))
        row = (await conn.execute(query)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return await _client_logo_response(_storage(request), row.client_logo_object_key)


@router.put("/{project_id}/client-logo", response_model=ClientLogoResponse)
async def upload_client_logo(
    project_id: uuid.UUID,
    body: ClientLogoUpload,
    request: Request,
    payload: dict = Depends(get_current_user),
):
    """Upload or replace the client logo shown on this project's DPRs."""
    from mesiri.domains.organizations import branding

    try:
        data, extension, content_type = branding.decode_upload(body.data_base64, body.content_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    storage = _storage(request)
    async with get_engine().begin() as conn:
        org_id, old = await _require_admin_project(conn, payload, project_id)
        key = branding.client_logo_key(org_id, project_id, extension)
        await storage.put_object(key, data, content_type=content_type)
        await conn.execute(
            projects_table.update()
            .where(projects_table.c.id == project_id)
            .values(client_logo_object_key=key)
        )
    # Committed: the old file is no longer referenced.
    await _remove_old_logo(storage, org_id, old)
    return await _client_logo_response(storage, key)


@router.delete("/{project_id}/client-logo", response_model=ClientLogoResponse)
async def remove_client_logo(
    project_id: uuid.UUID, request: Request, payload: dict = Depends(get_current_user)
):
    storage = _storage(request)
    async with get_engine().begin() as conn:
        org_id, old = await _require_admin_project(conn, payload, project_id)
        await conn.execute(
            projects_table.update()
            .where(projects_table.c.id == project_id)
            .values(client_logo_object_key=None)
        )
    await _remove_old_logo(storage, org_id, old)
    return ClientLogoResponse(hasClientLogo=False)


async def _remove_old_logo(storage, org_id: uuid.UUID, key: str | None) -> None:
    from mesiri.domains.organizations import branding

    if not branding.owns_key(org_id, key):
        return
    try:
        await storage.delete_object(key)
    except Exception:  # noqa: BLE001 -- an unused file left behind, nothing more
        import logging

        logging.getLogger(__name__).warning("client_logo.delete_failed key=%s", key, exc_info=True)
