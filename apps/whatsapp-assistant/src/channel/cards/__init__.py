"""Answer cards: small images that carry a list or table on WhatsApp (WA-14).

``templates`` builds the HTML (pure); ``CardRenderer`` turns it into a PNG on
the process's shared Chromium (``snapshot.HtmlSnapshotter``, the same one
receipts use). A card is always optional: rendering failures return None and
the caller sends its text alone, which must carry the answer by itself.
"""

from __future__ import annotations

import logging
from typing import Protocol

from .templates import (
    MAX_ROWS,
    RosterCard,
    RosterGroup,
    RosterPerson,
    TableCard,
    render_roster_card_html,
    render_table_card_html,
)

logger = logging.getLogger(__name__)


class PngRenderer(Protocol):
    async def render_png(
        self, html: str, *, selector: str = ".card", log_as: str | None = None
    ) -> bytes: ...


class CardRenderer:
    """Renders answer cards to PNG bytes, or None if anything goes wrong."""

    def __init__(self, snapshotter: PngRenderer) -> None:
        self._snapshotter = snapshotter

    async def render(self, card: TableCard | RosterCard) -> bytes | None:
        try:
            if isinstance(card, TableCard):
                html = render_table_card_html(card)
            else:
                html = render_roster_card_html(card)
            return await self._snapshotter.render_png(html, log_as="card")
        except Exception:
            logger.exception("card.render_failed kind=%s", type(card).__name__)
            return None


__all__ = [
    "MAX_ROWS",
    "CardRenderer",
    "PngRenderer",
    "RosterCard",
    "RosterGroup",
    "RosterPerson",
    "TableCard",
    "render_roster_card_html",
    "render_table_card_html",
]
