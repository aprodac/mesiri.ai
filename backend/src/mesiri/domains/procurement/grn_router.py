"""PRC-29: the goods received notes page (Procurement > GRN): every GRN the caller can see, newest first, with the
challan photo as a short-lived link. Recording one is "Material came" on the order (``orders_router.receive_order``).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
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
