"""HTML -> PNG rendering for receipt cards.

The browser and page pool live in channel/cards/snapshot.py (moved there in
WA-14 so answer cards share the same Chromium). This subclass only pins the
log prefix, so ``receipt.browser_launched`` / ``receipt.rendered`` log lines
read exactly as they did before the move.
"""

from __future__ import annotations

from channel.cards.snapshot import HtmlSnapshotter


class ReceiptRenderer(HtmlSnapshotter):
    """Owns one long-lived headless Chromium instance and a pool of
    pre-warmed pages for the process. Also renders answer cards: the
    process keeps one instance (runtime/dependencies.py) and every card
    path reuses it rather than starting a second browser."""

    def __init__(self) -> None:
        super().__init__(log_prefix="receipt")
