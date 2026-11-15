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


def auto_split(
    groups: Iterable[Mapping[str, Any]],
    allocations: Iterable[Mapping[str, Any]],
    worked: Mapping[tuple, Mapping[Any, str]],
) -> list[dict[str, Any]]:
    """BOQ-02: the man-days of each site-day-trade nobody put on a line, put on the lines that site's work went to
    that day (approved 15 Nov 2026: "split by work done"; D-CC2 had left them on no line).

    ``worked``: per (site_id, work_date) as ``group_key`` writes them, the BOQ lines work was counted on that day
    -> each line's name. One line: all of the day on it. Several: the lines the trade does (``TRADE_WORK``, and
    the words attendance gave for the day), else every line, the man-days shared evenly. No work on a line that
    day: nothing (the day stays "not on a BOQ line", never guessed). A group a person split is never touched.
    Returns allocation rows like the stored ones (site_id, work_date, trade_key, planned_item_id, man_days) with
    ``auto`` True; they are worked out each time, so a corrected attendance or work update moves them too.
    """
    split_by_hand = {group_key(a["site_id"], a["work_date"], a["trade_key"]) for a in allocations}
    out: list[dict[str, Any]] = []
    for g in groups:
        key = group_key(g["site_id"], g["work_date"], g["trade_key"])
        man_days = Decimal(g["man_days"])
        lines = worked.get(key[:2]) or {}
        if key in split_by_hand or man_days <= 0 or not lines:
            continue
        targets = list(lines)
        if len(targets) > 1:
            said = _trade_words(g.get("trade_key")) | _words(" ".join(g.get("activities") or []))
            fits = [ln for ln, name in lines.items() if said & _words(name)]
            targets = fits or targets
        each = (man_days / len(targets)).quantize(_CENT, rounding=ROUND_HALF_UP)
        for i, line_id in enumerate(targets):
            md = man_days - each * (len(targets) - 1) if i == len(targets) - 1 else each
            out.append({"site_id": g["site_id"], "work_date": g["work_date"], "trade_key": g["trade_key"],
                        "planned_item_id": line_id, "man_days": md, "auto": True})
    return out


def worked_lines(work: Iterable[Mapping[str, Any]], names: Mapping[Any, str]) -> dict[tuple, dict[Any, str]]:
    """Per (site, day), the BOQ lines work was counted on (``boq_router.counted_work`` rows), for ``auto_split``."""
    out: dict[tuple, dict[Any, str]] = {}
    for w in work:
        if w["line_id"] in names:
            out.setdefault(group_key(w["site_id"], w["work_date"], None)[:2], {})[w["line_id"]] = names[w["line_id"]]
    return out
