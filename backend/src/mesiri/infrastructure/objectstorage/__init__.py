"""Object-storage adapters and factory (M1).

Concrete implementations of the :class:`ObjectStoragePort` contract. This is the
only package permitted to touch the R2/S3 SDK, buckets, keys, or signed URLs.
"""

from __future__ import annotations

from mesiri_contracts.common.storage import ObjectStoragePort

from ...bootstrap.settings import ObjectStorageProvider, Settings
from .fake import FakeObjectStorage

__all__ = ["FakeObjectStorage", "build_object_storage"]


def build_object_storage(settings: Settings) -> ObjectStoragePort:
    """Select the object-storage adapter from configuration.

    Local/test use the in-process fake; ``r2`` selects the Cloudflare R2 adapter
    (imported lazily so boto3 is only required for that lane); ``local`` keeps
    files on this server's disk.
    """
    provider = settings.object_storage.provider
    if provider is ObjectStorageProvider.FAKE:
        return FakeObjectStorage()
    if provider is ObjectStorageProvider.R2:
        from .r2 import R2ObjectStorage

        return R2ObjectStorage(settings.object_storage)
    if provider is ObjectStorageProvider.LOCAL:
        from .local_disk import LocalDiskObjectStorage

        return LocalDiskObjectStorage(settings.object_storage)
    raise ValueError(f"unknown object storage provider: {provider}")
