"""Headless-browser pages for rendering our own HTML, locked down (BE-36).

The DPR PDF and the receipt images are HTML built from what people typed on
WhatsApp, rendered in a Chromium running on our server. The templates escape
every value; this is the second layer, in case anything ever slips through:
no JavaScript, and no network at all (the templates load nothing external;
logos are embedded data URIs, which are never fetched).
"""

from __future__ import annotations

from typing import Any


async def _refuse(route: Any) -> None:
    await route.abort()


async def new_locked_page(browser: Any, **options: Any) -> Any:
    """`browser.new_page(**options)` with JavaScript off and every request blocked."""
    page = await browser.new_page(java_script_enabled=False, **options)
    await page.route("**/*", _refuse)
    return page
