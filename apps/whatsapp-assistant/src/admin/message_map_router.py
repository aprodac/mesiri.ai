"""What works (SA-38): the messages people sent, by section and by how they ended, for the control panel.

Platform-admin only (``require_platform_admin``): it returns real message text, names and replies,
the same data and the same guard as the log viewer (``admin/logs_router.py``). No SQL of its own: messages
come from ``message_logger.list_for_map`` / ``list_around``, turns from ``trace_logger.get_turns``; the
grouping is ``admin/message_map.py`` and ``admin/intents*.py`` (pure).

The one write (SA-39 phase 5, decision D3): pinning the model example of a Playbook journey, through
``backend/postgres/what_works_pins.py``, recorded in ``admin_audit_log`` in the same transaction.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from admin.intents import FEEDBACK, JOURNEYS, build_intents
from admin.intents_patterns import patterns
from admin.intents_playbook import playbook
from admin.intents_summary import previous_window, summarise
from admin.message_map import CODE_TOOLS, _tools, build_map, build_thread
from mesiri.domains.audit.actions import actor_from_admin
from mesiri.domains.shared.auth import require_platform_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/message-map", tags=["admin"])

#: The page reads at most this many messages (the newest); past it the answer says it was cut.
MESSAGE_LIMIT = 5000


def _pin_store():
    """The pins store (tests replace this function)."""
    from admin.router import get_engine
    from backend.postgres.what_works_pins import PostgresWhatWorksPins

    return PostgresWhatWorksPins(get_engine())


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


#: The fields of an intent the panel needs; the rest is internal.
_INTENT_FIELDS = ("id", "started_at", "how", "company", "messages", "text", "sender_name", "sender_role",
                  "capability", "section", "tools", "ending", "reason", "journeys", "corrected_later",
                  "slowest_reply_s", "correlation_ids")


@router.get("/intents")
async def get_message_intents(
    request: Request,
    days: int = Query(default=14, ge=1, le=30),
    organization_id: uuid.UUID | None = None,
    _admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    """What works, version 2 (SA-39): the window's conversations as intents, by module and capability, with
    how each ended, the journeys, the funnel, and the totals of the window of the same length before it."""
    container = request.app.state.container
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    before, _ = previous_window(since, now)
    # One read for both windows; one row over the limit tells us it was cut.
    rows = await container.message_logger.list_for_map(
        since=before, organization_id=organization_id, limit=2 * MESSAGE_LIMIT + 1
    )
    truncated = len(rows) > 2 * MESSAGE_LIMIT
    rows = rows[: 2 * MESSAGE_LIMIT]
    turns = await container.trace_logger.get_turns([m["correlation_id"] for m in rows])
    current = [m for m in rows if m["received_at"] > since]
    previous = [m for m in rows if m["received_at"] <= since]
    built = build_intents(current, turns, now=now)
    summary = summarise(built["intents"], {str(m["id"]): m for m in current})
    earlier_intents = build_intents(previous, turns, now=now)["intents"]
    earlier = summarise(earlier_intents)
    # Pins only change which example the Playbook shows: the page still opens when they cannot be read.
    try:
        pins, pins_ok = await _pin_store().list(), True
    except Exception:
        logger.warning("what works: pins could not be read", exc_info=True)
        pins, pins_ok = {}, False
    return {
        "window": {"since": since.isoformat(), "until": now.isoformat(), "days": days},
        "truncated": truncated,
        "links": built["links"],
        **summary,
        "playbook": playbook(built["intents"], pins),
        "pins_ok": pins_ok,
        "patterns": patterns(built["intents"], earlier_intents, {str(m["id"]): m for m in current}),
        "previous": {
            "totals": earlier["totals"],
            "sections": {s["key"]: {"count": s["count"], "finished": s["finished"]} for s in earlier["sections"]},
        },
        "intents": [{k: intent[k] for k in _INTENT_FIELDS} for intent in built["intents"]],
    }


class PinBody(BaseModel):
    message_id: uuid.UUID
    note: str | None = Field(default=None, max_length=300)


def _check_pin_target(capability: str, journey: str) -> None:
    if journey not in JOURNEYS:
        raise HTTPException(status_code=404, detail=f"Unknown journey: {journey}")
    if capability == FEEDBACK or not (capability in _tools() or capability in CODE_TOOLS):
        raise HTTPException(status_code=404, detail=f"Not something people ask for: {capability}")


@router.put("/pins/{capability}/{journey}")
async def pin_example(
    request: Request,
    capability: str,
    journey: str,
    body: PinBody,
    _admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    """Pin one request (by its first message) as the model example of a Playbook journey (decision D3)."""
    _check_pin_target(capability, journey)
    if not await request.app.state.container.message_logger.list_around(body.message_id):
        raise HTTPException(status_code=404, detail="Message not found")
    note = (body.note or "").strip() or None
    await _pin_store().pin(capability=capability, journey=journey, message_id=body.message_id, note=note,
                           actor=actor_from_admin(_admin))
    return {"capability": capability, "journey": journey, "message_id": str(body.message_id), "pinned": True}


@router.delete("/pins/{capability}/{journey}")
async def unpin_example(
    capability: str,
    journey: str,
    _admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    """Remove the pin of a journey: the Playbook shows the scored pick again."""
    _check_pin_target(capability, journey)
    if not await _pin_store().unpin(capability=capability, journey=journey, actor=actor_from_admin(_admin)):
        raise HTTPException(status_code=404, detail="Nothing pinned here")
    return {"capability": capability, "journey": journey, "pinned": False}


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
