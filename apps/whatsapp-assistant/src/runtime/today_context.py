"""A one-line, read-only "today so far" for the reply writer (request [68]).

Built from the existing ActivitySearchService (the one behind "what did I log
today?") and only ever put into the model's prompt, so a small-talk reply can
sound like it knows the day ("Anil, Site A1: plastering logged today"). It never
writes anything. If the lookup is slow (over 300 ms), fails, or the sender has no
single site, the line is left out and the reply is written without it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from canonicalization.occurred_date import today_for

logger = logging.getLogger(__name__)

#: A reply never waits longer than this for context.
TIMEOUT_SECONDS = 0.3
_MAX_ITEMS = 3


def first_name(full_name: str | None) -> str:
    parts = (full_name or "").split()
    return parts[0] if parts else ""


def render_line(name: str, site: str | None, results: dict[str, Any] | None) -> str | None:
    """The line from search results, or None when there is nothing worth saying."""
    who = ", ".join(p for p in (name, site) if p)
    if not who:
        return None
    activities = (results or {}).get("activities") or []
    work: list[str] = []
    for row in activities:
        label = str(row.get("work_type") or "").strip()
        if label and label.lower() not in (w.lower() for w in work):
            work.append(label)
        if len(work) == _MAX_ITEMS:
            break
    if not work:
        return f"Today so far: {who}. Nothing saved yet today."
    return f"Today so far: {who}. Saved today: {', '.join(work)}."


async def build_today_line(
    activity_search_service: Any | None,
    actor: Any,
    *,
    timezone_name: str | None = None,
    timeout: float = TIMEOUT_SECONDS,
) -> str | None:
    """Never raises; None when the service is missing, slow or fails."""
    if activity_search_service is None or actor is None or not getattr(actor, "organization_id", None):
        return None
    sites = list(getattr(actor, "sites", None) or [])
    site = sites[0] if len(sites) == 1 else None
    try:
        today = today_for(timezone_name)
        results = await asyncio.wait_for(
            activity_search_service.search(
                organization_id=actor.organization_id,
                project_id=getattr(site, "project_id", None),
                site_id=getattr(site, "id", None),
                start_date=today,
                end_date=today,
            ),
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001 -- context is a nicety, never load-bearing
        logger.debug("today_context.skipped", exc_info=True)
        return None
    return render_line(first_name(getattr(actor, "full_name", None)), getattr(site, "name", None), results)


#: At most this many materials in the stock line, largest stock first.
_MAX_STOCK = 6


def _amount(value: float) -> str:
    return f"{value:g}"


def render_stock_line(site: str | None, levels: list[dict[str, Any]] | None) -> str | None:
    """WA-36: "Stock now at Site A1 (from the records): cement 140 bags, ..."
    from the inventory rows, or None when there is nothing to say."""
    rows = [r for r in (levels or []) if str(r.get("material_name") or "").strip()]
    if not rows:
        return None
    rows.sort(key=lambda r: float(r.get("current_stock") or 0), reverse=True)
    items = [
        f"{str(r['material_name']).strip()} {_amount(float(r.get('current_stock') or 0))} {r.get('unit') or ''}".strip()
        for r in rows[:_MAX_STOCK]
    ]
    more = f" (+{len(rows) - _MAX_STOCK} more)" if len(rows) > _MAX_STOCK else ""
    where = f" at {site}" if site else ""
    return f"Stock now{where} (from the records): {', '.join(items)}{more}."


async def build_stock_line(
    inventory_query: Any | None,
    actor: Any,
    *,
    timeout: float = TIMEOUT_SECONDS,
) -> str | None:
    """WA-36: the sender's site stock for the agent's prompt, so a material
    message or question is read against what is actually there. Read-only;
    only for a sender with one site; never raises, None when missing, slow
    or failing."""
    if inventory_query is None or actor is None or not getattr(actor, "organization_id", None):
        return None
    sites = list(getattr(actor, "sites", None) or [])
    if len(sites) != 1:
        return None
    site = sites[0]
    try:
        levels = await asyncio.wait_for(
            inventory_query.query(
                organization_id=str(actor.organization_id),
                project_id=str(site.project_id) if getattr(site, "project_id", None) else None,
                site_id=str(site.id),
                material_name=None,
            ),
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001 -- context is a nicety, never load-bearing
        logger.debug("stock_context.skipped", exc_info=True)
        return None
    return render_stock_line(getattr(site, "name", None), levels)
