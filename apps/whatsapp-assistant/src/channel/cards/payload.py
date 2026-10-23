"""A card that rides in a notification payload and is drawn when the row is
sent: ``{"kind": "today", "data": {...}}``. Anything unreadable gives None, so
the row goes out as its text."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .base import render_png
from .today import TodayCard, today_html

if TYPE_CHECKING:
    from channel.receipt import ReceiptRenderer

logger = logging.getLogger(__name__)


def today_payload(card: TodayCard) -> dict[str, Any]:
    return {"kind": "today", "data": card.to_dict()}


async def render_payload_card(card: Any, renderer: ReceiptRenderer | None) -> bytes | None:
    if renderer is None or not isinstance(card, dict) or card.get("kind") != "today":
        return None
    try:
        html = today_html(TodayCard.from_dict(card["data"]))
    except Exception:  # noqa: BLE001 -- a bad payload is the text's problem, not the send's
        logger.exception("card.payload_unreadable")
        return None
    return await render_png(renderer, html, card="today")
