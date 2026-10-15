"""Platform-wide settings for the control panel (SS-10).

Trial length, how long an expired trial's data is kept, and whether
self-serve signup is switched on. The rules and the store are SS-02's
(domains/organizations/platform_settings); every change is recorded in the
audit log in the same transaction (application/organizations/
platform_settings_admin). Gated by require_platform_admin on every route.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from admin.router import get_engine
from mesiri.application.organizations.platform_settings_admin import update_platform_setting
from mesiri.domains.audit.actions import actor_from_admin
from mesiri.domains.organizations import platform_settings as spec
from mesiri.domains.shared.auth import require_platform_admin
from mesiri.infrastructure.postgres.repositories.platform_settings import (
    PostgresPlatformSettingsRepository,
)

router = APIRouter(prefix="/admin/platform-settings", tags=["admin"])


@router.get("")
async def list_platform_settings(
    _admin: dict = Depends(require_platform_admin),
) -> dict[str, dict[str, Any]]:
    """Every platform setting, defaults filled in, with what it is for."""
    async with get_engine().connect() as conn:
        values = await PostgresPlatformSettingsRepository(conn).get_all()
    return {
        s.key: {"value": values[s.key], "default": dict(s.default), "description": s.description}
        for s in spec.all_specs()
    }


@router.put("/{key}")
async def update_platform_setting_route(
    key: str, value: dict[str, Any], _admin: dict = Depends(require_platform_admin)
) -> dict[str, Any]:
    """Change one setting (the whole object or some of its fields); returns
    what was stored."""
    if not spec.is_known_key(key):
        raise HTTPException(status_code=404, detail=f"Unknown platform setting: {key}")
    try:
        async with get_engine().begin() as conn:  # commits, or rolls back on error
            stored = await update_platform_setting(conn, key, value, actor=actor_from_admin(_admin))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"key": key, "value": stored}
