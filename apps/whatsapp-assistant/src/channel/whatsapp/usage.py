"""Reporting what each WhatsApp message costs (BE-25).

The sender reports every message it sends (`report_sent`) and the webhook
passes on Meta's own pricing for it (`report_pricing`). Where the reports go
is set once at startup (`set_sink`, runtime/dependencies.py) -- the backend's
UsageRecorder, which prices and stores them. No sink: reports are dropped.

Fire-and-forget: a report never raises and never delays the send or the
webhook it came from.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any, Protocol

from channel.whatsapp.templates import TEMPLATES

logger = logging.getLogger(__name__)

#: Meta's category for a free-form reply inside the 24 h window.
SERVICE = "service"


class MessageCostSink(Protocol):
    async def record_whatsapp_sent(
        self, *, wamid: str, recipient: str, category: str, operation: str = "send"
    ) -> None: ...

    async def record_whatsapp_pricing(
        self, *, wamid: str, recipient: str | None, category: str | None, billable: bool | None
    ) -> None: ...


_sink: MessageCostSink | None = None
_pending: set[asyncio.Task[None]] = set()


def set_sink(sink: MessageCostSink | None) -> None:
    global _sink
    _sink = sink


def category_for(message_fields: Mapping[str, Any]) -> str:
    """Our estimate of Meta's pricing category for an outgoing message: a
    template's declared category, anything else a service reply."""
    if message_fields.get("type") != "template":
        return SERVICE
    name = str((message_fields.get("template") or {}).get("name") or "")
    spec = TEMPLATES.get(name)
    # An undeclared template can't be sent (templates.py), but don't guess
    # high: utility is the common case.
    return spec.category.lower() if spec is not None else "utility"


def report_sent(*, wamid: str, recipient: str, message_fields: Mapping[str, Any]) -> None:
    sink = _sink
    if sink is None:
        return
    _spawn(
        sink.record_whatsapp_sent(
            wamid=wamid,
            recipient=recipient,
            category=category_for(message_fields),
            operation=f"send_{message_fields.get('type') or 'message'}",
        )
    )


def report_pricing(payload: Mapping[str, Any]) -> None:
    """Pass on the `pricing` Meta attaches to sent/delivered statuses on the
    webhook: whether the message was billable and in which category."""
    sink = _sink
    if sink is None:
        return
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "messages":
                continue
            for status in (change.get("value") or {}).get("statuses") or []:
                pricing = status.get("pricing")
                wamid = status.get("id")
                if not pricing or not wamid:
                    continue
                billable = pricing.get("billable")
                _spawn(
                    sink.record_whatsapp_pricing(
                        wamid=str(wamid),
                        recipient=status.get("recipient_id"),
                        category=pricing.get("category"),
                        billable=billable if isinstance(billable, bool) else None,
                    )
                )


def _spawn(coro: Any) -> None:
    try:
        task = asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        coro.close()
        return
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def drain() -> None:
    """Wait for reports still being written (tests, shutdown)."""
    while _pending:
        await asyncio.gather(*list(_pending), return_exceptions=True)
