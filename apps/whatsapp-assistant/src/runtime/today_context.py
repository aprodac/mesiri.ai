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


def render_line(
    name: str, site: str | None, results: dict[str, Any] | None, labour: dict[str, Any] | None = None
) -> str | None:
    """The line from search results (and the day's labour count, request 127),
    or None when there is nothing worth saying."""
    who = ", ".join(p for p in (name, site) if p)
    if not who:
        return None
    activities = (results or {}).get("activities") or []
    # Request 137 (D): saved and still waiting for Save are told apart; the work
    # says where it is now ("tiling 80%", its latest update).
    saved: list[str] = []
    pending: list[str] = []
    for row in activities:
        label = _work_label(row)
        into = saved if row.get("saved", True) else pending
        if label and label.lower() not in (w.lower() for w in into) and len(into) < _MAX_ITEMS:
            into.append(label)
    headcount = int((labour or {}).get("headcount") or 0)
    if headcount:
        saved.append(f"{headcount} {'worker' if headcount == 1 else 'workers'}")
    waiting = f" Waiting for Save: {', '.join(pending)}." if pending else ""
    if not saved:
        return f"Today so far: {who}. Nothing saved yet today.{waiting}"
    return f"Today so far: {who}. Saved today: {', '.join(saved)}.{waiting}"


def _work_label(row: dict[str, Any]) -> str:
    from canonicalization.progress import find_percent, percent_text

    label = str(row.get("work_type") or "").strip()
    percent = find_percent(str(row.get("narrative") or ""))
    return f"{label} {percent_text(percent)}" if label and percent is not None else label


def _chosen(sites: list[Any], site_id: str | None) -> Any | None:
    """The one of several sites the sender is working at today, if any."""
    return next((s for s in sites if site_id and str(s.id) == str(site_id)), None)


async def build_today_line(
    activity_search_service: Any | None,
    actor: Any,
    *,
    timezone_name: str | None = None,
    timeout: float = TIMEOUT_SECONDS,
    site_id: str | None = None,
    labour_query_service: Any | None = None,
) -> str | None:
    """Never raises; None when the service is missing, slow or fails.
    ``site_id``: the site a sender with several chose for today (SIT-10).
    ``labour_query_service``: adds the day's saved headcount (request 127: the
    line said "nothing saved" for a day with 8 workers counted)."""
    if activity_search_service is None or actor is None or not getattr(actor, "organization_id", None):
        return None
    sites = list(getattr(actor, "sites", None) or [])
    site = sites[0] if len(sites) == 1 else _chosen(sites, site_id)
    try:
        from runtime.agent.project_day import period_for, read_period

        # The one read helper: the project's today, the same scope and rules as
        # "what was done today?" and "how many workers today?".
        read = await asyncio.wait_for(
            read_period(
                organization_id=actor.organization_id,
                project_id=getattr(site, "project_id", None),
                site_id=getattr(site, "id", None),
                period=period_for("today", today_for(timezone_name)),  # type: ignore[arg-type]
                activity_search=activity_search_service,
                labour_query=labour_query_service,
                # WA-77: the agent sees what was sent, saved or not.
                include_unsaved=True,
            ),
            timeout=timeout,
        )
    except Exception:  # noqa: BLE001 -- context is a nicety, never load-bearing
        logger.debug("today_context.skipped", exc_info=True)
        return None
    return render_line(
        first_name(getattr(actor, "full_name", None)), getattr(site, "name", None), read["work"], read["labour"]
    )


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
    site_id: str | None = None,
) -> str | None:
    """WA-36: the sender's site stock for the agent's prompt, so a material
    message or question is read against what is actually there. Read-only;
    for a sender with one site, or the site a sender with several chose for
    today (SIT-10); never raises, None when missing, slow or failing."""
    if inventory_query is None or actor is None or not getattr(actor, "organization_id", None):
        return None
    sites = list(getattr(actor, "sites", None) or [])
    site = sites[0] if len(sites) == 1 else _chosen(sites, site_id)
    if site is None:
        return None
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


#: At most this many open activities in the open-work line.
_MAX_OPEN = 6


def open_work_label(row: dict[str, Any]) -> str:
    """How an open activity is named to the model, and matched back from its
    save_work_done ``continues``: "Plastering (2nd floor plastering)"."""
    work = str(row.get("work_type") or "").replace("_", " ").strip().capitalize()
    narrative = " ".join(str(row.get("narrative") or "").split())[:60]
    if work and narrative and narrative.casefold() != work.casefold():
        return f"{work} ({narrative})"
    return work or narrative or "Work"


def render_open_work_line(
    site: str | None, rows: list[dict[str, Any]] | None, *, site_names: dict[str, str] | None = None
) -> str | None:
    """The sender's open activities, so a "finished" or a new quantity can
    name the one it continues (save_work_done's ``continues``).

    WRK-04: the first ``_MAX_OPEN`` are named and the rest counted; the code
    still matches any open job by its work type, so a 7th job named in a
    message is continued, not started again. WRK-05: with no site chosen the
    rows come from all the sender's sites (``site_names`` maps site id to
    name) and each is shown under its site."""
    rows = rows or []
    if not rows:
        return None
    shown, more = rows[:_MAX_OPEN], max(len(rows) - _MAX_OPEN, 0)
    if site_names:
        by_site: dict[str, list[str]] = {}
        for row in shown:
            by_site.setdefault(site_names.get(str(row.get("site_id")), "another site"), []).append(open_work_label(row))
        listed = "; ".join(f"{name}: " + ", ".join(labels) for name, labels in by_site.items())
        where = ""
    else:
        listed = "; ".join(open_work_label(r) for r in shown)
        where = f" at {site}" if site else ""
    tail = f"; and {more} more open (name the work as the message does)" if more else ""
    return (
        f"Open work{where} (started, not finished): {listed}{tail}. When a message "
        "continues or finishes one of these, call save_work_done with continues set to its name "
        "exactly as written here; leave continues out for new work."
    )
