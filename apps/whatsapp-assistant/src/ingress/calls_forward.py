"""WA-118 step 1: copy Meta's `calls` events to the call spike.

Only while ``WHATSAPP_CALLS_FORWARD_URL`` is set. Sends the raw body and Meta's
signature, so the spike verifies them itself. Runs after the reply to Meta is
scheduled and never raises: a dead spike must not touch message handling.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_FORWARD_TIMEOUT_SECONDS = 5.0
_pending: set[asyncio.Task[None]] = set()


def has_calls_change(payload: Mapping[str, Any]) -> bool:
    return any(
        change.get("field") == "calls"
        for entry in payload.get("entry") or []
        for change in entry.get("changes") or []
    )


async def _forward(client: httpx.AsyncClient, url: str, body: bytes, signature: str) -> None:
    try:
        await client.post(
            url,
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
            timeout=_FORWARD_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        logger.warning("whatsapp.calls_forward_failed error=%s", type(exc).__name__)


def forward_calls(client: httpx.AsyncClient, url: str, body: bytes, signature: str) -> None:
    """Forward without making Meta's webhook wait on the spike."""
    task = asyncio.create_task(_forward(client, url, body, signature))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
