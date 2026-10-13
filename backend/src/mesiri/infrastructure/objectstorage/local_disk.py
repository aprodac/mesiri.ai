"""Local-disk object-storage adapter (INF-09).

Keeps media as plain files under one directory on the VPS, for a single-server
deployment that does not want a cloud bucket. Chosen 13 Oct 2026 over R2; R2
stays selectable by setting, so moving later is a configuration change.

Files cannot be handed to a browser directly, so ``generate_presigned_url``
returns a link to the app's own ``GET /media/...`` route, signed with an HMAC
and an expiry, the same shape as an R2 presigned URL. ``verify_signature`` is
what that route uses to check it.

Keys come from our own code, but they are still checked so no key can resolve
outside the media directory.

Operational note: these files exist only on this server. The nightly off-server
backup (INF-06) must copy the media directory as well as the database.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
from pathlib import Path
from urllib.parse import quote, urlencode

from mesiri_contracts.common.errors import ErrorCategory, ErrorCode, MesiriError
from mesiri_contracts.common.storage import ObjectMetadata, StoredObject

from ...bootstrap.settings import ObjectStorageSettings
from ..errors import map_object_storage_error

# Content type is kept beside each file rather than guessed from the key:
# keys are not guaranteed to carry an extension.
_TYPE_SUFFIX = ".content-type"
_PARTIAL_SUFFIX = ".partial"


def _not_found(key: str) -> MesiriError:
    return MesiriError(
        error_code=ErrorCode.OBJECT_STORAGE_UNAVAILABLE.value,
        category=ErrorCategory.NOT_FOUND,
        retryable=False,
        user_safe_message="The requested media could not be found.",
        internal_message=f"object not found: {key}",
    )


def _sign(secret: bytes, key: str, expires_at: int) -> str:
    return hmac.new(secret, f"{key}\n{expires_at}".encode(), hashlib.sha256).hexdigest()


class LocalDiskObjectStorage:
    name = "object_storage"
    required = True

    def __init__(self, settings: ObjectStorageSettings) -> None:
        if not settings.signing_secret or not settings.signing_secret.get_secret_value():
            raise MesiriError.configuration(
                "MESIRI_OBJECT_STORAGE__SIGNING_SECRET is required for local media storage",
                code=ErrorCode.CONFIG_MISSING.value,
            )
        if not settings.public_base_url:
            raise MesiriError.configuration(
                "MESIRI_OBJECT_STORAGE__PUBLIC_BASE_URL is required for local media storage",
                code=ErrorCode.CONFIG_MISSING.value,
            )
        self._root = Path(settings.local_root).resolve()
        self._secret = settings.signing_secret.get_secret_value().encode()
        self._base_url = settings.public_base_url.rstrip("/")

    def _path(self, key: str) -> Path:
        if not key or key.startswith("/") or "\\" in key or "\x00" in key:
            raise _not_found(key)
        path = (self._root / key).resolve()
        if path == self._root or self._root not in path.parents:
            raise _not_found(key)
        if path.name.endswith((_TYPE_SUFFIX, _PARTIAL_SUFFIX)):
            raise _not_found(key)
        return path

    async def _call(self, fn, *args):  # noqa: ANN001, ANN202 — thin thread hop
        try:
            return await asyncio.to_thread(fn, *args)
        except MesiriError:
            raise
        except FileNotFoundError as exc:
            raise _not_found(str(args[0]) if args else "") from exc
        except Exception as exc:  # noqa: BLE001 — mapped to the shared contract
            raise map_object_storage_error(exc) from exc

    # -- sync bodies, run in a thread ------------------------------------

    def _write(self, key: str, data: bytes, content_type: str | None) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename, so a reader never sees half a photo.
        tmp = path.with_name(path.name + _PARTIAL_SUFFIX)
        tmp.write_bytes(data)
        os.replace(tmp, path)
        type_file = path.with_name(path.name + _TYPE_SUFFIX)
        if content_type:
            type_file.write_text(content_type)
        else:
            type_file.unlink(missing_ok=True)

    def _content_type(self, path: Path) -> str | None:
        type_file = path.with_name(path.name + _TYPE_SUFFIX)
        try:
            return type_file.read_text().strip() or None
        except FileNotFoundError:
            return None

    def _read(self, key: str) -> StoredObject:
        path = self._path(key)
        if not path.is_file():
            raise _not_found(key)
        return StoredObject(key=key, data=path.read_bytes(), content_type=self._content_type(path))

    def _stat(self, key: str) -> ObjectMetadata:
        path = self._path(key)
        if not path.is_file():
            raise _not_found(key)
        return ObjectMetadata(
            key=key, size_bytes=path.stat().st_size, content_type=self._content_type(path)
        )

    def _remove(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        path.with_name(path.name + _TYPE_SUFFIX).unlink(missing_ok=True)

    def _probe(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        if not os.access(self._root, os.W_OK):
            raise PermissionError(f"media directory is not writable: {self._root}")

    # -- ObjectStoragePort ------------------------------------------------

    async def put_object(
        self, key: str, data: bytes, *, content_type: str | None = None
    ) -> ObjectMetadata:
        await self._call(self._write, key, bytes(data), content_type)
        return ObjectMetadata(key=key, size_bytes=len(data), content_type=content_type)

    async def get_object(self, key: str) -> StoredObject:
        return await self._call(self._read, key)

    async def head_object(self, key: str) -> ObjectMetadata:
        return await self._call(self._stat, key)

    async def delete_object(self, key: str) -> None:
        await self._call(self._remove, key)

    async def generate_presigned_url(
        self, key: str, *, expires_in_seconds: int = 900, method: str = "GET"
    ) -> str:
        if method.upper() != "GET":
            # Uploads go through the app, never straight from a browser.
            raise MesiriError.configuration(
                "local media storage only issues download links",
                code=ErrorCode.CONFIG_MISSING.value,
            )
        self._path(key)
        expires_at = int(time.time()) + int(expires_in_seconds)
        query = urlencode({"exp": expires_at, "sig": _sign(self._secret, key, expires_at)})
        return f"{self._base_url}/media/{quote(key)}?{query}"

    async def check_health(self) -> None:
        await self._call(self._probe)

    async def health_check(self) -> None:
        await self.check_health()


def verify_signature(
    settings: ObjectStorageSettings, key: str, expires_at: int, signature: str
) -> bool:
    """True when ``signature`` is a live download link for ``key``.

    A module function rather than a method so the ``/media`` route can check a
    link from settings alone, whichever wrapper the process put around the store.
    """
    secret = settings.signing_secret.get_secret_value() if settings.signing_secret else ""
    if not secret or expires_at < int(time.time()):
        return False
    return hmac.compare_digest(_sign(secret.encode(), key, expires_at), signature)
