"""The site photos printed on a DPR (PHO-02, audit 07).

The document showed a photo count and a column of numbers, never a picture.
Each work item's photos are embedded as small data URIs, as the letterhead
logo is, so the headless browser fetches nothing over the network: a grid of
at most ``MAX_THUMBS`` per work item, and "N more" for the rest.

A photo that cannot be read is left out; it never stops a report.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Photos shown per work item; the rest are counted ("+ 4 more").
MAX_THUMBS = 6
#: The longest side of a thumbnail, in pixels (a 2-3 MB phone photo becomes ~15 KB).
THUMB_SIDE = 360
_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
#: Without Pillow an original is embedded only when it is already small.
_MAX_RAW_BYTES = 200_000


def _thumbnail(data: bytes, content_type: str) -> str | None:
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((THUMB_SIDE, THUMB_SIDE))
            out = io.BytesIO()
            image.save(out, "JPEG", quality=72, optimize=True)
        return f"data:image/jpeg;base64,{base64.b64encode(out.getvalue()).decode()}"
    except ImportError:
        if len(data) > _MAX_RAW_BYTES:
            return None
        return f"data:{content_type};base64,{base64.b64encode(data).decode()}"
    except Exception:  # noqa: BLE001 -- an unreadable picture is left out
        return None


async def embed_photos(object_storage: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """A copy of the SITE payload whose work items carry ``thumbs`` (data URIs)
    and ``photos_more``. The stored payload is not changed: the pictures are
    read at render time, so a version stays small."""
    if object_storage is None or not payload.get("activities"):
        return payload
    activities = []
    for activity in payload["activities"]:
        photos = list(activity.get("photos") or [])
        thumbs: list[str] = []
        for photo in photos[:MAX_THUMBS]:
            key = photo.get("object_key")
            if not key:
                continue
            try:
                stored = await object_storage.get_object(key)
            except Exception:  # noqa: BLE001 -- a lost photo must not stop the report
                logger.warning("dpr_photos.unreadable key=%s", key, exc_info=True)
                continue
            content_type = (getattr(stored, "content_type", None) or photo.get("mime_type") or "").lower()
            if content_type not in _IMAGE_TYPES or not getattr(stored, "data", None):
                continue
            uri = _thumbnail(stored.data, content_type)
            if uri:
                thumbs.append(uri)
        count = int(activity.get("evidence_count") or len(photos))
        activities.append({**activity, "thumbs": thumbs, "photos_more": max(count - len(thumbs), 0)})
    return {**payload, "activities": activities}
