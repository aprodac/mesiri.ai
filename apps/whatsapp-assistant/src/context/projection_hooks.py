"""Async-safe hooks that keep the context layer in sync with control-plane writes.

Every user/organization/project/site created or updated through the mobile
app or control panel must be projected into ``context_users`` /
``external_identities`` / ``organization_memberships`` / etc. — that's the
data ``context_resolver`` (M4) actually reads when resolving an inbound
WhatsApp message. Without this, a brand-new user is invisible to the
assistant even though the control-plane row exists.

``IdentityProjectionService`` predates the async routers and uses a
synchronous SQLAlchemy engine, so every call here is pushed off the event
loop via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from .identity_projection import EntityType, IdentityProjectionService

if TYPE_CHECKING:
    from mesiri.application.organizations.create_company import CreatedCompany

_log = logging.getLogger("mesiri.context")
_service: IdentityProjectionService | None = None


def _get_service() -> IdentityProjectionService:
    global _service
    if _service is None:
        _service = IdentityProjectionService()
    return _service


async def project_entity(entity_type: EntityType, entity_id: UUID) -> None:
    """Project a single control-plane row into the context layer.

    Best-effort: a projection failure must never fail the request that
    created or updated the underlying row — it only means the WhatsApp
    assistant won't recognize this entity until the next successful
    projection or reconcile.
    """
    try:
        await asyncio.to_thread(_get_service().project_one, entity_type, entity_id)
    except Exception:  # noqa: BLE001
        _log.exception(
            "context.projection_failed entity_type=%s entity_id=%s", entity_type, entity_id
        )


async def project_new_company(created: CreatedCompany) -> None:
    """Project everything the create-company step (SS-03) just committed,
    so the owner's first WhatsApp message is recognised without waiting for
    a reconcile. Shared by the superadmin's /provision and WhatsApp signup."""
    await project_entity("organization", created.organization_id)
    await project_entity("user", created.owner_user_id)
    if created.project_id is not None:
        await project_entity("project", created.project_id)
    if created.site_id is not None:
        await project_entity("site", created.site_id)
    await project_entity("membership", created.owner_user_id)
