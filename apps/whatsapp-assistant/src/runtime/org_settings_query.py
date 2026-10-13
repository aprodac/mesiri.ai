"""Per-organization settings read service (wiring layer only).

Same shape and justification as runtime/material_catalog_query.py: adapts
the backend's PostgresOrganizationSettingsRepository into plain async
methods the inbound journey's gates can call, without the WhatsApp
assistant depending on backend infrastructure anywhere outside runtime/.

Read-only by design — settings are changed from the control panel, never
from a WhatsApp message.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase

_log = logging.getLogger("mesiri.org_settings")


class OrganizationSettingsQueryService:
    """Read-only: never opens a write transaction, never mutates state."""

    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def get(self, *, organization_id: str, key: str) -> Any:
        """The org's value for `key`, falling back to the spec default when
        unset (the repository already handles that) and *also* when the
        lookup itself fails.

        Never raises: this runs inside the inbound journey, where an
        exception costs the user their whole reply. Degrading to the
        documented default is the same fail-safe choice the material/unit
        gates make on a catalog lookup failure.
        """
        from mesiri.domains.organizations import settings as settings_spec
        from mesiri.infrastructure.postgres.repositories.organization_settings import (
            PostgresOrganizationSettingsRepository,
        )

        try:
            async with self._db.transaction() as conn:
                repo = PostgresOrganizationSettingsRepository(conn)
                return await repo.get(uuid.UUID(organization_id), key)
        except Exception:
            _log.exception("org_settings.lookup_failed org=%s key=%s", organization_id, key)
            try:
                return settings_spec.default_for(key)
            except KeyError:
                return None

    async def enabled_modules(self, *, organization_id: str) -> list[str]:
        """The company's switched-on modules (BE-06 / WA-07), canonical and
        defaulted. Never raises, for the same reason as get()."""
        from mesiri.domains.organizations import settings as settings_spec

        stored = await self.get(organization_id=organization_id, key=settings_spec.ENABLED_MODULES)
        return settings_spec.enabled_modules(stored)
