"""Request 164: every rupee amount the sender said must be on the card.

"Aa 100 bag cement-inu motham ₹10000 aayi" saved the bags and dropped the
₹10000 without a word. The model can forget a figure; code cannot. After items
are staged, the amounts SAID WITH A CURRENCY CUE (₹, Rs, rupees, രൂപ, /-) in
the sender's words are matched, as numbers, against every number on the card's
items (their fields and the tool arguments, plus wage x people and cost x
quantity). An amount on no item is shown on the card as a question.

Only currency-cued amounts are checked, so "Tower 2", "2nd floor", dates and
quantities are never flagged. No model call; pure functions.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

_CUE = r"(?:₹|rs\.?|inr|rupees?|rupai|രൂപ|रुपये|रुपए)"
_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_SAID = re.compile(rf"{_CUE}\s*{_NUM}|{_NUM}\s*(?:{_CUE}|/-)", re.IGNORECASE)


def _dec(raw: Any) -> Decimal | None:
    try:
        return Decimal(str(raw).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def said_amounts(text: str) -> list[Decimal]:
    """Amounts said with a currency cue, in order, each once."""
    found: list[Decimal] = []
    for match in _SAID.finditer(text or ""):
        value = _dec(match.group(1) or match.group(2))
        if value is not None and value > 0 and value not in found:
            found.append(value)
    return found


def _walk(value: Any, out: set[Decimal]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float, Decimal)):
        if (d := _dec(value)) is not None:
            out.add(d)
    elif isinstance(value, str):
        if re.fullmatch(r"\s*\d[\d,]*(?:\.\d+)?\s*", value) and (d := _dec(value)) is not None:
            out.add(d)
    elif isinstance(value, dict):
        for v in value.values():
            _walk(v, out)
        for per, count in (("daily_wage", "headcount"), ("unit_cost", "quantity"), ("rate", "quantity")):
            a, b = _dec(value.get(per)), _dec(value.get(count) or (1 if per == "daily_wage" and per in value else None))
            if a is not None and b is not None:
                out.add(a * b)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _walk(v, out)


def kept_amounts(*sources: Any) -> set[Decimal]:
    out: set[Decimal] = set()
    for source in sources:
        _walk(source, out)
    return {d.normalize() for d in out}


def unkept(said: str, *sources: Any) -> list[Decimal]:
    """The amounts in ``said`` that none of ``sources`` carries."""
    have = kept_amounts(*sources)
    return [a for a in said_amounts(said) if a.normalize() not in have]


def show(amount: Decimal) -> str:
    return f"₹{amount:,.0f}".replace(",", "") if amount == amount.to_integral_value() else f"₹{amount}"
