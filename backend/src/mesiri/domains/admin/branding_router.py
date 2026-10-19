"""Branding requests and a company's letterhead and details, for the control
panel (SA-09, SA-03).

The owner sends letterhead / visiting card / logo photos on WhatsApp (SS-14);
the Mesiri team sees them here next to the letterhead form, fills it in,
uploads the logo, and marks the request done. The assistant then tells the
owner on their next message. Nothing here sends WhatsApp messages.

One router, mounted by both apps (backend http/app.py and the assistant's
runtime/lifecycle.py), like the dashboard's /company router, so there is no
second copy to keep in step. The logic is application/organizations/
branding_admin, shared with the dashboard's own /company/branding routes.
Every change is recorded in the audit log (BE-05) in the same transaction.
Gated by require_platform_admin on every route.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.audit.record import record_admin_action
from mesiri.application.organizations import branding_admin
from mesiri.domains.audit import actions as audit
from mesiri.domains.audit.actions import actor_from_admin
from mesiri.domains.shared.auth import require_platform_admin
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri_contracts.common.storage import ObjectStoragePort

router = APIRouter(prefix="/admin", tags=["admin"])


class BrandingRequestFile(BaseModel):
    index: int
    content_type: str | None = None
    received_at: str | None = None


class BrandingRequestResponse(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    id: str
    status: str
    created_at: str | None = None
    done_at: str | None = None
    owner_notified: bool = False
    file_count: int
    files: list[BrandingRequestFile] = []


class LetterheadResponse(BaseModel):
    company_name: str
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    letterhead_name: str | None = None
    brand_color: str | None = None
    gstin: str | None = None
    signatory_name: str | None = None
    signatory_designation: str | None = None
    has_logo: bool = False
    logo_url: str | None = None


class CompanyBrandingResponse(BaseModel):
    letterhead: LetterheadResponse
    requests: list[BrandingRequestResponse]


class LogoUpload(BaseModel):
    content_type: str
    # The image file, base64-encoded (same as the dashboard's upload).
    data_base64: str


def _request_response(item: branding_admin.BrandingRequestItem) -> BrandingRequestResponse:
    return BrandingRequestResponse(
        organization_id=item.organization_id,
        organization_name=item.organization_name,
        id=item.id,
        status=item.status,
        created_at=item.created_at,
        done_at=item.done_at,
        owner_notified=item.owner_notified,
        file_count=item.file_count,
        files=[
            BrandingRequestFile(
                index=i, content_type=f.get("content_type"), received_at=f.get("received_at")
            )
            for i, f in enumerate(item.files)
        ],
    )


def _admin_id(admin: dict) -> uuid.UUID | None:
    return actor_from_admin(admin).user_id


async def _company_name(conn: AsyncConnection, org_id: uuid.UUID) -> str:
    name = (
        await conn.execute(sa.text("SELECT name FROM organizations WHERE id = :id"), {"id": org_id})
    ).scalar_one_or_none()
    if name is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return name


async def _company_branding(
    conn: AsyncConnection, storage: ObjectStoragePort, org_id: uuid.UUID
) -> CompanyBrandingResponse:
    view = await branding_admin.branding_view(conn, storage, org_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    items = await branding_admin.company_branding_requests(conn, org_id, view["company_name"])
    return CompanyBrandingResponse(
        letterhead=LetterheadResponse(**view),
        requests=[_request_response(i) for i in items],
    )


async def _record(
    conn: AsyncConnection, admin: dict, org_id: uuid.UUID, summary: str, details: dict[str, Any]
) -> None:
    await record_admin_action(
        conn,
        actor=actor_from_admin(admin),
        action=audit.COMPANY_SETTING_CHANGED,
        organization_id=org_id,
        target_type="organization",
        target_id=org_id,
        summary=summary,
        details=details,
    )


@router.get("/branding-requests", response_model=list[BrandingRequestResponse])
async def list_branding_requests(
    conn: AsyncConnection = Depends(get_db_conn),
    _admin: dict = Depends(require_platform_admin),
):
    """Every company's branding requests: open ones first, oldest first."""
    return [_request_response(i) for i in await branding_admin.list_branding_requests(conn)]


@router.get("/organizations/{org_id}/branding", response_model=CompanyBrandingResponse)
async def get_company_branding(
    org_id: uuid.UUID,
    conn: AsyncConnection = Depends(get_db_conn),
    storage: ObjectStoragePort = Depends(get_object_storage),
    _admin: dict = Depends(require_platform_admin),
):
    """The company's letterhead and its branding requests."""
    return await _company_branding(conn, storage, org_id)


@router.put("/organizations/{org_id}/branding", response_model=CompanyBrandingResponse)
async def update_company_branding(
    org_id: uuid.UUID,
    body: dict,
    conn: AsyncConnection = Depends(get_db_conn),
    storage: ObjectStoragePort = Depends(get_object_storage),
    _admin: dict = Depends(require_platform_admin),
):
    """Change letterhead fields (letterhead name, brand colour, GSTIN,
    signatory) and the company's address / phone / email. Fields left out
    stay as they are."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Expected an object")
    await _company_name(conn, org_id)
    text_part = {k: v for k, v in body.items() if k not in branding_admin.CONTACT_FIELDS}
    try:
        contact = branding_admin.validate_contact(body)
        changes = (
            await branding_admin.update_branding_text(
                conn, org_id, text_part, updated_by=_admin_id(_admin)
            )
            if text_part
            else {}
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await branding_admin.update_contact(conn, org_id, contact)
    changed = sorted({**changes, **contact})
    if changed:
        await _record(
            conn,
            _admin,
            org_id,
            f"Letterhead updated: {', '.join(changed)}",
            {"after": {**changes, **contact}},
        )
    return await _company_branding(conn, storage, org_id)


class CompanyDetailsResponse(BaseModel):
    id: uuid.UUID
    name: str
    primary_contact: str | None = None


async def _details(conn: AsyncConnection, org_id: uuid.UUID) -> CompanyDetailsResponse:
    row = (
        await conn.execute(
            sa.text("SELECT id, name, primary_contact FROM organizations WHERE id = :id"),
            {"id": org_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return CompanyDetailsResponse(**row)


@router.get("/organizations/{org_id}/details", response_model=CompanyDetailsResponse)
async def get_company_details(
    org_id: uuid.UUID,
    conn: AsyncConnection = Depends(get_db_conn),
    _admin: dict = Depends(require_platform_admin),
):
    """The company's name and primary contact, for the edit form (SA-03)."""
    return await _details(conn, org_id)


@router.patch("/organizations/{org_id}/details", response_model=CompanyDetailsResponse)
async def update_company_details(
    org_id: uuid.UUID,
    body: dict,
    conn: AsyncConnection = Depends(get_db_conn),
    _admin: dict = Depends(require_platform_admin),
):
    """Rename the company or change its primary contact (SA-03). Fields left
    out stay as they are; the change is recorded in the audit log with its
    before and after."""
    try:
        changes = branding_admin.validate_details(body)
        changed = await branding_admin.update_details(conn, org_id, changes)
    except branding_admin.BrandingAdminError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if changed:
        await record_admin_action(
            conn,
            actor=actor_from_admin(_admin),
            action=audit.COMPANY_UPDATED,
            organization_id=org_id,
            target_type="organization",
            target_id=org_id,
            summary=f"Company details updated: {', '.join(sorted(changed))}",
            details={"changes": changed},
        )
    return await _details(conn, org_id)


@router.put("/organizations/{org_id}/branding/logo", response_model=CompanyBrandingResponse)
async def upload_company_logo(
    org_id: uuid.UUID,
    body: LogoUpload,
    background: BackgroundTasks,
    conn: AsyncConnection = Depends(get_db_conn),
    storage: ObjectStoragePort = Depends(get_object_storage),
    _admin: dict = Depends(require_platform_admin),
):
    """Upload or replace the company logo (PNG, JPEG or WebP, up to 700 KB),
    the same rules as the dashboard's upload."""
    await _company_name(conn, org_id)
    try:
        old = await branding_admin.replace_logo(
            conn,
            storage,
            org_id,
            data_base64=body.data_base64,
            content_type=body.content_type,
            updated_by=_admin_id(_admin),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _record(conn, _admin, org_id, "Letterhead logo uploaded", {"replaced": bool(old)})
    if old:
        background.add_task(branding_admin.remove_file, storage, old)
    return await _company_branding(conn, storage, org_id)


@router.delete("/organizations/{org_id}/branding/logo", response_model=CompanyBrandingResponse)
async def remove_company_logo(
    org_id: uuid.UUID,
    background: BackgroundTasks,
    conn: AsyncConnection = Depends(get_db_conn),
    storage: ObjectStoragePort = Depends(get_object_storage),
    _admin: dict = Depends(require_platform_admin),
):
    await _company_name(conn, org_id)
    old = await branding_admin.set_logo_key(conn, org_id, None, updated_by=_admin_id(_admin))
    await _record(conn, _admin, org_id, "Letterhead logo removed", {})
    if old:
        background.add_task(branding_admin.remove_file, storage, old)
    return await _company_branding(conn, storage, org_id)


@router.get("/organizations/{org_id}/branding-requests/{request_id}/files/{index}")
async def get_branding_request_file(
    org_id: uuid.UUID,
    request_id: str,
    index: int,
    conn: AsyncConnection = Depends(get_db_conn),
    storage: ObjectStoragePort = Depends(get_object_storage),
    _admin: dict = Depends(require_platform_admin),
):
    """One photo the owner sent, by its position in the request. 404 "File
    no longer available" when storage has lost it."""
    try:
        obj, content_type = await branding_admin.request_file(
            conn, storage, org_id, request_id, index
        )
    except branding_admin.BrandingAdminError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(
        content=obj.data,
        media_type=obj.content_type or content_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=300"},
    )


class RequestDoneResponse(BaseModel):
    id: str
    status: str
    done_at: datetime | None = None


@router.post(
    "/organizations/{org_id}/branding-requests/{request_id}/done",
    response_model=RequestDoneResponse,
)
async def mark_branding_request_done(
    org_id: uuid.UUID,
    request_id: str,
    conn: AsyncConnection = Depends(get_db_conn),
    _admin: dict = Depends(require_platform_admin),
):
    """The letterhead is set up: mark the request done. The assistant tells
    the owner on their next message (it sets owner_notified itself)."""
    name = await _company_name(conn, org_id)
    try:
        done = await branding_admin.mark_request_done(
            conn, org_id, request_id, updated_by=_admin_id(_admin)
        )
    except branding_admin.BrandingAdminError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    await _record(
        conn,
        _admin,
        org_id,
        f"{name}: branding request done",
        {"request_id": request_id, "files": len(done.get("files") or [])},
    )
    return RequestDoneResponse(id=done["id"], status=done["status"], done_at=done["done_at"])
