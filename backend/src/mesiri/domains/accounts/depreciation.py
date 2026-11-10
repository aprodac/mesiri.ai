"""ACC-16 (D-ACC9): what each fixed asset is worth, year by year. Pure, no I/O: the register and the sweep both use it.

- **WDV** (written-down value, the Income-tax way and the default): each financial year the asset loses ``rate`` % of
  its value at the start of the year. An asset first put to use in the year for **less than 180 days** gets half the
  rate that year (section 32, second proviso). No depreciation in the year it is sold or scrapped (the block rule).
- **SLM** (straight line, Companies Act Schedule II): ``(cost − salvage) / useful life`` a year, by the days it was
  in use in the year (put to use, sold), never below the salvage value.

An asset owned before the books start (``books_from``) comes in at its value at the start of that financial year:
cost less ``opening_depreciation`` (what was written off before).
"""

from __future__ import annotations

import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from mesiri.domains.accounts import periods

_C = Decimal("0.01")
_ZERO = Decimal(0)


def _m(v: Any) -> Decimal:
    return Decimal(v or 0).quantize(_C, rounding=ROUND_HALF_UP)


def first_year(a: dict[str, Any]) -> datetime.date:
    """The start of the first financial year the books depreciate the asset in."""
    start = a.get("books_from") or a["acquired_on"]
    return periods.fy_start(max(start, a["acquired_on"]))


def in_use_from(a: dict[str, Any]) -> datetime.date:
    return a.get("put_to_use_on") or a["acquired_on"]


def schedule(a: dict[str, Any], until: datetime.date) -> list[dict[str, Any]]:
    """Each financial year from the first until the one holding ``until`` (today): opening value, depreciation, closing
    value, the day its depreciation is posted (the year's last day, or the day it was sold) and whether that day is
    past (``posted``: a year is written down once it is over, so March can be closed after it).

    ``a``: cost, acquired_on, put_to_use_on, method, rate, useful_life_years, salvage_value, opening_depreciation,
    books_from, disposed_on."""
    cost = _m(a["cost"])
    salvage = _m(a.get("salvage_value"))
    value = cost - _m(a.get("opening_depreciation"))
    used_from = in_use_from(a)
    disposed = a.get("disposed_on")
    out = []
    fy = first_year(a)
    while fy <= until:
        end = periods.fy_end(fy)
        opening = value
        dep = _ZERO
        sold_this_year = disposed is not None and fy <= disposed <= end
        if disposed is not None and disposed < fy:
            break
        if used_from <= end:
            if a["method"] == "wdv":
                if not sold_this_year:
                    rate = Decimal(str(a["rate"])) / 100
                    if fy <= used_from and (end - used_from).days + 1 < 180:
                        rate /= 2
                    dep = _m(opening * rate)
            else:
                yearly = (cost - salvage) / Decimal(str(a["useful_life_years"]))
                start = max(fy, used_from)
                stop = min(end, disposed) if sold_this_year else end
                days = (stop - start).days + 1
                dep = _m(yearly * days / ((end - fy).days + 1)) if days > 0 else _ZERO
                dep = min(dep, max(opening - salvage, _ZERO))
        value = opening - dep
        post_on = disposed if sold_this_year else end
        out.append({"financial_year": periods.fy_label(fy), "starts_on": fy, "ends_on": end, "opening": opening,
                    "depreciation": dep, "closing": value, "post_on": post_on, "posted": post_on < until or sold_this_year,
                    "disposed_on": disposed if sold_this_year else None})
        if sold_this_year:
            break
        fy = end + datetime.timedelta(days=1)
    return out


def value_on(a: dict[str, Any], day: datetime.date, today: datetime.date) -> Decimal:
    """The book value on a day: the opening value less the depreciation posted on or before it."""
    value = _m(a["cost"]) - _m(a.get("opening_depreciation"))
    for r in schedule(a, today):
        if r["posted"] and r["post_on"] <= day:
            value = r["closing"]
    return value
