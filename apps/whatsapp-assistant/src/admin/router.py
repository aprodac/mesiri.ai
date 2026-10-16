"""Admin router for Control Plane - tenant provisioning."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine

from mesiri.application.audit.record import record_admin_action
from mesiri.application.identity.phone_numbers import NUMBER_TAKEN_MESSAGE, whatsapp_number_taken
from mesiri.application.organizations import trial_controls
from mesiri.application.organizations.companies_overview import company_setup, list_companies
from mesiri.application.organizations.create_company import (
    DEFAULT_DB_ROUTE,
    DEFAULT_DEPLOYMENT_TYPE,
    START_ACTIVE,
    CompanyCreationError,
    NewCompany,
    create_company,
)
from mesiri.authorization.roles import ALL_PROJECTS_MODE, is_org_wide
from mesiri.domains.audit import actions as audit
from mesiri.domains.audit.actions import actor_from_admin
from mesiri.domains.organizations import lifecycle
from mesiri.domains.organizations import settings as org_settings
from mesiri.domains.organizations.settings import VALID_ROLES
from mesiri.domains.shared.auth import require_platform_admin
from mesiri.domains.timeline.responses import TimelineEntriesListResponse
from mesiri.infrastructure.postgres.repositories.timeline import PostgresTimelineReadRepository
from users.access_service import DEFAULT_ACCESS_POLICY, AccessPolicy, apply_access_policy

router = APIRouter(prefix="/admin/organizations", tags=["admin"])


# ---------------------------------------------------------------------------
# DB Connection (standalone for the admin router)
# ---------------------------------------------------------------------------
def _get_engine():
    """Build async engine from environment variables."""
    host = os.environ.get("MESIRI_POSTGRES__HOST", "localhost")
    port = os.environ.get("MESIRI_POSTGRES__PORT", "5432")
    user = os.environ.get("MESIRI_POSTGRES__USER", "mesiri")
    password = os.environ.get("MESIRI_POSTGRES__PASSWORD", "mesiri_local_dev")
    database = os.environ.get("MESIRI_POSTGRES__DATABASE", "mesiri")
    dsn = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
    return create_async_engine(dsn, echo=False, pool_pre_ping=True)


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = _get_engine()
    return _engine


# ---------------------------------------------------------------------------
# Tables (raw SQLAlchemy core - no ORM needed)
# ---------------------------------------------------------------------------
metadata = sa.MetaData()

organizations_table = sa.Table(
    "organizations",
    metadata,
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("name", sa.String),
    sa.Column("deployment_type", sa.String),
    sa.Column("db_route", sa.String),
    sa.Column("status", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)

users_table = sa.Table(
    "users",
    metadata,
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("organization_id", sa.UUID),
    sa.Column("email", sa.String),
    sa.Column("hashed_password", sa.String),
    sa.Column("full_name", sa.String),
    sa.Column("role", sa.String),
    sa.Column("status", sa.String),
    sa.Column("whatsapp_number", sa.String),
    sa.Column("access_policy", sa.JSON),
)

projects_table = sa.Table(
    "projects",
    metadata,
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("organization_id", sa.UUID),
    sa.Column("name", sa.String),
)

sites_table = sa.Table(
    "sites",
    metadata,
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("project_id", sa.UUID),
    sa.Column("organization_id", sa.UUID),
    sa.Column("name", sa.String),
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    deployment_type: str
    db_route: str
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SetupProgressResponse(BaseModel):
    has_team: bool
    has_site: bool
    first_update_at: datetime | None = None
    first_dpr_sent_at: datetime | None = None


class CompanyListItem(OrganizationResponse):
    """A row of the companies list (SA-02): the company plus its effective
    status and setup progress (application/organizations/companies_overview)."""

    effective_status: str
    trial_started_at: datetime | None = None
    trial_ends_at: datetime | None = None
    trial_days_left: int | None = None
    converted_at: datetime | None = None
    signup_source: str
    setup: SetupProgressResponse
    open_branding_requests: int = 0


class TrialExtendRequest(BaseModel):
    days: int


class SuspendRequest(BaseModel):
    reason: str | None = None


class PlanChangeResponse(BaseModel):
    organization_id: uuid.UUID
    status: str
    effective_status: str
    trial_started_at: datetime | None = None
    trial_ends_at: datetime | None = None
    converted_at: datetime | None = None


class OrganizationProvision(BaseModel):
    """What the control panel sends to create a company. The original six
    fields still work unchanged; the rest are optional (SS-03)."""

    name: str
    deployment_type: str = DEFAULT_DEPLOYMENT_TYPE
    db_route: str = DEFAULT_DB_ROUTE
    admin_name: str
    admin_email: str | None = None
    admin_password: str | None = None
    admin_whatsapp_number: str | None = None
    project_name: str | None = None
    site_name: str | None = None
    # Several sites under the one project (SA-01), instead of site_name.
    site_names: list[str] | None = None
    start_as: str = START_ACTIVE


class ProvisionedSite(BaseModel):
    site_id: uuid.UUID
    name: str


class ProvisionResponse(OrganizationResponse):
    signup_source: str
    timezone: str
    trial_started_at: datetime | None = None
    trial_ends_at: datetime | None = None
    owner_user_id: uuid.UUID
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    materials_seeded: int = 0
    sites: list[ProvisionedSite] = []


class ProjectAccessGrant(BaseModel):
    project_id: uuid.UUID
    project_name: str
    site_access: str


class OrgUserResponse(BaseModel):
    id: uuid.UUID
    full_name: str | None = None
    email: str | None = None
    role: str | None = None
    status: str = "active"
    whatsapp_number: str | None = None
    access_mode: str = "custom_projects"
    project_access: list[ProjectAccessGrant] = []


class UserStatusUpdate(BaseModel):
    status: str


class FinanceSeedRequest(BaseModel):
    include_demo_transactions: bool = True


class FinanceSeedResponse(BaseModel):
    organization_id: uuid.UUID
    categories_created: int
    accounts_created: int
    vendors_created: int
    settings_created: int
    expenses_created: int
    transactions_created: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hash_password(plain: str) -> str:
    """Hash password using bcrypt directly (avoids passlib/bcrypt 5.0 incompatibility)."""
    import bcrypt as _bcrypt

    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("", response_model=list[CompanyListItem])
async def list_organizations(_admin: dict = Depends(require_platform_admin)):
    """Every company, newest first, with status and setup progress (SA-02)."""
    async with get_engine().connect() as conn:
        companies = await list_companies(conn)
    return [CompanyListItem.model_validate(company, from_attributes=True) for company in companies]


@router.get("/{org_id}/overview", response_model=CompanyListItem)
async def get_organization_overview(
    org_id: uuid.UUID, _admin: dict = Depends(require_platform_admin)
):
    """One company's status, trial dates and setup progress (SS-10 plan card)."""
    async with get_engine().connect() as conn:
        company = await company_setup(conn, org_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return CompanyListItem.model_validate(company, from_attributes=True)


async def _change_plan(
    org_id: uuid.UUID,
    action: str,
    admin: dict,
    *,
    days: int | None = None,
    reason: str | None = None,
) -> PlanChangeResponse:
    """Extend / convert / suspend / reactivate (SS-10), audited in the same
    transaction. WhatsApp reads the row on every message, so it follows at once."""
    try:
        async with get_engine().begin() as conn:  # commits, or rolls back on error
            after = await trial_controls.apply_trial_action(
                conn, org_id, action, actor=actor_from_admin(admin), days=days, reason=reason
            )
    except trial_controls.TrialControlError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return PlanChangeResponse(
        organization_id=org_id,
        status=after.status,
        effective_status=lifecycle.effective_status(
            after.status, after.trial_ends_at, datetime.now(UTC)
        ),
        trial_started_at=after.trial_started_at,
        trial_ends_at=after.trial_ends_at,
        converted_at=after.converted_at,
    )


@router.post("/{org_id}/trial/extend", response_model=PlanChangeResponse)
async def extend_organization_trial(
    org_id: uuid.UUID, body: TrialExtendRequest, _admin: dict = Depends(require_platform_admin)
):
    return await _change_plan(org_id, trial_controls.EXTEND, _admin, days=body.days)


@router.post("/{org_id}/convert", response_model=PlanChangeResponse)
async def convert_organization(org_id: uuid.UUID, _admin: dict = Depends(require_platform_admin)):
    return await _change_plan(org_id, trial_controls.CONVERT, _admin)


@router.post("/{org_id}/suspend", response_model=PlanChangeResponse)
async def suspend_organization(
    org_id: uuid.UUID,
    body: SuspendRequest | None = None,
    _admin: dict = Depends(require_platform_admin),
):
    return await _change_plan(
        org_id, trial_controls.SUSPEND, _admin, reason=body.reason if body else None
    )


@router.post("/{org_id}/reactivate", response_model=PlanChangeResponse)
async def reactivate_organization(
    org_id: uuid.UUID, _admin: dict = Depends(require_platform_admin)
):
    return await _change_plan(org_id, trial_controls.REACTIVATE, _admin)


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(org_id: uuid.UUID, _admin: dict = Depends(require_platform_admin)):
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.select(organizations_table).where(organizations_table.c.id == org_id)
        )
        row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrganizationResponse(
        id=row.id,
        name=row.name,
        deployment_type=row.deployment_type,
        db_route=row.db_route,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.delete("/{org_id}", status_code=204)
async def delete_organization(org_id: uuid.UUID, _admin: dict = Depends(require_platform_admin)):
    """Hard-delete a tenant and every row scoped to it."""
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.select(organizations_table.c.id, organizations_table.c.name, organizations_table.c.status)
            .where(organizations_table.c.id == org_id)
        )
        org_row = result.first()
        if org_row is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        # 1. Fetch user IDs belonging to this organization
        user_rows = await conn.execute(
            sa.select(users_table.c.id).where(users_table.c.organization_id == org_id)
        )
        user_ids = [r[0] for r in user_rows.fetchall()]

        # 2. Interactions reference users without cascading
        if user_ids:
            await conn.execute(
                sa.text(
                    "DELETE FROM interactions WHERE user_id IN :uids"
                ).bindparams(sa.bindparam("uids", expanding=True)),
                {"uids": user_ids},
            )

        # 3. Delete main organization row (ON DELETE CASCADE sweeps all domain tables)
        try:
            await conn.execute(
                organizations_table.delete().where(organizations_table.c.id == org_id)
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=500, detail=f"Failed to delete organization: {exc}"
            ) from exc

        # The audit log has no foreign key to organizations, so this entry
        # outlives the company it describes.
        await record_admin_action(
            conn,
            actor=actor_from_admin(_admin),
            action=audit.COMPANY_DELETED,
            organization_id=org_id,
            target_type="organization",
            target_id=org_id,
            summary=f"Deleted {org_row.name}",
            details={"name": org_row.name, "status": org_row.status, "users_deleted": len(user_ids)},
        )


@router.get("/{org_id}/timeline", response_model=TimelineEntriesListResponse)
async def list_organization_timeline(
    org_id: uuid.UUID,
    event_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _admin: dict = Depends(require_platform_admin),
):
    """Cross-tenant activity feed for a single organization (platform admin view)."""
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.select(organizations_table.c.id).where(organizations_table.c.id == org_id)
        )
        if result.first() is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        repo = PostgresTimelineReadRepository(conn)
        items, total = await repo.list_entries(
            organization_id=org_id,
            event_type=event_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    return {"items": items, "total": total}


async def _fetch_org_users(
    conn, org_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> list[OrgUserResponse]:
    query = sa.select(
        users_table.c.id,
        users_table.c.full_name,
        users_table.c.email,
        users_table.c.role,
        users_table.c.status,
        users_table.c.whatsapp_number,
        users_table.c.access_policy,
    ).where(users_table.c.organization_id == org_id)

    if user_id is not None:
        query = query.where(users_table.c.id == user_id)

    result = await conn.execute(query)
    rows = result.fetchall()

    project_rows = await conn.execute(
        sa.select(projects_table.c.id, projects_table.c.name).where(
            projects_table.c.organization_id == org_id
        )
    )
    project_names = {row.id: row.name for row in project_rows.fetchall()}

    site_rows = await conn.execute(
        sa.select(sites_table.c.id, sites_table.c.name).where(
            sites_table.c.organization_id == org_id
        )
    )
    site_names = {row.id: row.name for row in site_rows.fetchall()}

    users = []
    for row in rows:
        policy = row.access_policy or {}
        # An org-wide ROLE is a live bypass that is never written into
        # access_policy or project_members, so reading the stored policy
        # alone under-reported it: an ADMIN carrying the default policy
        # ({"mode": "custom_projects", "projects": []}, set for every user at
        # creation) rendered as "No projects assigned" here while both the
        # WhatsApp assistant and the dashboard gave that same person every
        # project in the org. Under-reporting privilege is the dangerous
        # direction -- an operator auditing access sees "none" and moves on.
        # is_org_wide() is the shared rule every other surface already used.
        mode = (
            ALL_PROJECTS_MODE
            if is_org_wide(row.role, policy)
            else (policy.get("mode") or "custom_projects")
        )
        grants: list[ProjectAccessGrant] = []
        for grant in policy.get("projects") or []:
            if not isinstance(grant, dict):
                continue
            try:
                project_uuid = uuid.UUID(str(grant.get("projectId")))
            except (TypeError, ValueError):
                continue

            site_access = grant.get("siteAccess") or {}
            if site_access.get("mode") == "all_sites":
                site_label = "All Sites"
            else:
                site_ids = site_access.get("siteIds") or []
                names = []
                for site_id in site_ids:
                    try:
                        names.append(site_names.get(uuid.UUID(str(site_id)), str(site_id)))
                    except (TypeError, ValueError):
                        continue
                site_label = ", ".join(names) if names else "No Sites"

            grants.append(
                ProjectAccessGrant(
                    project_id=project_uuid,
                    project_name=project_names.get(project_uuid, str(project_uuid)),
                    site_access=site_label,
                )
            )

        users.append(
            OrgUserResponse(
                id=row.id,
                full_name=row.full_name,
                email=row.email,
                role=row.role,
                status=row.status or "active",
                whatsapp_number=row.whatsapp_number,
                access_mode=mode,
                project_access=grants,
            )
        )
    return users


@router.get("/{org_id}/users", response_model=list[OrgUserResponse])
async def list_organization_users(
    org_id: uuid.UUID, _admin: dict = Depends(require_platform_admin)
):
    """Users belonging to one org — powers the "run as" picker in the control-plane
    test harness (admin/system_graph_router.py). Only users with a
    whatsapp_number can actually be simulated; the caller marks the rest as
    untestable."""
    engine = get_engine()
    async with engine.connect() as conn:
        return await _fetch_org_users(conn, org_id)


@router.patch("/{org_id}/users/{user_id}/status", response_model=OrgUserResponse)
async def update_organization_user_status(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    body: UserStatusUpdate,
    _admin: dict = Depends(require_platform_admin),
):
    valid_statuses = {"active", "inactive", "suspended"}
    if body.status.lower() not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{body.status}'. Must be one of {sorted(valid_statuses)}",
        )

    # Lowercase, not .capitalize(). Every status is stored lowercase
    # (migration 0463 also lowercased organizations). Writing the capitalized form here
    # meant the assistant's own lookup (WHERE lower(u.status) = 'active',
    # previously case-sensitive) missed the row entirely -- so reactivating
    # someone locked them out of WhatsApp and they were told their number
    # wasn't recognized.
    normalized_status = body.status.strip().lower()
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.select(users_table.c.id, users_table.c.full_name, users_table.c.status).where(
                users_table.c.id == user_id, users_table.c.organization_id == org_id
            )
        )
        user_row = result.first()
        if user_row is None:
            raise HTTPException(status_code=404, detail="User not found in this organization")

        await conn.execute(
            users_table.update()
            .where(users_table.c.id == user_id, users_table.c.organization_id == org_id)
            .values(status=normalized_status)
        )
        await record_admin_action(
            conn,
            actor=actor_from_admin(_admin),
            action=audit.COMPANY_USER_STATUS_CHANGED,
            organization_id=org_id,
            target_type="user",
            target_id=user_id,
            summary=f"{user_row.full_name}: {user_row.status} -> {normalized_status}",
            details={"before": {"status": user_row.status}, "after": {"status": normalized_status}},
        )

    async with engine.connect() as conn:
        fetched = await _fetch_org_users(conn, org_id, user_id)
    if not fetched:
        raise HTTPException(status_code=404, detail="User not found after update")
    return fetched[0]


# ---------------------------------------------------------------------------
# Per-organization settings (migration 0365)
# ---------------------------------------------------------------------------
# These live here, not in backend/domains/admin/router.py, because that
# module is never registered by runtime/lifecycle.py -- only this one is.
# Defining them there made GET /admin/organizations/{id}/settings a 404,
# which took the whole control-panel organization page down: the page loads
# its data with Promise.all, so a single failing call rejected the lot and
# rendered "Not Found" instead of the organization.
@router.get("/{org_id}/settings")
async def get_organization_settings(
    org_id: uuid.UUID,
    _admin: dict = Depends(require_platform_admin),
):
    """Every known setting for `org_id`, with defaults filled in for anything
    never configured, plus the spec catalog the control panel renders its
    form from (so the UI never hardcodes its own copy of the setting list)."""
    from mesiri.infrastructure.postgres.repositories.organization_settings import (
        PostgresOrganizationSettingsRepository,
    )

    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.select(organizations_table.c.id).where(organizations_table.c.id == org_id)
        )
        if result.first() is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        repo = PostgresOrganizationSettingsRepository(conn)
        values = await repo.get_all(org_id)

    return {
        "settings": values,
        "specs": [
            {"key": spec.key, "description": spec.description, "default": spec.default}
            for spec in org_settings.all_specs()
        ],
        "valid_roles": sorted(VALID_ROLES),
        # The module switches (SA-07) render from this, not a frontend copy.
        "modules": org_settings.module_catalogue(),
    }


class OrganizationSettingUpdate(BaseModel):
    key: str
    value: object


@router.put("/{org_id}/settings")
async def update_organization_setting(
    org_id: uuid.UUID,
    body: OrganizationSettingUpdate,
    admin: dict = Depends(require_platform_admin),
):
    """Set one setting for `org_id`. Validation lives in
    domains/organizations/settings.py, so an unknown key or malformed value
    is rejected here rather than persisted as a row nothing ever reads."""
    from mesiri.infrastructure.postgres.repositories.organization_settings import (
        PostgresOrganizationSettingsRepository,
    )

    try:
        canonical = org_settings.validate(body.key, body.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.select(organizations_table.c.id).where(organizations_table.c.id == org_id)
        )
        if result.first() is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        repo = PostgresOrganizationSettingsRepository(conn)
        before = (await repo.get_all(org_id)).get(body.key)
        user_id = admin.get("sub")
        await repo.set(
            org_id,
            body.key,
            canonical,
            updated_by=uuid.UUID(user_id) if user_id else None,
        )
        await record_admin_action(
            conn,
            actor=actor_from_admin(admin),
            action=audit.COMPANY_SETTING_CHANGED,
            organization_id=org_id,
            target_type="setting",
            target_id=body.key,
            summary=f"Setting {body.key} changed",
            details={"key": body.key, "before": before, "after": canonical},
        )
    return {"key": body.key, "value": canonical}


class AuditEntryResponse(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    actor_kind: str
    actor_user_id: uuid.UUID | None = None
    actor_label: str | None = None
    action: str
    target_type: str | None = None
    target_id: str | None = None
    summary: str | None = None
    details: dict = {}


@router.get("/{org_id}/audit", response_model=list[AuditEntryResponse])
async def list_organization_audit(
    org_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    before: datetime | None = None,
    _admin: dict = Depends(require_platform_admin),
):
    """What Mesiri operators (and a self-serve signup) did to this company,
    newest first (BE-05). Page back with `before` = the last entry's
    `occurred_at`. Still answers after the company is deleted: the log has
    no foreign key to it."""
    from mesiri.infrastructure.postgres.repositories.admin_audit import (
        PostgresAdminAuditRepository,
    )

    engine = get_engine()
    async with engine.connect() as conn:
        entries = await PostgresAdminAuditRepository(conn).list_for_organization(
            org_id, limit=limit, before=before
        )
    return [
        AuditEntryResponse(
            id=e.id,
            occurred_at=e.occurred_at,
            actor_kind=e.actor_kind,
            actor_user_id=e.actor_user_id,
            actor_label=e.actor_label,
            action=e.action,
            target_type=e.target_type,
            target_id=e.target_id,
            summary=e.summary,
            details=e.details,
        )
        for e in entries
    ]


class OrgSiteSummary(BaseModel):
    id: uuid.UUID
    name: str


class OrgProjectSummary(BaseModel):
    id: uuid.UUID
    name: str
    sites: list[OrgSiteSummary] = []


@router.get("/{org_id}/projects", response_model=list[OrgProjectSummary])
async def list_organization_projects(
    org_id: uuid.UUID,
    _admin: dict = Depends(require_platform_admin),
):
    """Projects (with their sites) in one organization.

    Exists so the control panel's access editor can offer real choices --
    without it the UI would have no way to know what a user could be
    assigned to. Read-only; assignment itself goes through
    PUT /{org_id}/users/{user_id}/access.
    """
    engine = get_engine()
    async with engine.connect() as conn:
        project_rows = (
            await conn.execute(
                sa.select(projects_table.c.id, projects_table.c.name)
                .where(projects_table.c.organization_id == org_id)
                .order_by(projects_table.c.name)
            )
        ).fetchall()

        site_rows = (
            await conn.execute(
                sa.select(sites_table.c.id, sites_table.c.name, sites_table.c.project_id)
                .where(sites_table.c.organization_id == org_id)
                .order_by(sites_table.c.name)
            )
        ).fetchall()

    sites_by_project: dict[uuid.UUID, list[OrgSiteSummary]] = {}
    for row in site_rows:
        sites_by_project.setdefault(row.project_id, []).append(
            OrgSiteSummary(id=row.id, name=row.name)
        )

    return [
        OrgProjectSummary(
            id=row.id, name=row.name, sites=sites_by_project.get(row.id, [])
        )
        for row in project_rows
    ]


class OrgUserCreate(BaseModel):
    full_name: str
    email: str
    password: str
    role: str
    whatsapp_number: str | None = None


@router.post("/{org_id}/users", response_model=OrgUserResponse, status_code=201)
async def create_organization_user(
    org_id: uuid.UUID,
    body: OrgUserCreate,
    _admin: dict = Depends(require_platform_admin),
):
    """Add a person to an existing organization, as a platform admin.

    Previously the only creation path was POST /provision, which makes a
    whole new organization plus its first admin -- there was no way to add a
    second person to an org that already existed except by logging into that
    tenant's own dashboard.

    The new user starts with the same default access policy every user gets
    ({"mode": "custom_projects", "projects": []}), i.e. no projects until
    someone grants them -- except an ADMIN, who reaches everything by role
    (mesiri/authorization/roles.py). Access is then editable via
    PUT /{org_id}/users/{user_id}/access.
    """
    email = body.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    full_name = body.full_name.strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="full_name is required")
    if not body.password:
        raise HTTPException(status_code=400, detail="password is required")

    role = body.role.strip().upper()
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=400, detail=f"Invalid role. Must be one of {sorted(VALID_ROLES)}"
        )

    whatsapp = (body.whatsapp_number or "").strip() or None

    engine = get_engine()
    user_id = uuid.uuid4()
    async with engine.begin() as conn:
        org_exists = await conn.execute(
            sa.select(organizations_table.c.id).where(organizations_table.c.id == org_id)
        )
        if org_exists.first() is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        # Email is the login identity and is unique across the whole
        # platform, not per organization.
        clash = await conn.execute(
            sa.select(users_table.c.id).where(users_table.c.email == email)
        )
        if clash.first() is not None:
            raise HTTPException(status_code=409, detail="Email already registered")

        # The number is the join key for inbound WhatsApp messages (on its
        # digits); two users sharing one would make routing ambiguous.
        if whatsapp and await whatsapp_number_taken(conn, whatsapp):
            raise HTTPException(status_code=409, detail=NUMBER_TAKEN_MESSAGE)

        await conn.execute(
            users_table.insert().values(
                id=user_id,
                organization_id=org_id,
                email=email,
                hashed_password=_hash_password(body.password),
                full_name=full_name,
                role=role,
                whatsapp_number=whatsapp,
                status="active",
                access_policy=DEFAULT_ACCESS_POLICY,
            )
        )
        await record_admin_action(
            conn,
            actor=actor_from_admin(_admin),
            action=audit.COMPANY_USER_CREATED,
            organization_id=org_id,
            target_type="user",
            target_id=user_id,
            summary=f"Added {full_name} ({role})",
            details={
                "full_name": full_name,
                "email": email,
                "role": role,
                "whatsapp_number": whatsapp,
            },
        )

    async with engine.connect() as conn:
        fetched = await _fetch_org_users(conn, org_id, user_id)
    if not fetched:
        raise HTTPException(status_code=404, detail="User not found after creation")
    return fetched[0]


class OrgUserProfileUpdate(BaseModel):
    """Partial update — only provided fields change. Email stays immutable,
    matching the tenant-side users router."""

    role: str | None = None
    whatsapp_number: str | None = None
    full_name: str | None = None


@router.put("/{org_id}/users/{user_id}/access", response_model=OrgUserResponse)
async def update_organization_user_access(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    policy: AccessPolicy,
    _admin: dict = Depends(require_platform_admin),
):
    """Set which projects and sites a user can reach, as a platform admin.

    The platform-admin counterpart to the dashboard's
    PUT /users/{id}/access. Both call users/access_service.apply_access_policy
    so the validation, the membership replace, and the all_projects bypass
    semantics are provably identical -- duplicating them per surface is how
    the org-wide role rule ended up with five copies and one of them wrong.

    The org comes from the path rather than a JWT claim because a platform
    admin has no `org` claim; access_service still validates every project
    and site against that org, so this cannot grant cross-tenant access.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.select(
                users_table.c.id,
                users_table.c.role,
                users_table.c.full_name,
                users_table.c.access_policy,
            ).where(users_table.c.id == user_id, users_table.c.organization_id == org_id)
        )
        user_row = result.first()
        if user_row is None:
            raise HTTPException(status_code=404, detail="User not found in this organization")

        await apply_access_policy(
            conn,
            user_id=user_id,
            org_id=org_id,
            user_role=user_row.role,
            policy=policy,
        )
        await record_admin_action(
            conn,
            actor=actor_from_admin(_admin),
            action=audit.COMPANY_USER_ACCESS_CHANGED,
            organization_id=org_id,
            target_type="user",
            target_id=user_id,
            summary=f"{user_row.full_name}: project access set to {policy.mode}",
            details={"before": user_row.access_policy, "after": policy.model_dump()},
        )

    async with engine.connect() as conn:
        fetched = await _fetch_org_users(conn, org_id, user_id)
    if not fetched:
        raise HTTPException(status_code=404, detail="User not found after update")
    return fetched[0]


@router.patch("/{org_id}/users/{user_id}", response_model=OrgUserResponse)
async def update_organization_user_profile(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    body: OrgUserProfileUpdate,
    _admin: dict = Depends(require_platform_admin),
):
    """Set a user's role, WhatsApp number, or name from the control panel.

    The WhatsApp number is what maps an inbound message to this person at
    all (matched on its digits), and role feeds the org-wide access bypass.
    WhatsApp reads both from this row on every message.
    """
    updates: dict = {}
    if body.role is not None:
        role = body.role.strip().upper()
        if role not in VALID_ROLES:
            raise HTTPException(
                status_code=400, detail=f"Invalid role. Must be one of {sorted(VALID_ROLES)}"
            )
        updates["role"] = role
    if body.whatsapp_number is not None:
        # Empty string clears the mapping; anything else is stored as typed
        # (WhatsApp compares digits only).
        updates["whatsapp_number"] = body.whatsapp_number.strip() or None
    if body.full_name is not None:
        name = body.full_name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="full_name cannot be empty")
        updates["full_name"] = name

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.select(
                users_table.c.id,
                users_table.c.role,
                users_table.c.whatsapp_number,
                users_table.c.full_name,
            ).where(users_table.c.id == user_id, users_table.c.organization_id == org_id)
        )
        user_row = result.first()
        if user_row is None:
            raise HTTPException(status_code=404, detail="User not found in this organization")

        if updates.get("whatsapp_number") and await whatsapp_number_taken(
            conn, updates["whatsapp_number"], except_user_id=user_id
        ):
            # The number is the join key for inbound messages (on its digits);
            # two users sharing one would make routing ambiguous.
            raise HTTPException(status_code=409, detail=NUMBER_TAKEN_MESSAGE)

        await conn.execute(
            users_table.update()
            .where(users_table.c.id == user_id, users_table.c.organization_id == org_id)
            .values(**updates)
        )
        await record_admin_action(
            conn,
            actor=actor_from_admin(_admin),
            action=audit.COMPANY_USER_UPDATED,
            organization_id=org_id,
            target_type="user",
            target_id=user_id,
            summary=f"{user_row.full_name}: changed {', '.join(sorted(updates))}",
            details={
                "before": {k: getattr(user_row, k) for k in updates},
                "after": updates,
            },
        )

    async with engine.connect() as conn:
        fetched = await _fetch_org_users(conn, org_id, user_id)
    if not fetched:
        raise HTTPException(status_code=404, detail="User not found after update")
    return fetched[0]


@router.delete("/{org_id}/users/{user_id}", status_code=204)
async def delete_organization_user(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    force: bool = Query(default=False),
    _admin: dict = Depends(require_platform_admin),
):
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.select(
                users_table.c.id,
                users_table.c.full_name,
                users_table.c.email,
                users_table.c.role,
                users_table.c.whatsapp_number,
            ).where(users_table.c.id == user_id, users_table.c.organization_id == org_id)
        )
        user_row = result.first()
        if user_row is None:
            raise HTTPException(status_code=404, detail="User not found in this organization")

        if force:
            # Nullify created_by user references in domain tables that have created_by
            for table_name in (
                "money_accounts",
                "money_transactions",
                "expenses",
                "material_receipts",
                "material_usage",
                "material_movements",
                "equipment_events",
                "labour_attendance",
                "timeline_entries",
            ):
                await conn.execute(
                    sa.text(f"UPDATE {table_name} SET created_by = NULL WHERE created_by = :user_id"),
                    {"user_id": user_id},
                )

            # Nullify user_id / actor_user_id in workflow and logging tables
            await conn.execute(
                sa.text("UPDATE workflow_instances SET user_id = NULL WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
            await conn.execute(
                sa.text("UPDATE inbound_messages SET actor_user_id = NULL WHERE actor_user_id = :user_id"),
                {"user_id": user_id},
            )

            await conn.execute(
                sa.text("DELETE FROM interactions WHERE user_id = :user_id"),
                {"user_id": user_id},
            )

        try:
            await conn.execute(
                users_table.delete().where(
                    users_table.c.id == user_id, users_table.c.organization_id == org_id
                )
            )
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            if "foreign key" in msg or "violates" in msg or "constraint" in msg or "23503" in msg:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "User cannot be deleted because they own historical records "
                        "(materials, finance, timeline, etc). Deactivate them instead or use Force Delete."
                    ),
                ) from exc
            raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

        await record_admin_action(
            conn,
            actor=actor_from_admin(_admin),
            action=audit.COMPANY_USER_DELETED,
            organization_id=org_id,
            target_type="user",
            target_id=user_id,
            summary=f"Deleted {user_row.full_name}" + (" (force)" if force else ""),
            details={
                "full_name": user_row.full_name,
                "email": user_row.email,
                "role": user_row.role,
                "whatsapp_number": user_row.whatsapp_number,
                "force": force,
            },
        )


@router.post("/provision", response_model=ProvisionResponse)
async def provision_tenant(
    prov_in: OrganizationProvision, _admin: dict = Depends(require_platform_admin)
):
    """Create a company and its owner -- through the one create-company step
    every onboarding path shares (application/organizations/create_company)."""
    new = NewCompany(
        name=prov_in.name,
        owner_name=prov_in.admin_name,
        owner_email=prov_in.admin_email,
        owner_phone=prov_in.admin_whatsapp_number,
        owner_password=prov_in.admin_password,
        project_name=prov_in.project_name,
        site_name=prov_in.site_name,
        site_names=tuple(prov_in.site_names or ()),
        start_as=prov_in.start_as,
        signup_source="superadmin",
        deployment_type=prov_in.deployment_type,
        db_route=prov_in.db_route,
    )
    try:
        async with get_engine().begin() as conn:  # commits, or rolls back on error
            created = await create_company(conn, new, actor=actor_from_admin(_admin))
    except CompanyCreationError as exc:
        raise HTTPException(status_code=409 if exc.conflict else 400, detail=str(exc)) from exc

    return ProvisionResponse(
        id=created.organization_id,
        name=created.name,
        deployment_type=created.deployment_type,
        db_route=created.db_route,
        status=created.status,
        created_at=created.created_at,
        updated_at=created.created_at,
        signup_source=created.signup_source,
        timezone=created.timezone,
        trial_started_at=created.trial_started_at,
        trial_ends_at=created.trial_ends_at,
        owner_user_id=created.owner_user_id,
        project_id=created.project_id,
        site_id=created.site_id,
        materials_seeded=created.materials_seeded,
        sites=[ProvisionedSite(site_id=s.site_id, name=s.name) for s in created.sites],
    )


@router.post("/{org_id}/seed-finance", response_model=FinanceSeedResponse)
async def seed_organization_finance(
    org_id: uuid.UUID,
    payload: FinanceSeedRequest | None = None,
    admin: dict = Depends(require_platform_admin),
):
    from mesiri.domains.finance.seeder import AdminFinanceSeedingService

    if payload is None:
        payload = FinanceSeedRequest()

    engine = get_engine()
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                sa.select(organizations_table.c.id).where(organizations_table.c.id == org_id)
            )
            if result.first() is None:
                raise HTTPException(status_code=404, detail="Organization not found")

            admin_user_id = uuid.uuid4()
            if admin.get("sub"):
                try:
                    admin_user_id = uuid.UUID(admin["sub"])
                except (ValueError, TypeError):
                    pass

            seeder = AdminFinanceSeedingService(conn)
            stats = await seeder.seed_organization(
                organization_id=org_id,
                created_by=admin_user_id,
                include_demo_transactions=payload.include_demo_transactions,
            )
            await record_admin_action(
                conn,
                actor=actor_from_admin(admin),
                action=audit.COMPANY_FINANCE_SEEDED,
                organization_id=org_id,
                target_type="organization",
                target_id=org_id,
                summary="Seeded finance data"
                + (" with demo transactions" if payload.include_demo_transactions else ""),
                details={
                    "include_demo_transactions": payload.include_demo_transactions,
                    "stats": stats,
                },
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Surface the real DB error (constraint name, missing column, etc.)
        # in both the response and journalctl instead of a bare 500 -- the
        # seeder has already hit several distinct constraint violations that
        # were each indistinguishable from the client's point of view.
        import logging

        logging.getLogger(__name__).exception(
            "seed_organization_finance failed for org_id=%s", org_id
        )
        raise HTTPException(
            status_code=500,
            detail=f"Finance seeding failed: {type(exc).__name__}: {exc}",
        ) from exc
    return FinanceSeedResponse(organization_id=org_id, **stats)
