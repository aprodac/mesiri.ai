"""Request 164: what a loss is worth, and how serious that makes it. One table.

"80 bags of cement wasted" was filed as Low severity for about ₹8000 of cement.
Severity of a waste / loss issue comes from its value in rupees, here; change a
threshold in ``SEVERITY_BY_VALUE`` and nothing else.
"""

from __future__ import annotations

import re
from decimal import Decimal

#: (at least this many rupees, severity), highest first.
SEVERITY_BY_VALUE: tuple[tuple[int, str], ...] = ((50000, "CRITICAL"), (5000, "HIGH"), (1000, "MEDIUM"))
_ORDER = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

WASTE_WORDS = re.compile(
    r"\bwast\w*|\bloss\b|\blosses\b|\bkalanj\w*|\bnashtam\b|\bnasht\w*|കളഞ്ഞു|നഷ്ടം|नुकसान|बर्बाद",
    re.IGNORECASE,
)


def severity_for_value(value: Decimal | float | int, current: str = "") -> str:
    """The severity a loss of ``value`` rupees calls for, never lower than ``current``."""
    chosen = next((name for floor, name in SEVERITY_BY_VALUE if value >= floor), "")
    have = current.upper()
    if have in _ORDER and (not chosen or _ORDER.index(have) >= _ORDER.index(chosen)):
        return have
    return chosen or have


def loss_line(name: str, unit: str, received: float, used: float, rate: float | None, fmt) -> str:
    """"Cement: 100 bags in · 20 used · 80 wasted · ₹100/bag · ₹8000 loss"."""
    wasted = max(received - used, 0.0)
    parts = [f"{fmt(received)} {unit} in", f"{fmt(used)} used", f"{fmt(wasted)} wasted"]
    if rate:
        parts += [f"₹{fmt(rate)}/{unit.rstrip('s')}", f"₹{fmt(wasted * rate)} loss"]
    else:
        parts.append("no cost recorded for it yet")
    return f"{name.title()}: " + " · ".join(parts)
