"""Guard against a misconfigured object-storage adapter leaking into responses.

The local/test fake adapter (`FakeObjectStorage`) returns `memory://...`
links instead of real downloadable URLs -- fine in-process, but if it is
ever selected in a production-like deployment (e.g. the provider env var
was never set), every attachment/photo URL silently becomes unusable and
the only visible symptom is a browser console `ERR_UNKNOWN_URL_SCHEME` on
an otherwise-normal-looking API response. `Settings.validate_runtime()` is
meant to refuse to boot in that situation, but this is a second, independent
check at the point the URL actually leaves the backend -- so a gap in that
guard surfaces as a clear 500 with a diagnosable message, not a silently
broken image.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

from mesiri_contracts.common.storage import ObjectStoragePort

logger = logging.getLogger(__name__)


def assert_downloadable_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        logger.error(
            "object storage returned a non-downloadable URL scheme (%r) -- "
            "the configured provider cannot be used outside local/test",
            url.split(":", 1)[0],
        )
        raise HTTPException(
            status_code=500,
            detail="Media storage is not configured for this environment.",
        )
    return url


MEDIA_URL_TTL_SECONDS = 600


async def signed_media_url(object_storage: ObjectStoragePort, key: str | None) -> str | None:
    """A short-lived link to a stored photo/voice note, or None when storage
    can't give one (the caller then shows the item without it). Shared by the
    DPR sources panel and the site gallery (WEB-24)."""
    if not key:
        return None
    try:
        return assert_downloadable_url(
            await object_storage.generate_presigned_url(key, expires_in_seconds=MEDIA_URL_TTL_SECONDS)
        )
    except Exception:  # noqa: BLE001 -- one missing photo must not hide the rest
        logger.warning("media.url_unavailable key=%s", key)
        return None
