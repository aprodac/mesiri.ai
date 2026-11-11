"""PRC-29: the goods received notes page (Procurement > GRN): every GRN the caller can see, newest first, with the
challan photo as a short-lived link. Recording one is "Material came" on the order (``orders_router.receive_order``).

PRC-52: ``POST /procurement/grns/{id}/certificates`` keeps a delivery's quality paper (mill test, cement test, RMC batch /
cube) in the project's documents register (test-reports folder, the supplier and the GRN linked) through the register's
own upload (``documents.router._keep``): same checks, storage and access (D-DOC1). Anyone who can see the GRN may add one.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.materials.router import _resolve_project_ids, _site_filter_denied
from mesiri.domains.procurement import grn as store
from mesiri.domains.procurement.orders_router import with_photo_links
from mesiri.domains.procurement.router import _visible
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri_contracts.common.storage import ObjectStoragePort

router = APIRouter(prefix="/procurement/grns", tags=["procurement"], dependencies=[Depends(require_module("materials"))])


@router.get("")
async def list_grns(
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
):
    project_ids, denied = _resolve_project_ids(auth_context, project_id)
    if denied or _site_filter_denied(auth_context, project_id, site_id):
        return {"items": []}
    items = await store.fetch(conn, auth_context.organization_id, project_ids=project_ids, site_id=site_id)
    items = [g for g in items if _visible(auth_context, uuid.UUID(g["project_id"]), uuid.UUID(g["site_id"]))]
    await with_photo_links(object_storage, items)
    return {"items": items}


@router.post("/{grn_id}/certificates", status_code=201)
async def add_certificate(
    grn_id: uuid.UUID,
    file: UploadFile = File(...),
    kind: str = Form(default="other"),
    number: str | None = Form(default=None, max_length=60),
    batch: str | None = Form(default=None, max_length=60),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
):
    """A certificate that came with the delivery: photo or PDF, its number and the heat / batch number (optional).
    Returns the GRN with its certificates."""
    from mesiri.domains.documents.router import _keep

    if kind not in store.CERTIFICATE_KINDS:
        raise HTTPException(status_code=422, detail=f"kind is one of {', '.join(store.CERTIFICATE_KINDS)}")
    project_ids, denied = _resolve_project_ids(auth_context, None)
    found = [] if denied else await store.fetch(conn, auth_context.organization_id, project_ids=project_ids,
                                                grn_id=grn_id)
    grn = next((g for g in found if _visible(auth_context, uuid.UUID(g["project_id"]), uuid.UUID(g["site_id"]))), None)
    if grn is None:
        raise HTTPException(status_code=404, detail="GRN not found")
    number, batch = (number or "").strip() or None, (batch or "").strip() or None
    items = ", ".join(sorted({line["material"] for line in grn["lines"]}))
    title = f"{store.CERTIFICATE_KINDS[kind]}{f' {number}' if number else ''} · {items} · {grn['ref']}"
    await _keep(conn, auth_context, object_storage, uuid.UUID(grn["project_id"]), file, supersede=None, guess=False,
                given={"folder": "test_report", "title": title, "restricted": False, "vendor_id": uuid.UUID(grn["vendor_id"]),
                       "goods_receipt_id": grn_id, "notes": f"Heat / batch: {batch}" if batch else None})
    out = await store.fetch(conn, auth_context.organization_id, grn_id=grn_id)
    await with_photo_links(object_storage, out)
    return out[0]
