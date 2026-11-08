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
