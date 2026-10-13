"""GET /media/{key} -- serves stored media through a signed, expiring link (INF-09).

Only used when media is kept on this server's disk (object storage provider
``local``). Every other provider hands out its own URLs, so this route answers
404 for them. The link itself is the permission: it is issued by an endpoint
that already checked the caller, exactly like an R2 presigned URL, so the route
takes no login.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from mesiri_contracts.common.errors import MesiriError
from mesiri_contracts.common.storage import ObjectStoragePort

from ...bootstrap.settings import ObjectStorageProvider, get_settings
from ...infrastructure.objectstorage.dependency import get_object_storage
from ...infrastructure.objectstorage.local_disk import verify_signature

router = APIRouter(tags=["media"])


@router.get("/media/{key:path}")
async def get_media(
    key: str,
    exp: int = Query(...),
    sig: str = Query(...),
    object_storage: ObjectStoragePort = Depends(get_object_storage),
) -> Response:
    settings = get_settings().object_storage
    if settings.provider is not ObjectStorageProvider.LOCAL:
        raise HTTPException(status_code=404, detail="Not found")
    if not verify_signature(settings, key, exp, sig):
        raise HTTPException(status_code=403, detail="This link has expired or is not valid.")
    try:
        stored = await object_storage.get_object(key)
    except MesiriError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    return Response(
        content=stored.data,
        media_type=stored.content_type or "application/octet-stream",
        # The link expires; the browser may keep the bytes until then, not longer.
        headers={"Cache-Control": "private, max-age=900"},
    )
