"""Change a platform-wide setting from the superadmin, recorded (SS-10).

The store and its rules exist already (SS-02:
domains/organizations/platform_settings, repositories/platform_settings);
this adds the audit entry (BE-05) in the same transaction, so a setting is
changed if and only if the change is recorded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mesiri.application.audit.record import record_admin_action
from mesiri.domains.audit import actions as audit
from mesiri.infrastructure.postgres.repositories.platform_settings import (
    PostgresPlatformSettingsRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

    from mesiri.domains.audit.actions import AuditActor


async def update_platform_setting(
    conn: AsyncConnection, key: str, value: dict[str, Any], *, actor: AuditActor
) -> dict[str, Any]:
    """Validate, store and record one setting; returns what was stored.
    Raises KeyError for an unknown key, ValueError for a bad value."""
    repo = PostgresPlatformSettingsRepository(conn)
    before = await repo.get(key)
    after = await repo.set(key, value, updated_by=actor.user_id)
    changed = sorted(k for k in after if before.get(k) != after.get(k))
    await record_admin_action(
        conn,
        actor=actor,
        action=audit.PLATFORM_SETTING_CHANGED,
        target_type="platform_setting",
        target_id=key,
        summary=f"{key}: "
        + (", ".join(f"{k} {before.get(k)} -> {after[k]}" for k in changed) or "no change"),
        details={"before": before, "after": after},
    )
    return after
