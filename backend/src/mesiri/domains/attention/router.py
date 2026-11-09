"""GM-04: the attention feed API (dashboard Site > Attention, and the assistant's "anything I should know?").

  GET    /attention                 what crossed a line, for this person: bad first; counts (snoozed counted apart)
  GET    /attention/count           just the counts (the sidebar badge)
  POST   /attention/snooze          {key, days 1-7}: not now, until that day (it comes back if still true)
  DELETE /attention/snooze/{key}    bring it back now

Read only, except the person's own snoozes. Rules: ``rules.py``; sources and who sees what: ``feed.py``.
Plan: docs/plans/gm-pm-plan.md (GM-04).
"""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.attention import feed, rules
from mesiri.domains.organizations import settings as org_settings
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import read_enabled_modules
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(prefix="/attention", tags=["attention"])


async def _feed(request: Request, conn: AsyncConnection, auth: AuthorizationContext,
                project_id: uuid.UUID | None) -> dict:
    stored = await read_enabled_modules(request, auth.organization_id)
    enabled = {m for m in org_settings.MODULES if org_settings.module_enabled(m, stored)}
    alerts = await feed.collect(conn, auth, enabled=enabled, project_id=project_id)
    today = (await feed.local_now(conn, auth.organization_id)).date()
    return {"date": today.isoformat(), **rules.arrange(alerts, await feed.snoozed(conn, auth, today))}


@router.get("")
async def attention(
    request: Request,
    project_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """What crossed a line for this person: over budget, late, to order, not reported, issues left open, hire bills
    above the log. Each alert says what, by how much, and the page that acts on it."""
    return await _feed(request, conn, auth_context, project_id)


@router.get("/count")
async def attention_count(
    request: Request,
    project_id: uuid.UUID | None = None,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    return {"counts": (await _feed(request, conn, auth_context, project_id))["counts"]}


class SnoozeIn(BaseModel):
    key: str = Field(min_length=3, max_length=200)
    days: int = Field(default=1, ge=1, le=7)


@router.post("/snooze")
async def snooze(body: SnoozeIn, auth_context: AuthorizationContext = Depends(get_auth_context),
                 conn: AsyncConnection = Depends(get_db_conn)):
    """Not now: hidden for this person until ``days`` from today (the company's day). Back after, if still true."""
    today = (await feed.local_now(conn, auth_context.organization_id)).date()
    until = today + datetime.timedelta(days=body.days - 1)
    await feed.snooze(conn, auth_context, body.key, until)
    return {"key": body.key, "until": until.isoformat()}


@router.delete("/snooze/{key:path}")
async def unsnooze(key: str, auth_context: AuthorizationContext = Depends(get_auth_context),
                   conn: AsyncConnection = Depends(get_db_conn)):
    await feed.unsnooze(conn, auth_context, key)
    return {"key": key}
