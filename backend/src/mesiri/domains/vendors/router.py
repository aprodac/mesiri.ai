from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.vendors import PostgresVendorRepository

router = APIRouter(
    prefix="/finance/vendors",
    tags=["vendors"],
    dependencies=[Depends(require_module("finance"))],
)


class VendorResponse(BaseModel):
    id: uuid.UUID
    name: str
    code: str | None = None
    status: str
    expense_count: int = 0
    total_amount_paid: Decimal = Decimal("0")


class CreateVendorRequest(BaseModel):
    name: str


class UpdateVendorRequest(BaseModel):
    name: str | None = None
    status: str | None = None


@router.get("", response_model=list[VendorResponse])
async def list_vendors(
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """List all vendors for the organization with live disbursement metrics."""
    repo = PostgresVendorRepository(conn)
    metrics = await repo.list_with_metrics(auth_context.organization_id)
    return [
        VendorResponse(
            id=m["vendor"].id,
            name=m["vendor"].name,
            code=m["vendor"].code,
            status=m["vendor"].status,
            expense_count=m["expense_count"],
            total_amount_paid=m["total_amount"],
        )
        for m in metrics
    ]


@router.post("", response_model=VendorResponse, status_code=201)
async def create_vendor(
    body: CreateVendorRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Create a new vendor in the organization."""
    repo = PostgresVendorRepository(conn)
    existing = await repo.find_by_name_exact_active(auth_context.organization_id, body.name)
    if existing:
        raise HTTPException(status_code=409, detail="Vendor with this name already exists")
    vendor = await repo.create(
        organization_id=auth_context.organization_id,
        name=body.name.strip(),
        created_by=auth_context.user_id,
    )
    return VendorResponse(
        id=vendor.id,
        name=vendor.name,
        code=vendor.code,
        status=vendor.status,
        expense_count=0,
        total_amount_paid=Decimal("0"),
    )


@router.patch("/{vendor_id}", response_model=VendorResponse)
async def update_vendor(
    vendor_id: uuid.UUID,
    body: UpdateVendorRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Update vendor name or active/inactive status."""
    repo = PostgresVendorRepository(conn)
    vendor = await repo.get_by_id(auth_context.organization_id, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    updated = await repo.update(
        organization_id=auth_context.organization_id,
        vendor_id=vendor_id,
        name=body.name,
        status=body.status,
        updated_by=auth_context.user_id,
    )
    assert updated is not None
    return VendorResponse(
        id=updated.id,
        name=updated.name,
        status=updated.status,
        expense_count=0,
        total_amount_paid=Decimal("0"),
    )
