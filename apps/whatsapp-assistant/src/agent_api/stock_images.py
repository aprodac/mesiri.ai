"""[304]: "how much stock is left, everything" -- the list as pictures, as many as it takes.

15 Nov (Aprodac, a voice note "ethra stock baaki undu, full ellathilum"): the answer was a long text list over two
projects and four sites, hard to read on a phone and folded away by WhatsApp. Stock of more than one material is now
drawn by the code, in the receipt card's look, from the same route the dashboard reads (``GET /materials/inventory``,
as the person: only their projects and sites). One picture holds about ``PAGE_UNITS`` lines; a longer list goes on in
the next picture ("1/3", "2/3"), and a site is never cut in two when it fits whole on the next one.

A material with minus stock is never shown as stock left: it is marked "Check" (more was used than received, so a
delivery is probably missing) ([302]). Nothing is computed here that the API did not give.
"""

from __future__ import annotations

import datetime as dt
import html
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from mesiri_ai.models import ToolSpec

from .client import ApiClient

_log = logging.getLogger(__name__)

SEND_STOCK_LIST = "send_stock_list"
TOOL = ToolSpec(name=SEND_STOCK_LIST, description=(
    "Send the stock left of MORE than one material as pictures in this chat (the code draws them from the stock "
    "records, as many pictures as the list needs). For overall stock ('ethra stock baaki undu', 'full stock', "
    "'stock of all sites'), one project's or one site's stock, or one category's: project_id / site_id / category_id "
    "to narrow it, none for everything they can see. Stock of ONE material stays a text answer from stock_levels."),
    parameters={"type": "object", "properties": {
        "project_id": {"type": "string"}, "site_id": {"type": "string"}, "category_id": {"type": "string"}}})

#: How many lines one picture holds (a material is 1, a site's heading 1.5, a project's heading 2).
PAGE_UNITS = 24.0
_ROW, _SITE, _PROJECT = 1.0, 1.5, 2.0
#: At most this many pictures; a company with more is told to narrow it (a project or a site).
MAX_PAGES = 6


@dataclass
class Line:
    name: str
    left: str
    unit: str
    state: str  # "ok", "low", "out", "check"
    note: str = ""


@dataclass
class Site:
    project: str
    name: str
    lines: list[Line] = field(default_factory=list)
    continued: bool = False


def _number(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def quantity(value: Decimal) -> str:
    """2560 -> "2,560"; 2.20 -> "2.2"; -30 -> "-30"."""
    q = value.quantize(Decimal("0.01")).normalize()
    if q == q.to_integral():
        return f"{int(q):,}"
    return f"{q:,f}".rstrip("0").rstrip(".")


def line_of(row: dict[str, Any]) -> Line:
    left = _number(row.get("current_stock"))
    coming = _number(row.get("on_order"))
    unit = str(row.get("unit") or "")
    if left < 0:
        state, note = "check", f"{quantity(-left)} {unit} more used than received"
    elif left == 0:
        state, note = "out", "None left"
    elif row.get("below_min"):
        state, note = "low", "Below the minimum"
    else:
        state, note = "ok", ""
    if coming > 0:
        note = (note + " · " if note else "") + f"{quantity(coming)} {unit} on order"
    return Line(str(row.get("material_name") or "Material"), quantity(left), unit, state, note)


def sites_of(rows: list[dict[str, Any]], project_names: dict[str, str], site_names: dict[str, str]) -> list[Site]:
    """The rows grouped by project, then site, each list by material name. A row of a project the names do not know
    keeps its place under "Other"."""
    grouped: dict[tuple[str, str], Site] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        project = project_names.get(str(row.get("project_id")), "Other")
        site = site_names.get(str(row.get("site_id")), "No site") if row.get("site_id") else "No site"
        grouped.setdefault((project, site), Site(project, site)).lines.append(line_of(row))
    for site in grouped.values():
        site.lines.sort(key=lambda line: line.name.casefold())
    return [grouped[k] for k in sorted(grouped, key=lambda k: (k[0].casefold(), k[1].casefold()))]


def paginate(sites: list[Site], units: float = PAGE_UNITS) -> list[list[Site]]:
    """Pictures of at most ``units`` lines. A site goes whole to the next picture when it does not fit on this one
    but fits on an empty one; a site longer than a whole picture is split, its next part marked as continued."""
    pages: list[list[Site]] = []
    page: list[Site] = []
    used = 0.0

    def cost(site: Site, first_of_project: bool) -> float:
        return (_PROJECT if first_of_project else 0) + _SITE + _ROW * len(site.lines)

    def close() -> None:
        nonlocal page, used
        if page:
            pages.append(page)
        page, used = [], 0.0

    for site in sites:
        rest = Site(site.project, site.name, list(site.lines))
        while rest.lines:
            first = not page or page[-1].project != rest.project
            need = cost(rest, first)
            if used + need <= units:
                page.append(rest)
                used += need
                break
            if page and cost(rest, True) <= units:  # fits whole on a fresh picture: never cut it
                close()
                continue
            room = int((units - used - (_PROJECT if first else 0) - _SITE) // _ROW)
            if room < 1:
                close()
                continue
            page.append(Site(rest.project, rest.name, rest.lines[:room], rest.continued))
            rest = Site(rest.project, rest.name, rest.lines[room:], True)
            close()
    close()
    return pages


_COLOUR = {"ok": "#111111", "low": "#B45309", "out": "#6B7280", "check": "#B42318"}
_TAG = {"low": "LOW", "out": "OUT", "check": "CHECK"}


def page_html(page: list[Site], *, number: int, total: int, day: dt.date, where: str) -> str:
    from channel.receipt.template import _font_css

    e = html.escape
    parts: list[str] = []
    project = None
    for site in page:
        if site.project != project:
            project = site.project
            parts.append(f'<div class="project">{e(project)}</div>')
        parts.append(f'<div class="site">{e(site.name)}{" (continued)" if site.continued else ""}</div>')
        for line in site.lines:
            tag = (f'<span class="tag" style="background:{_COLOUR[line.state]}">{_TAG[line.state]}</span>'
                   if line.state in _TAG else "")
            note = f'<div class="note" style="color:{_COLOUR[line.state]}">{e(line.note)}</div>' if line.note else ""
            parts.append(
                f'<div class="row"><div class="name">{e(line.name)}{note}</div>'
                f'<div class="qty" style="color:{_COLOUR[line.state]}">{e(line.left)} '
                f'<span class="unit">{e(line.unit)}</span>{tag}</div></div>')
    pager = f"{number}/{total}" if total > 1 else ""
    check = (" CHECK: more was used than received, so a delivery may not be recorded."
             if any(line.state == "check" for site in page for line in site.lines) else "")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
{_font_css()}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ width: 620px; font-family: "Inter", "Noto Sans Malayalam", "Noto Sans", sans-serif; color: #111111;
  font-variant-numeric: tabular-nums; -webkit-font-smoothing: antialiased; }}
.card {{ width: 620px; background: #FFFFFF; padding: 22px 32px 20px; border-top: 6px solid #111111; }}
.top {{ display: flex; justify-content: space-between; align-items: baseline; }}
.brand {{ font-size: 13px; font-weight: 800; letter-spacing: 0.2em; }}
.pager {{ font-size: 13px; font-weight: 700; color: #6B7280; }}
h1 {{ font-size: 24px; font-weight: 800; margin-top: 10px; }}
.sub {{ font-size: 13px; color: #6B7280; margin-top: 2px; }}
.project {{ font-size: 15px; font-weight: 800; margin-top: 18px; padding-bottom: 4px;
  border-bottom: 2px solid #111111; text-transform: uppercase; letter-spacing: 0.04em; }}
.site {{ font-size: 13px; font-weight: 700; color: #374151; margin-top: 10px; padding: 3px 8px;
  background: #F3F4F6; }}
.row {{ display: flex; justify-content: space-between; align-items: center; padding: 7px 8px;
  border-bottom: 1px solid #E5E7EB; }}
.name {{ font-size: 15px; font-weight: 500; }}
.note {{ font-size: 11.5px; margin-top: 1px; }}
.qty {{ font-size: 16px; font-weight: 700; white-space: nowrap; text-align: right; }}
.unit {{ font-size: 12px; font-weight: 500; color: #6B7280; }}
.tag {{ display: inline-block; color: #FFFFFF; font-size: 10px; font-weight: 800; letter-spacing: 0.06em;
  padding: 2px 6px; margin-left: 8px; vertical-align: 2px; }}
.foot {{ font-size: 11px; color: #6B7280; margin-top: 14px; }}
</style></head><body><div class="card">
<div class="top"><div class="brand">MESIRI</div><div class="pager">{pager}</div></div>
<h1>Stock left</h1><div class="sub">{e(where)} · {day.day} {day:%b %Y}</div>
{''.join(parts)}
<div class="foot">As recorded in Mesiri.{check}</div>
</div></body></html>"""


def _names(ctx: Any) -> tuple[dict[str, str], dict[str, str]]:
    """The person's project and site names (the facts the model reads come from the same place)."""
    projects = {str(p.id): str(p.name) for p in getattr(ctx, "projects", None) or []}
    sites = {str(s.id): str(s.name) for s in getattr(ctx, "sites", None) or []}
    return projects, sites


async def send(client: ApiClient, render_png: Callable[[str], Awaitable[bytes]],
               send_image: Callable[..., Awaitable[Any]], wa_id: str, ctx: Any, today: dt.date,
               arguments: dict[str, Any]) -> dict[str, Any]:
    """Fetch the stock as the person, draw it, send the pictures in order. What went is said back to the model."""
    params = {k: str(arguments[k]) for k in ("project_id", "site_id", "category_id") if arguments.get(k)}
    response = await client.call("GET", "/materials/inventory", params=params)
    if not response.ok or not isinstance(response.body, list):
        return {"status": "not sent; answer from stock_levels in words instead"}
    rows = [r for r in response.body if isinstance(r, dict)]
    if not rows:
        return {"status": "nothing sent: no stock is recorded there. Say so plainly, with an example to send "
                          "(\"50 bags cement vannu\")."}
    projects, sites = _names(ctx)
    grouped = sites_of(rows, projects, sites)
    pages = paginate(grouped)
    if len(pages) > MAX_PAGES:
        return {"status": f"not sent: {len(rows)} lines would need {len(pages)} pictures. Ask which project or site "
                          "they want, then call this again with it."}
    where = (sites.get(params.get("site_id", ""), "") or projects.get(params.get("project_id", ""), "")
             or "All your sites")
    sent = 0
    for number, page in enumerate(pages, 1):
        try:
            image = await render_png(page_html(page, number=number, total=len(pages), day=today, where=where))
            ok = await send_image(wa_id, image, filename=f"stock-{number}.png",
                                  shows=f"Stock list picture {number}/{len(pages)}")
        except Exception:  # noqa: BLE001 -- said back to the model; it answers in words
            _log.exception("agent_api.stock_images_failed page=%s", number)
            ok = False
        if not ok:
            break
        sent += 1
    checks = sorted({line.name for s in grouped for line in s.lines if line.state == "check"})
    if sent == 0:
        return {"status": "not sent; answer from stock_levels in words instead"}
    out: dict[str, Any] = {
        "status": f"sent {sent} picture{'s' if sent > 1 else ''} of {len(pages)} to their WhatsApp",
        "note": ("The pictures show every line. Your reply is ONE short line in their language: that the stock list "
                 "is above. Never repeat the list in words."),
    }
    if sent < len(pages):
        out["note"] += f" Only {sent} of {len(pages)} went: say so and that they can ask again."
    if checks:
        out["check"] = (f"Minus stock (more used than received; a delivery may be missing): {', '.join(checks)}. "
                        "Add one short line naming them.")
    return out
