"""Stock for a period, and when a material is running low (PRC-17).

"How many bags of cement are left, and what came and went this week?" -- for any date range, per site and
material: what the site held before the period (opening), what was delivered and used in it, anything else that
moved stock (opening stock, adjustments, corrections; ``adjusted``), and what it held at the end (closing).
opening + received + adjusted - used == closing, always (the daily report's rule, BE-12, over a range).

Running low is the stock card's rule (classic ``channel/cards/stock.py``), owned here for the API: at or below
zero, or fewer than ``LOW_DAYS`` days left at the last ``USE_WINDOW_DAYS`` days' use. Nothing is entered by hand:
the use already recorded decides.
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


def finish_row(row: dict[str, Any]) -> dict[str, Any]:
    """Add ``adjusted``, ``days_left`` and ``running_low`` to one site+material row of sums."""
    opening = Decimal(str(row.get("opening") or 0))
    closing = Decimal(str(row.get("closing") or 0))
    received = Decimal(str(row.get("received") or 0))
    used = Decimal(str(row.get("used") or 0))
    recent = Decimal(str(row.pop("used_recently", 0) or 0))
    daily = recent / USE_WINDOW_DAYS
    days_left = None if daily <= 0 or closing <= 0 else max(0, math.floor(closing / daily))
    return {
        **row,
        "opening": opening,
        "received": received,
        "used": used,
        "adjusted": closing - opening - received + used,
        "closing": closing,
        "days_left": days_left,
        "running_low": closing <= 0 or (days_left is not None and closing / daily < LOW_DAYS),
    }
