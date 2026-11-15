"""What works (SA-38): the messages people sent, by section and by how they ended, for the control panel.

Platform-admin only (``require_platform_admin``): it returns real message text, names and replies,
the same data and the same guard as the log viewer (``admin/logs_router.py``). Read-only. No SQL of
its own: messages come from ``message_logger.list_for_map`` / ``list_around``, turns from
``trace_logger.get_turns``; the grouping is ``admin/message_map.py`` (pure).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from admin.message_map import build_map, build_thread
from mesiri.domains.shared.auth import require_platform_admin

router = APIRouter(prefix="/admin/message-map", tags=["admin"])

#: The page reads at most this many messages (the newest); past it the answer says it was cut.
MESSAGE_LIMIT = 5000


@router.get("")
async def get_message_map(
    request: Request,
    days: int = Query(default=14, ge=1, le=30),
    organization_id: uuid.UUID | None = None,
    _admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    container = request.app.state.container
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    # One row over the limit tells us the window was cut, without a COUNT.
    messages = await container.message_logger.list_for_map(
        since=since, organization_id=organization_id, limit=MESSAGE_LIMIT + 1
    )
    truncated = len(messages) > MESSAGE_LIMIT
    messages = messages[:MESSAGE_LIMIT]
    turns = await container.trace_logger.get_turns([m["correlation_id"] for m in messages])
    return {
        "window": {"since": since.isoformat(), "until": now.isoformat(), "days": days},
        "truncated": truncated,
        **build_map(messages, turns, now=now),
    }


@router.get("/thread/{message_id}")
async def get_message_thread(
    request: Request,
    message_id: uuid.UUID,
    _admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    """The WhatsApp conversation one message was part of: what the person sent before and after it,
    each reply, and what the assistant did in each turn."""
    container = request.app.state.container
    messages = await container.message_logger.list_around(message_id)
    if not messages:
        raise HTTPException(status_code=404, detail="Message not found")
    turns = await container.trace_logger.get_turns([m["correlation_id"] for m in messages])
    thread = build_thread(messages, turns, message_id=str(message_id), now=datetime.now(UTC))
    first = messages[0]
    return {
        "sender": first.get("sender_name"),
        "role": first.get("sender_role"),
        "company": first.get("organization_name"),
        "messages": thread,
    }
