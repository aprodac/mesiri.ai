"""The control panel's Overview (SA-18): GET /admin/overview, everything the
super admin's morning screen shows in one read -- see
application/organizations/platform_overview.py. Read-only.

One router, mounted by both apps (backend http/app.py and the assistant's
runtime/lifecycle.py), like the costs router. Gated by
require_platform_admin: it spans every company.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.organizations.platform_overview import platform_overview
from mesiri.domains.shared.auth import require_platform_admin
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview")
async def get_overview(
    _admin: dict = Depends(require_platform_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Status, what needs attention, today, companies, onboarding funnel,
    14-day activity, cost, and the most active and gone-quiet companies."""
    return await platform_overview(conn)
