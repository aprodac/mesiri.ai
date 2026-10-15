from __future__ import annotations

import datetime as dt
import uuid
from datetime import datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.organizations.create_company import (
    DEFAULT_DB_ROUTE,
    START_ACTIVE,
    CompanyCreationError,
    NewCompany,
    create_company,
)
from mesiri.domains.audit.actions import actor_from_admin
from mesiri.domains.shared.auth import require_platform_admin
from mesiri.domains.timeline.responses import TimelineEntriesListResponse
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.models.organization import (
    DeploymentType,
    OrganizationModel,
    OrganizationStatus,
)
from mesiri.infrastructure.postgres.models.user import UserModel
from mesiri.infrastructure.postgres.repositories.timeline import PostgresTimelineReadRepository

router = APIRouter(prefix="/admin/organizations", tags=["admin"])

_users = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("email", sa.String),
    sa.Column("full_name", sa.String),
    sa.Column("role", sa.String),
    sa.Column("status", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)


class OrganizationCreate(BaseModel):
    name: str
    deployment_type: DeploymentType
    db_route: str
    status: OrganizationStatus = OrganizationStatus.ACTIVE


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    deployment_type: DeploymentType
    db_route: str
    status: OrganizationStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.post("", response_model=OrganizationResponse)
async def create_organization(
    org_in: OrganizationCreate,
    conn: AsyncConnection = Depends(get_db_conn),
    _admin: dict = Depends(require_platform_admin),
):
    stmt = (
        insert(OrganizationModel)
        .values(
            name=org_in.name,
            deployment_type=org_in.deployment_type,
            db_route=org_in.db_route,
            status=org_in.status.value,
        )
        .returning(OrganizationModel)
    )

    result = await conn.execute(stmt)
    org_row = result.first()

    if not org_row:
        raise HTTPException(status_code=500, detail="Failed to create organization")

    org = org_row[0]
    return org


@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    conn: AsyncConnection = Depends(get_db_conn),
    _admin: dict = Depends(require_platform_admin),
):
    result = await conn.execute(select(OrganizationModel))
    orgs = result.scalars().all()
    return orgs


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: uuid.UUID,
    conn: AsyncConnection = Depends(get_db_conn),
    _admin: dict = Depends(require_platform_admin),
):
    result = await conn.execute(select(OrganizationModel).where(OrganizationModel.id == org_id))
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.delete("/{org_id}", status_code=204)
async def delete_organization(
    org_id: uuid.UUID,
    conn: AsyncConnection = Depends(get_db_conn),
    _admin: dict = Depends(require_platform_admin),
):
    result = await conn.execute(select(OrganizationModel.id).where(OrganizationModel.id == org_id))
    if result.first() is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    await conn.execute(delete(UserModel).where(UserModel.organization_id == org_id))
    await conn.execute(delete(OrganizationModel).where(OrganizationModel.id == org_id))


class OrganizationUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    status: str
    created_at: datetime | None

    class Config:
        from_attributes = True


@router.get("/{org_id}/users", response_model=list[OrganizationUserResponse])
async def list_organization_users(
    org_id: uuid.UUID,
    conn: AsyncConnection = Depends(get_db_conn),
    _admin: dict = Depends(require_platform_admin),
):
    org_exists = await conn.execute(
        select(OrganizationModel.id).where(OrganizationModel.id == org_id)
    )
    if org_exists.first() is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    result = await conn.execute(
        select(_users)
        .where(_users.c.organization_id == org_id)
        .order_by(_users.c.created_at.desc())
    )
    return [
        OrganizationUserResponse(
            id=row.id,
            email=row.email,
            full_name=row.full_name,
            role=row.role,
            status=row.status or "active",
            created_at=row.created_at,
        )
        for row in result.fetchall()
    ]


@router.get("/{org_id}/timeline", response_model=TimelineEntriesListResponse)
async def list_organization_timeline(
    org_id: uuid.UUID,
    event_type: str | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    conn: AsyncConnection = Depends(get_db_conn),
    _admin: dict = Depends(require_platform_admin),
):
    """Cross-tenant activity feed for a single organization (platform admin view)."""
    org_exists = await conn.execute(
        select(OrganizationModel.id).where(OrganizationModel.id == org_id)
    )
    if org_exists.first() is None:
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


class OrganizationProvision(BaseModel):
    """Same request as the assistant's `/provision`: the original six fields
    still work unchanged; the rest are optional (SS-03)."""

    name: str
    deployment_type: DeploymentType = DeploymentType.SAAS
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


@router.post("/provision", response_model=ProvisionResponse)
async def provision_tenant(
    prov_in: OrganizationProvision,
    conn: AsyncConnection = Depends(get_db_conn),
    _admin: dict = Depends(require_platform_admin),
):
    """Create a company and its owner through the one create-company step
    (application/organizations/create_company). The request's transaction
    (get_db_conn) makes it all-or-nothing."""
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
        deployment_type=prov_in.deployment_type.value,
        db_route=prov_in.db_route,
    )
    try:
        created = await create_company(conn, new, actor=actor_from_admin(_admin))
    except CompanyCreationError as exc:
        raise HTTPException(status_code=409 if exc.conflict else 400, detail=str(exc)) from exc

    return ProvisionResponse(
        id=created.organization_id,
        name=created.name,
        deployment_type=DeploymentType(created.deployment_type),
        db_route=created.db_route,
        status=OrganizationStatus(created.status),
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


@router.post("/{org_id}/seed-finance", response_model=FinanceSeedResponse)
async def seed_organization_finance(
    org_id: uuid.UUID,
    payload: FinanceSeedRequest | None = None,
    conn: AsyncConnection = Depends(get_db_conn),
    admin: dict = Depends(require_platform_admin),
):
    from mesiri.domains.finance.seeder import AdminFinanceSeedingService

    if payload is None:
        payload = FinanceSeedRequest()

    res = await conn.execute(select(OrganizationModel).where(OrganizationModel.id == org_id))
    if not res.scalar_one_or_none():
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
    return FinanceSeedResponse(organization_id=org_id, **stats)
