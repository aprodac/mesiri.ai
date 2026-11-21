"""Labour put on BOQ lines (CC-05). Pure, no I/O.

Attendance gives, per site, day and trade, the man-days worked and what they cost (the Labour module's own
rule). A person puts that day's trade on one or more BOQ lines, by man-days ("4 masons: 3 on plastering, 1 on
brickwork"). A line's labour cost is its share of the group's cost, by man-days; what nobody put on a line
stays "not on a BOQ line": shown, never guessed (decision D-CC2).

A group's cost is shared out exactly: the shares are rounded to the paisa and the part not on a line takes the
rounding, so lines + not on a line always equals what attendance cost. Man-days with no wage give no cost
(the Labour rule), so a share of a group with no wage is man-days with no cost, never zero rupees of work.

When attendance is corrected after a split (12 masons re-sent as 10), the man-days put on lines can be more
than were worked. Then the lines share the cost in proportion and the group says ``over_allocated``: the money
never passes what attendance cost.

Worked example (the GM meeting): 4 masons at ₹1,100 and 2 helpers at ₹1,000 one day = ₹6,400. Masons put
3 man-days on plastering and 1 on brickwork: plastering ₹3,300, brickwork ₹1,100, helpers ₹2,000 not on a line.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

_CENT = Decimal("0.01")
_ZERO = Decimal(0)


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def group_key(site_id: Any, work_date: Any, trade_key: str | None) -> tuple:
    """The one key a site's day of one trade is known by (attendance and allocations both use it)."""
    return (str(site_id) if site_id else None, str(work_date), (trade_key or "").strip().lower())


def share_group(group: Mapping[str, Any], allocations: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """One group's man-days and cost, shared over the lines it was put on.

    ``group``: man_days, priced_man_days, cost (from attendance). ``allocations``: line_id, man_days.
    Returns per line {line_id, man_days, cost} (cost None when the group has no wage at all), the part not on
    a line, and ``over_allocated`` when more man-days were put on lines than attendance now counts.
    """
    man_days = Decimal(group["man_days"])
    cost = Decimal(group["cost"])
    priced = Decimal(group.get("priced_man_days") or 0)
    allocs = [(a["line_id"], Decimal(a["man_days"])) for a in allocations if Decimal(a["man_days"]) > 0]
    put = sum((md for _, md in allocs), _ZERO)
    over = put > man_days
    # Shares are taken of the larger of the two, so a corrected-down day never costs more than it did.
    base = max(put, man_days)
    lines = []
    shared = _ZERO
    for line_id, md in allocs:
        line_md = md * man_days / base if over else md
        line_cost = _money(cost * md / base) if base and priced else None
        shared += line_cost or _ZERO
        lines.append({"line_id": line_id, "man_days": line_md, "cost": line_cost})
    left_md = max(man_days - put, _ZERO)
    return {
        "man_days": man_days,
        "cost": _money(cost) if priced else None,
        "on_lines": lines,
        "not_on_a_line": {"man_days": left_md, "cost": _money(cost - shared) if priced else None},
        "over_allocated": over,
    }


def labour_by_line(
    groups: Iterable[Mapping[str, Any]],
    allocations: Iterable[Mapping[str, Any]],
    current_of: Mapping[Any, Any] | None = None,
) -> dict[str, Any]:
    """A project's labour, per BOQ line and not on a line, over the groups given.

    ``groups``: attendance per site, day and trade (site_id, work_date, trade_key, man_days, priced_man_days,
    cost). ``allocations``: site_id, work_date, trade_key, planned_item_id, man_days. ``current_of`` maps an
    earlier revision of a line to the current one, so a line revised after the split keeps its labour.
    An allocation whose group has no attendance any more (the report was withdrawn) counts nothing.
    """
    current_of = current_of or {}
    by_group: dict[tuple, list[dict]] = {}
    for a in allocations:
        key = group_key(a["site_id"], a["work_date"], a["trade_key"])
        line_id = current_of.get(a["planned_item_id"], a["planned_item_id"])
        by_group.setdefault(key, []).append({"line_id": line_id, "man_days": a["man_days"]})
    lines: dict[Any, dict[str, Any]] = {}
    left = {"man_days": _ZERO, "cost": _ZERO, "unpriced_man_days": _ZERO}
    total = {"man_days": _ZERO, "cost": _ZERO}
    for g in groups:
        shared = share_group(g, by_group.get(group_key(g["site_id"], g["work_date"], g["trade_key"]), []))
        total["man_days"] += shared["man_days"]
        total["cost"] += shared["cost"] or _ZERO
        for part in shared["on_lines"]:
            row = lines.setdefault(part["line_id"], {"man_days": _ZERO, "cost": _ZERO, "unpriced_man_days": _ZERO})
            row["man_days"] += part["man_days"]
            if part["cost"] is None:
                row["unpriced_man_days"] += part["man_days"]
            else:
                row["cost"] += part["cost"]
        rest = shared["not_on_a_line"]
        left["man_days"] += rest["man_days"]
        if rest["cost"] is None:
            left["unpriced_man_days"] += rest["man_days"]
        else:
            left["cost"] += rest["cost"]
    return {"lines": lines, "not_on_a_line": left, "total": total}


# -- BOQ-02: a day's labour put on the lines its site's work went to, when nobody split it -------------------------

#: The work each trade does, as BOQ lines name it: a mason's day goes to the brickwork and plastering lines, not the
#: steel. A trade not here (helpers, unskilled) is shared over every line the site worked on that day.
TRADE_WORK: dict[str, tuple[str, ...]] = {
    "mason": ("brick", "brickwork", "block", "blockwork", "masonry", "plaster", "plastering", "stone", "rubble",
              "laterite", "concrete", "pcc", "rcc", "screed", "flooring", "tile", "tiling"),
    "carpenter": ("shuttering", "formwork", "centering", "centring", "door", "doors", "window", "windows", "wood",
                  "woodwork", "joinery", "frame", "frames"),
    "bender": ("steel", "reinforcement", "rebar", "bar", "bars", "bending", "tmt"),
    "steel": ("steel", "reinforcement", "rebar", "bar", "bars", "bending", "tmt"),
    "fitter": ("steel", "reinforcement", "rebar", "bar", "bars", "fabrication"),
    "electrician": ("electrical", "wiring", "conduit", "conduits", "earthing", "light", "lighting", "switch"),
    "plumber": ("plumbing", "pipe", "pipes", "piping", "sanitary", "drainage", "water", "tank"),
    "painter": ("painting", "paint", "putty", "primer", "emulsion", "texture", "polish"),
    "tiler": ("tile", "tiles", "tiling", "flooring", "granite", "marble", "cladding"),
    "welder": ("welding", "fabrication", "grill", "grills", "railing", "truss", "steel"),
}


def _words(value: str | None) -> set[str]:
    cleaned = "".join(ch if ch.isalnum() else " " for ch in (value or "").lower())
    return {w for w in cleaned.split() if len(w) > 2}


def _trade_words(trade_key: str | None) -> set[str]:
    out: set[str] = set()
    for word in _words((trade_key or "").replace("_", " ")):
        out |= set(TRADE_WORK.get(word.removesuffix("s"), ()))
    return out


def known_trade(trade_key: str | None) -> bool:
    """A trade whose work Mesiri knows (``TRADE_WORK``): its days go only to lines of that work."""
    return bool(_trade_words(trade_key))


def fitting_lines(trade_key: str | None, activities: Iterable[str] | None, names: Mapping[Any, str]) -> list[Any]:
    """The one rule for which BOQ lines a site-day of one trade may go to (``names``: line -> its work and section).

    A trade Mesiri knows goes only to the lines of its work, or that attendance's own words name (masons never to the
    steel); any other trade (helpers) to those its words name, else to every line given. Used by the automatic split
    and by the line suggested to a person, so the two never disagree."""
    said = _trade_words(trade_key) | _words(" ".join(activities or []))
    fits = [ln for ln, name in names.items() if said & _words(name)]
    return fits if known_trade(trade_key) else (fits or list(names))


def suggest_for(group: Mapping[str, Any], worked_on: Mapping[tuple, Mapping[Any, str]]) -> Any:
    """The line to offer a person for a site-day of one trade nobody put on a line, or None.

    ``worked_on``: per (site_id, work_date) as ``group_key`` writes them, the lines work was reported on -> name.
    That day's work at the site first, then the nearest other day's at the same site (masons idle at the Main block
    on Monday are offered the plastering they did on Friday, never the conduits that were the only work on Monday).
    Only lines ``fitting_lines`` allows; when none fits, nothing is offered: a person picks."""
    site, day = group_key(group["site_id"], group["work_date"], None)[:2]
    days = sorted((d for (s, d) in worked_on if s == site), key=lambda d: (d != day, abs(_day(d) - _day(day)), d))
    for d in days:
        fits = fitting_lines(group.get("trade_key"), group.get("activities"), worked_on[(site, d)])
        if fits:
            return fits[0]
    return None


def _day(value: str) -> int:
    import datetime

    return datetime.date.fromisoformat(value[:10]).toordinal()


#: BOQ-02b: a line never takes more of a day's labour by itself than this many times the labour budget its work that
#: day earned (done x labour rate). What is left stays "not on a BOQ line": shown, for a person to put.
EARNED_CAP = Decimal(2)


def auto_split(
    groups: Iterable[Mapping[str, Any]],
    allocations: Iterable[Mapping[str, Any]],
    worked: Mapping[tuple, Mapping[Any, Any]],
    skip: Iterable[tuple] = (),
) -> list[dict[str, Any]]:
    """BOQ-02: the man-days of each site-day-trade nobody split, put on the lines that site's work went to that day
    (approved 15 Nov 2026: "split by work done"; D-CC2 had left them on no line).

    ``worked``: per (site_id, work_date) as ``group_key`` writes them, the BOQ lines work was counted on that day ->
    {"name", "earned"} (``earned``: the labour budget that day's work there earned; None when it can't be told).
    ``skip``: group keys a person took off every line (never put back).

    Which lines (BOQ-02b, only where the reported work plausibly covers it):
    - a trade Mesiri knows (``TRADE_WORK``: masons, bar benders, carpenters ...) goes only to the lines it does, or
      that attendance's own words name; none of them worked that day: it stays off every line (masons never land
      on the steel just because steel was the only work reported);
    - any other trade (helpers) is shared over every line worked that day;
    - the man-days are shared evenly, but no line takes more than ``EARNED_CAP`` x what its work earned that day,
      skilled trades first; the rest stays "not on a BOQ line". A line with no labour rate has no cap.
    A group a person split, or a day whose split was kept (rows exist), is never touched.
    Returns allocation rows like the stored ones (site_id, work_date, trade_key, planned_item_id, man_days), ``auto``.
    """
    split = {group_key(a["site_id"], a["work_date"], a["trade_key"]) for a in allocations} | set(skip)
    room: dict[tuple, Decimal | None] = {}
    out: list[dict[str, Any]] = []

    def known(g: Mapping[str, Any]) -> bool:
        return known_trade(g.get("trade_key"))

    for g in sorted(groups, key=lambda g: not known(g)):  # skilled trades first: they take the room first
        key = group_key(g["site_id"], g["work_date"], g["trade_key"])
        man_days = Decimal(g["man_days"])
        lines = worked.get(key[:2]) or {}
        if key in split or man_days <= 0 or not lines:
            continue
        targets = fitting_lines(g.get("trade_key"), g.get("activities"), {ln: info["name"] for ln, info in lines.items()})
        if not targets:
            continue
        per_day = Decimal(g["cost"]) / man_days if Decimal(g.get("cost") or 0) > 0 else Decimal(0)
        each = (man_days / len(targets)).quantize(_CENT, rounding=ROUND_HALF_UP)
        given = _ZERO
        for i, line_id in enumerate(targets):
            r = (key[0], key[1], line_id)
            if r not in room:
                earned = lines[line_id].get("earned")
                room[r] = None if earned is None else Decimal(earned) * EARNED_CAP
            md = man_days - given if i == len(targets) - 1 else each  # the last line takes the rounding
            if room[r] is not None and per_day > 0:
                md = min(md, (room[r] / per_day).quantize(_CENT, rounding=ROUND_HALF_UP))
                room[r] -= md * per_day
            given += md
            if md > 0:
                out.append({"site_id": g["site_id"], "work_date": g["work_date"], "trade_key": g["trade_key"],
                            "planned_item_id": line_id, "man_days": md, "auto": True})
    return out


def worked_lines(work: Iterable[Mapping[str, Any]], lines: Mapping[Any, Mapping[str, Any]]) -> dict[tuple, dict]:
    """Per (site, day), the BOQ lines work was counted on (``boq_router.counted_work`` rows) -> {"name", "earned"}
    (``name``: the line's work and, when the line carries it, its section's name, for matching a trade):
    the labour budget that day's work earned there (quantity in the line's unit x its labour rate; None when the
    line has no labour rate or the work was in another unit), for ``auto_split``."""
    out: dict[tuple, dict] = {}
    for w in work:
        line = lines.get(w["line_id"])
        if line is None:
            continue
        day = out.setdefault(group_key(w["site_id"], w["work_date"], None)[:2], {})
        # The section's name is matched too: a line is often named for the element ("Plinth beam", "Lintel") and only
        # its section says the work ("B. CONCRETE"), so a mason's day would otherwise never reach it.
        name = " ".join(x for x in (line["work_type"], line.get("section")) if x)
        info = day.setdefault(w["line_id"], {"name": name, "earned": Decimal(0)})
        rate = line.get("labour_rate")
        if info["earned"] is None or rate is None or w["quantity"] is None:
            info["earned"] = None
        else:
            info["earned"] += Decimal(w["quantity"]) * Decimal(rate)
    return out
