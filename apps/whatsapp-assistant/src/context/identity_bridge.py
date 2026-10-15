"""M6.5 identity bridge — deterministic context IDs and canonical lookups."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID, uuid5


def context_organization_id(canonical_id: UUID) -> str:
    return f"ctx_org_{canonical_id}"


def context_user_id(canonical_id: UUID) -> str:
    return f"ctx_user_{canonical_id}"


def context_project_id(canonical_id: UUID) -> str:
    return f"ctx_proj_{canonical_id}"


def context_site_id(canonical_id: UUID) -> str:
    return f"ctx_site_{canonical_id}"


class IdentityBridgeRepository(Protocol):
    async def canonical_organization_id(self, context_organization_id: str) -> str | None: ...

    async def canonical_user_id(self, context_user_id: str) -> str | None: ...

    async def canonical_project_id(self, context_project_id: str) -> str | None: ...

    async def canonical_site_id(self, context_site_id: str) -> str | None: ...


FAKE_BRIDGE_NAMESPACE = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def deterministic_canonical_uuid(context_id: str) -> str:
    """Deterministic canonical UUID for a context id (matches FakeIdentityBridgeRepository)."""
    return str(uuid5(FAKE_BRIDGE_NAMESPACE, context_id))


class FakeIdentityBridgeRepository:
    """Deterministic canonical UUID mapping for unit tests (uuid5 per context id)."""

    _NAMESPACE = FAKE_BRIDGE_NAMESPACE

    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        self._overrides = overrides or {}

    def _canonical(self, context_id: str) -> str:
        if context_id in self._overrides:
            return self._overrides[context_id]
        return deterministic_canonical_uuid(context_id)

    async def canonical_organization_id(self, context_organization_id: str) -> str | None:
        return self._canonical(context_organization_id)

    async def canonical_user_id(self, context_user_id: str) -> str | None:
        return self._canonical(context_user_id)

    async def canonical_project_id(self, context_project_id: str) -> str | None:
        return self._canonical(context_project_id)

    async def canonical_site_id(self, context_site_id: str) -> str | None:
        return self._canonical(context_site_id)


def build_fake_bridge_from_seed() -> FakeIdentityBridgeRepository:
    """Return a fake bridge; seed context ids map deterministically via uuid5."""
    return FakeIdentityBridgeRepository()
