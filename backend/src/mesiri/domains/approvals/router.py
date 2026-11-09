"""REST API for the approvals inbox (NXT-08). Read only; acting stays on each module's own route.

  GET /approvals/waiting    everything waiting for me: items (urgent first, then oldest), counts per kind, total

Used by the dashboard's bell (top bar) and by the WhatsApp assistant ("what is waiting for me?", tool ``waiting``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.approvals import inbox
from mesiri.domains.organizations import settings as org_settings
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import read_enabled_modules
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("/waiting")
async def waiting(
    request: Request,
    kind: str | None = Query(default=None, description="Only these kinds, comma separated: site_report, "
                                                        "material_request, subcontract_bill, ra_bill, task"),
    limit: int = Query(default=100, ge=1, le=300, description="At most this many items (the counts are all of them)"),
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
) -> dict[str, Any]:
    """What is waiting for me: site reports to confirm, material requests to decide, subcontractor bills to approve,
    RA bills in draft, my tasks overdue or due today. Each item names its kind, project, site and how long it has
    waited; urgent ones first."""
    kinds = inbox.KINDS
    if kind:
        kinds = tuple(k for k in (w.strip() for w in kind.split(",")) if k in inbox.KINDS) or inbox.KINDS
    stored = await read_enabled_modules(request, auth.organization_id)
    result = await inbox.waiting(conn, auth, lambda m: org_settings.module_enabled(m, stored), kinds)
    result["items"] = result["items"][:limit]
    return result
