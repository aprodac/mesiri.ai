"""Stock for a period, and when a material is running low (PRC-17).

"How many bags of cement are left, and what came and went this week?" -- for any date range, per site and
material: what the site held before the period (opening), what was delivered and used in it, anything else that
moved stock (opening stock, adjustments, corrections; ``adjusted``), and what it held at the end (closing).
opening + received + adjusted - used == closing, always (the daily report's rule, BE-12, over a range).

Running low is the stock card's rule (classic ``channel/cards/stock.py``), owned here for the API: at or below
zero, or fewer than ``LOW_DAYS`` days left at the last ``USE_WINDOW_DAYS`` days' use. Nothing is entered by hand:
the use already recorded decides.

PRC-47: when the office set a minimum for the site and material (``stock_levels``), it is the second rule of the same
function: below the minimum (``below_min``, what the site holds now) is the chip on the row, and running low also when
what the site holds plus what is on order is under the minimum. No minimum: exactly as before.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

#: Fewer days of stock than this is running low.
LOW_DAYS = 3
#: Days of use, up to the end of the period, that decide the daily rate.
USE_WINDOW_DAYS = 7

#: Deliveries and use, as the daily report counts them (application/dpr/assembly.py).
RECEIVED_REASONS = ("RECEIVED", "RETURN_IN", "TRANSFER_IN")
USED_REASONS = ("CONSUMED", "WASTAGE", "RETURN_TO_VENDOR", "TRANSFER_OUT")


def finish_row(row: dict[str, Any], on_order: Decimal = Decimal(0), level: dict[str, Any] | None = None) -> dict[str, Any]:
    """Add ``adjusted``, ``days_left``, ``on_order``, ``running_low`` and the minimum to one site+material row of sums.

    PRC-27: ``on_order`` (still to come on open purchase orders) counts towards running low: stock that is already
    ordered is not "what to order". ``days_left`` stays what the site holds now. PRC-47: ``level`` is the site's
    ``stock_levels`` row for the material (``min_qty``, ``reorder_qty``), when one is set."""
    opening = Decimal(str(row.get("opening") or 0))
    closing = Decimal(str(row.get("closing") or 0))
    received = Decimal(str(row.get("received") or 0))
    used = Decimal(str(row.get("used") or 0))
    recent = Decimal(str(row.pop("used_recently", 0) or 0))
    daily = recent / USE_WINDOW_DAYS
    days_left = None if daily <= 0 or closing <= 0 else max(0, math.floor(closing / daily))
    minimum = Decimal(str(level["min_qty"])) if level and level.get("min_qty") is not None else None
    reorder = Decimal(str(level["reorder_qty"])) if level and level.get("reorder_qty") is not None else None
    held = closing + on_order
    low = held <= 0 or (daily > 0 and held / daily < LOW_DAYS)
    return {
        **row,
        "opening": opening,
        "received": received,
        "used": used,
        "adjusted": closing - opening - received + used,
        "closing": closing,
        "days_left": days_left,
        "on_order": on_order,
        "running_low": low or (minimum is not None and held < minimum),
        "min_qty": minimum,
        "reorder_qty": reorder,
        "below_min": minimum is not None and closing < minimum,
    }


def reorder_quantity(closing: Decimal, on_order: Decimal, minimum: Decimal, reorder: Decimal | None) -> Decimal:
    """PRC-47: how much a draft request or RFQ asks for when an item is below its minimum: the reorder quantity the
    office set, else enough to bring the site back to twice the minimum (what it holds and what is coming counted)."""
    if reorder is not None and reorder > 0:
        return reorder
    return max(Decimal(0), minimum * 2 - closing - on_order).quantize(Decimal(1), rounding="ROUND_CEILING")


def suggest_minimum(used_last_week: Decimal, lead_days: int) -> tuple[Decimal, Decimal] | None:
    """PRC-47 "suggest from use": a minimum of a week's average use plus the supplier's lead time at that use
    (``USE_WINDOW_DAYS`` + lead days of use), and a reorder quantity of two weeks' use. None when nothing was used."""
    used = Decimal(used_last_week)
    if used <= 0:
        return None
    ceil = Decimal(1)
    # Multiplied before divided: 10 used in a week is exactly 20 for two weeks, not 20.0000001 rounded up to 21.
    minimum = (used * (USE_WINDOW_DAYS + max(0, lead_days)) / USE_WINDOW_DAYS).quantize(ceil, rounding="ROUND_CEILING")
    return minimum, (used * 14 / USE_WINDOW_DAYS).quantize(ceil, rounding="ROUND_CEILING")
