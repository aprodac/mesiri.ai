"""GM-01: the "Waiting for you" API (dashboard Site > Approvals, and the assistant's "what is waiting for me?").

  GET /approvals/inbox         every decision waiting for the caller, flagged first, then the oldest; counts per
                               group and kind. ``project_id`` narrows to one project; ``kind`` to some kinds.
  GET /approvals/inbox/count   just the counts (the sidebar badge)

Read only. Each row says which of its module's routes decides it (``actions`` + ``kind``); deciding stays there.
Rules and sources: ``inbox.py``. Plan: docs/plans/gm-pm-plan.md.
"""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.approvals import inbox
from mesiri.domains.organizations import settings as org_settings
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import read_enabled_modules
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _kinds(kind: str | None) -> set[str] | None:
    if not kind:
        return None
    asked = {k.strip() for k in kind.split(",") if k.strip()}
    unknown = asked - set(inbox.KINDS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"kind is one or more of {', '.join(inbox.KINDS)}")
    return asked


async def _arranged(request: Request, conn: AsyncConnection, auth: AuthorizationContext,
                    project_id: uuid.UUID | None, kind: str | None) -> dict:
    kinds = _kinds(kind)
    stored = await read_enabled_modules(request, auth.organization_id)
    enabled = {m for m in org_settings.MODULES if org_settings.module_enabled(m, stored)}
    rows = await inbox.collect(conn, auth, enabled=enabled, project_id=project_id, kinds=kinds)
    return inbox.arrange(rows, datetime.datetime.now(datetime.UTC))


@router.get("/inbox")
async def waiting_for_me(
    request: Request,
    project_id: uuid.UUID | None = None,
    kind: str | None = Query(default=None, description="Comma-separated: " + ", ".join(inbox.KINDS)),
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """What is waiting for this person's decision, each row with the one fact that decides it."""
    return await _arranged(request, conn, auth_context, project_id, kind)


@router.get("/inbox/count")
async def waiting_count(
    request: Request,
    project_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    return {"counts": (await _arranged(request, conn, auth_context, project_id, None))["counts"]}
