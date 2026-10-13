from __future__ import annotations

import datetime as dt
import uuid
from datetime import datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

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
    name: str
    deployment_type: DeploymentType
    db_route: str
    admin_name: str
    admin_email: str
    admin_password: str


@router.post("/provision", response_model=OrganizationResponse)
async def provision_tenant(
    prov_in: OrganizationProvision,
    conn: AsyncConnection = Depends(get_db_conn),
    _admin: dict = Depends(require_platform_admin),
):
    # 1. Create Organization
    stmt_org = (
        insert(OrganizationModel)
        .values(
            name=prov_in.name,
            deployment_type=prov_in.deployment_type,
            db_route=prov_in.db_route,
            status=OrganizationStatus.ACTIVE.value,
        )
        .returning(OrganizationModel)
    )

    result = await conn.execute(stmt_org)
    org_row = result.first()
    if not org_row:
        raise HTTPException(status_code=500, detail="Failed to create organization")
    org = org_row[0]

    # 2. Create Admin User
    from sqlalchemy.exc import IntegrityError

    from mesiri.domains.identity.auth_service import hash_password
    from mesiri.infrastructure.postgres.models.user import UserModel, UserRole

    hashed_pwd = hash_password(prov_in.admin_password)
    stmt_user = insert(UserModel).values(
        organization_id=org.id,
        email=prov_in.admin_email,
        hashed_password=hashed_pwd,
        full_name=prov_in.admin_name,
        role=UserRole.ADMIN,
    )

    try:
        await conn.execute(stmt_user)
    except IntegrityError as exc:
        # Email already exists
        raise HTTPException(status_code=400, detail="Admin email is already registered") from exc

    # 3. Commit transaction (if not auto-commit, but AsyncConnection execution is auto-committed in this context or managed by dependency, assuming managed)
    # Return the created organization
    return org


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


