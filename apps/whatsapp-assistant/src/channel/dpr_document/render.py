"""HTML -> PDF rendering for the DPR document.

Playwright is imported lazily, same convention as channel/receipt/render.py.
Unlike ReceiptRenderer, this has no pre-warmed page pool: a receipt renders
once per confirmation (a hot reply-path), a DPR renders once per site per
day (runtime/render_pending_dpr_pdfs.py's cron drain) -- the pool's
complexity buys nothing at this frequency, so a page is opened and closed
per render instead. The browser instance itself is still long-lived (lazy
launch, reused across renders in the same process).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from channel.locked_page import new_locked_page

logger = logging.getLogger(__name__)


class DprPdfRenderer:
    """Owns one long-lived headless Chromium instance for the process."""

    def __init__(self) -> None:
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._browser_lock = asyncio.Lock()

    async def _ensure_browser(self) -> Any:
        if self._browser is not None:
            return self._browser
        async with self._browser_lock:
            if self._browser is None:
                from playwright.async_api import async_playwright

                started = time.perf_counter()
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=True)
                logger.info(
                    "dpr_document.browser_launched launch_ms=%s",
                    round((time.perf_counter() - started) * 1000, 1),
                )
        return self._browser

    async def render_pdf(self, html: str) -> bytes:
        """Render the given HTML to A4 PDF bytes."""
        browser = await self._ensure_browser()
        started = time.perf_counter()
        page = await new_locked_page(browser)
        try:
            await page.set_content(html, wait_until="domcontentloaded")
            result = await page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )
            logger.info(
                "dpr_document.rendered render_ms=%s bytes=%s",
                round((time.perf_counter() - started) * 1000, 1),
                len(result),
            )
            return result
        finally:
            await page.close()

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None
