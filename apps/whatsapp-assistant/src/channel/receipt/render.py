"""HTML → PNG rendering for receipt cards.

Playwright is imported lazily here only -- the core test suite (and
data.py/template.py, which are pure) run without a headless browser
installed, same convention as workflows/material/graph.py's lazy langgraph
import. One headless Chromium instance is reused across renders (started on
first use, never per-message) since launching a browser per WhatsApp message
would be far too slow for a reply path.

Page pool (Phase 4 perf):
  Creating and closing a new browser page per confirmation was measured at
  300-600 ms. A pool of _PRE_WARMED_PAGES pages is kept ready; each render
  checks one out, sets its content, screenshots it, and checks it back in.
  This drops page-acquisition cost to near zero on warm paths. If a page
  errors it is closed and replaced so the pool stays full.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from channel.locked_page import new_locked_page

logger = logging.getLogger(__name__)

_CARD_SELECTOR = ".card"
_PRE_WARMED_PAGES = 2
_PAGE_VIEWPORT = {"width": 680, "height": 800}
# 2x so the 620 px card stays sharp when WhatsApp scales it on a phone. A flat
# card is a ~100-200 KB PNG even at 2x; WhatsApp's header-image limit is 5 MB.
_PAGE_SCALE = 2
_MAX_IMAGE_BYTES = 5 * 1024 * 1024


class ReceiptRenderer:
    """Owns one long-lived headless Chromium instance and a pool of
    pre-warmed pages for the process."""

    def __init__(self) -> None:
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._browser_lock = asyncio.Lock()
        # Queue acts as the page pool. Bounded to _PRE_WARMED_PAGES.
        self._page_pool: asyncio.Queue[Any] | None = None
        self._pool_lock = asyncio.Lock()

    async def _ensure_browser(self) -> Any:
        if self._browser is not None:
            return self._browser
        async with self._browser_lock:
            if self._browser is None:
                from playwright.async_api import async_playwright

                # Logged loudly and separately from render time: this is a
                # full Chromium launch on the reply path, and because it sits
                # behind the lock above, every other reply that needs a
                # receipt while it's starting waits for it too. It's lazy by
                # design (so container construction needs no browser), which
                # means the first receipt after a deploy pays for it -- worth
                # knowing whether that is 300ms or 5s before deciding whether
                # to pre-warm it at startup instead.
                started = time.perf_counter()
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=True)
                logger.info(
                    "receipt.browser_launched launch_ms=%s",
                    round((time.perf_counter() - started) * 1000, 1),
                )
        return self._browser

    async def _ensure_pool(self) -> asyncio.Queue[Any]:
        """Lazily create and pre-warm the page pool on first use."""
        if self._page_pool is not None:
            return self._page_pool
        async with self._pool_lock:
            if self._page_pool is None:
                browser = await self._ensure_browser()
                pool: asyncio.Queue[Any] = asyncio.Queue(maxsize=_PRE_WARMED_PAGES)
                for _ in range(_PRE_WARMED_PAGES):
                    page = await new_locked_page(
                        browser, viewport=_PAGE_VIEWPORT, device_scale_factor=_PAGE_SCALE
                    )
                    await pool.put(page)
                self._page_pool = pool
        return self._page_pool

    async def _acquire_page(self) -> Any:
        pool = await self._ensure_pool()
        return await pool.get()

    async def _release_page(self, page: Any, *, healthy: bool) -> None:
        """Return a page to the pool, or replace it with a fresh one if it errored."""
        pool = await self._ensure_pool()
        if healthy:
            await pool.put(page)
        else:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                browser = await self._ensure_browser()
                fresh = await new_locked_page(
                    browser, viewport=_PAGE_VIEWPORT, device_scale_factor=_PAGE_SCALE
                )
                await pool.put(fresh)
            except Exception:  # noqa: BLE001
                pass  # pool shrinks by 1; next render will still work

    async def render_png(self, html: str) -> bytes:
        """Render the given HTML and screenshot just the `.card` element.

        Acquires a pre-warmed page from the pool, sets its content using
        ``domcontentloaded`` (safe for self-contained inline HTML with no
        external network resources -- faster than the previous ``load``),
        takes the screenshot, and returns the page to the pool.
        """
        started = time.perf_counter()
        page = await self._acquire_page()
        # Acquisition is timed apart from the render, and matters more with a
        # pool than it did with a page per render: on a warm pool this is ~0,
        # but _acquire_page() *blocks* once all _PRE_WARMED_PAGES are checked
        # out, and from the outside that queueing is indistinguishable from a
        # slow screenshot.
        acquire_ms = round((time.perf_counter() - started) * 1000, 1)
        try:
            await page.set_content(html, wait_until="domcontentloaded")
            card = page.locator(_CARD_SELECTOR)
            result = await card.screenshot(type="png")
            if len(result) > _MAX_IMAGE_BYTES:
                # Cannot happen for a card of up to 10 rows; if a future design
                # makes it happen, fail loudly (no image) rather than send an
                # image WhatsApp rejects.
                raise ValueError(f"receipt image too large: {len(result)} bytes")
            await self._release_page(page, healthy=True)
            logger.info(
                "receipt.rendered acquire_ms=%s render_ms=%s bytes=%s",
                acquire_ms,
                round((time.perf_counter() - started) * 1000, 1) - acquire_ms,
                len(result),
            )
            return result
        except Exception:
            await self._release_page(page, healthy=False)
            raise

    async def close(self) -> None:
        if self._page_pool is not None:
            while not self._page_pool.empty():
                try:
                    page = self._page_pool.get_nowait()
                    await page.close()
                except Exception:  # noqa: BLE001
                    pass
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None
        self._page_pool = None

