"""PRC-34: GST on a rate, the one rule every price comparison reads (Rates, orders, and later quotations).

A rate is stored as said (``unit_cost`` on a delivery, ``rate`` on an order line) with two optional facts beside it:
``gst_percent`` and ``rate_includes_gst``. From them:

- ``with_gst``: what the company pays per unit, GST included;
- ``before_gst``: the shop's price before GST;
- ``cost``: what the unit costs the company, by D-CC8 (decided 8 Nov 2026, the rule ``finance/costs.py`` uses for
  expenses): before GST when the supplier has a GSTIN (the GST can be claimed back), else with GST (it cannot).
  Rates compares suppliers on ``cost``, so a shop without GST at 400 and a registered shop at 360 + 18% compare
  as they really cost.

Not known (no ``gst_percent`` or the rate not said to include / exclude it): every figure is the rate as entered and
``known`` is false; the page says so instead of guessing. 0% is known: no GST charged.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

#: The GST slabs offered first in the forms (any 0-100 is accepted: cess and odd rates exist).
SLABS = (Decimal("0"), Decimal("5"), Decimal("12"), Decimal("18"), Decimal("28"))

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class GstRate:
    entered: Decimal
    with_gst: Decimal
    before_gst: Decimal
    cost: Decimal
    known: bool
    percent: Decimal | None
    includes: bool | None
    claimable: bool


def split(rate: Decimal | int | str, percent: Decimal | int | str | None, includes: bool | None, *,
          supplier_gstin: str | None = None) -> GstRate:
    """The rate with and before GST, and what it costs (D-CC8). ``supplier_gstin``: the supplier's GSTIN, if any."""
    entered = Decimal(rate)
    pct = None if percent is None else Decimal(percent)
    known = pct is not None and (includes is not None or pct == 0)
    if not known:
        return GstRate(entered, entered, entered, entered, False, pct, includes, False)
    factor = 1 + pct / 100
    if pct == 0:
        with_gst = before = entered
    elif includes:
        with_gst, before = entered, entered / factor
    else:
        with_gst, before = entered * factor, entered
    claimable = bool(supplier_gstin and supplier_gstin.strip()) and pct > 0
    return GstRate(entered, with_gst, before, before if claimable else with_gst, True, pct, includes, claimable)


def money(value: Decimal | None) -> str | None:
    return None if value is None else str(Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP))


def out(g: GstRate) -> dict:
    """The GST part of a rate in an API answer."""
    return {
        "rate_entered": money(g.entered),
        "rate_with_gst": money(g.with_gst),
        "rate_before_gst": money(g.before_gst),
        "gst_percent": None if g.percent is None else format(g.percent.normalize(), "f"),
        "rate_includes_gst": g.includes,
        "gst_known": g.known,
        "gst_claimable": g.claimable,
    }
