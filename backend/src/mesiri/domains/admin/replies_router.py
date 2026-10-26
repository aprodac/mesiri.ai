"""Reply Insights for the control panel (SA-17): how fast each WhatsApp
message was answered and the AI tokens it took, across every company.

Reads through PostgresReplyUsageRepository (no SQL here): an overview (reply
time, speed bands, tokens, a trend and where the tokens go), the message
feed, and one message's AI calls. Read-only.

One router, mounted by both apps (backend http/app.py and the assistant's
runtime/lifecycle.py), like the costs router. Gated by
require_platform_admin: it shows every company's messages.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.admin.costs_router import _plain
from mesiri.domains.shared.auth import require_platform_admin
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.reply_usage import (
    BANDS_MS,
    PostgresReplyUsageRepository,
)

router = APIRouter(prefix="/admin/replies", tags=["admin"])

#: Longest window: 30 days.
_MAX_MINUTES = 30 * 24 * 60


def step_for(minutes: int) -> dt.timedelta:
    """The trend's bucket size: about 12-30 points whatever the window."""
    for upto, step in ((60, 5), (360, 15), (1440, 60), (10080, 360)):
        if minutes <= upto:
            return dt.timedelta(minutes=step)
    return dt.timedelta(days=1)


def _scope(since_minutes: int, organization_id: uuid.UUID | None, message_type: str | None):
    until = dt.datetime.now(dt.UTC)
    return {
        "since": until - dt.timedelta(minutes=since_minutes),
        "until": until,
        "organization_id": organization_id,
        "message_type": message_type or None,
    }


Window = Query(default=1440, ge=5, le=_MAX_MINUTES)


@router.get("")
async def get_reply_overview(
    since_minutes: int = Window,
    organization_id: uuid.UUID | None = None,
    message_type: str | None = None,
    _admin: dict = Depends(require_platform_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Messages received in the last `since_minutes`: reply time and token
    totals (`summary`), the speed bands' upper bounds (`bands_ms`), a trend
    (`timeline`, `step_minutes` per point) and tokens by model and by step."""
    repo = PostgresReplyUsageRepository(conn)
    scope = _scope(since_minutes, organization_id, message_type)
    step = step_for(since_minutes)
    return {
        "since": scope["since"].isoformat(),
        "until": scope["until"].isoformat(),
        "step_minutes": int(step.total_seconds() // 60),
        "bands_ms": list(BANDS_MS),
        "summary": _plain(await repo.summary(**scope)),
        "timeline": [_plain(r) for r in await repo.timeline(step=step, **scope)],
        "by_model": [_plain(r) for r in await repo.by_model(**scope)],
        "by_step": [_plain(r) for r in await repo.by_step(**scope)],
    }


@router.get("/messages")
async def get_reply_messages(
    since_minutes: int = Window,
    organization_id: uuid.UUID | None = None,
    message_type: str | None = None,
    sort: Literal["newest", "slowest", "tokens", "cost"] = "newest",
    slower_than_ms: int | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: dict = Depends(require_platform_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """One page of messages with their reply time and AI usage; `total` is
    how many match before paging."""
    rows = await PostgresReplyUsageRepository(conn).messages(
        sort=sort,
        slower_than_ms=slower_than_ms,
        limit=limit,
        offset=offset,
        **_scope(since_minutes, organization_id, message_type),
    )
    total = rows[0].pop("total") if rows else 0
    for row in rows[1:]:
        row.pop("total")
    return {"total": total, "items": [_plain(r) for r in rows]}


@router.get("/messages/{correlation_id}/calls")
async def get_reply_calls(
    correlation_id: str,
    _admin: dict = Depends(require_platform_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """The AI calls one message took, in order, with tokens and cost."""
    rows = await PostgresReplyUsageRepository(conn).message_calls(correlation_id)
    return [_plain(r) for r in rows]
