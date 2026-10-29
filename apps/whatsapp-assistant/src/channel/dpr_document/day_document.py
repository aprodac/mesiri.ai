"""A site's day as the DPR document (request 143): one way to print a day that is
not a stored, confirmed report -- the draft "send me today's report" sends on
WhatsApp and the dashboard's live preview.

The day comes from Day Facts (``runtime.day_facts.SiteDay``); the template,
letterhead and photos are this package's. Nothing is stored here.
"""

from __future__ import annotations

from typing import Any

#: The document's code line until the day is confirmed.
DRAFT_CODE = "Draft · not confirmed yet"

_renderer: Any = None


def shared_renderer() -> Any:
    """One DPR PDF renderer (a headless Chromium, started on first use) for the
    process, as the cron drains keep one for theirs."""
    global _renderer
    if _renderer is None:
        from channel.dpr_document.render import DprPdfRenderer

        _renderer = DprPdfRenderer()
    return _renderer


async def day_html(
    site_day: Any,
    *,
    object_storage: Any,
    code: str = DRAFT_CODE,
    letterhead: Any = None,
    summary: str | None = None,
) -> str:
    """The day as the document's HTML, its photos embedded."""
    from channel.dpr_document.data import build_document_data
    from channel.dpr_document.photos import embed_photos
    from channel.dpr_document.template import render_html

    document = await embed_photos(object_storage, site_day.document())
    return render_html(build_document_data(code=code, payload=document, summary=summary), letterhead)


async def day_pdf(
    site_day: Any,
    *,
    object_storage: Any,
    letterhead: Any = None,
    code: str = DRAFT_CODE,
    renderer: Any = None,
) -> bytes:
    """The day as a PDF. Raises when it cannot be printed; the caller says so."""
    html = await day_html(site_day, object_storage=object_storage, code=code, letterhead=letterhead)
    return await (renderer or shared_renderer()).render_pdf(html)
