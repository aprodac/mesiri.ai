"""The Stock card: every material on the site, one row each.

A bar per material scaled to what was received, stock in big numbers, red when
the stock is at or below zero. "≈N days at this week's use" comes from the last
seven days of usage and is left out when nothing was used. A red footer names
the materials at zero or with under three days left, and says what to do.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from workflows.readable import format_quantity

from .base import clip, render_html

#: Fewer days of stock than this is "LOW".
LOW_DAYS = 3
#: Rows shown; the rest are summarised ("+N more").
MAX_ROWS = 8

_BODY = """
{% for r in rows %}
<div class="mat">
  <div class="line1">
    <div class="name">{{ r.name }}</div>
    <div class="qty{{ ' red' if r.red }}">{{ r.stock }} <span class="unit">{{ r.unit }}</span></div>
  </div>
  <div class="track"><i class="{{ 'bad' if r.red }}" style="width: {{ r.bar_pct }}%"></i></div>
  <div class="note">{{ r.note }}</div>
</div>
{% endfor %}
{% if more %}<div class="sub more">+{{ more }} more</div>{% endif %}
"""

_STYLE = """
.mat { padding: 13px 0; border-top: 1px solid #E5E7EB; }
.mat:first-child { border-top: 0; padding-top: 0; }
.line1 { display: flex; justify-content: space-between; align-items: baseline; gap: 14px; }
.name { font-size: 19px; font-weight: 600; overflow-wrap: anywhere; min-width: 0; }
.qty { font-size: 30px; font-weight: 700; letter-spacing: -0.02em; white-space: nowrap; }
.qty .unit { font-size: 15px; font-weight: 600; color: #6B7280; letter-spacing: 0; }
.track { height: 8px; background: #EFEFEF; margin-top: 8px; }
.track i { display: block; height: 8px; background: #111111; }
.track i.bad { background: #C8102E; }
.note { margin-top: 6px; font-size: 13px; color: #6B7280; }
.more { padding-top: 10px; border-top: 1px solid #E5E7EB; }
"""


@dataclass(frozen=True, slots=True)
class StockRow:
    name: str
    unit: str
    stock: str
    bar_pct: int
    note: str
    red: bool
    low: bool
    days: int = 0


@dataclass(frozen=True, slots=True)
class StockCard:
    where: str
    rows: tuple[StockRow, ...]
    more: int

    @property
    def low(self) -> bool:
        return any(r.low for r in self.rows)

    @property
    def footer(self) -> str:
        """What is wrong, in words ("Steel is out. Cement ≈2 days left."): up to
        two materials, then "+N more", then one line on what to do."""
        low = [r for r in self.rows if r.low]
        if not low:
            return "Stock now"
        parts = [f"{r.name} is out." if r.red else f"{r.name} ≈{r.days} days left." for r in low[:2]]
        if len(low) > 2:
            parts.append(f"+{len(low) - 2} more.")
        parts.append("Order before the next pour." if any(r.red for r in low) else "Order soon.")
        return " ".join(parts)


def days_left(stock: float, used_week: float) -> float | None:
    """Days the stock lasts at this week's use, or None when nothing was used
    (or none is left): no use means no honest figure."""
    if used_week <= 0 or stock <= 0:
        return None
    return stock / (used_week / 7)


_fmt = format_quantity


def build_stock_card(
    levels: list[dict[str, Any]],
    usage_week: dict[tuple[str, str], float],
    *,
    where: str,
) -> StockCard:
    """``levels`` are MaterialInventoryQueryService.query rows; ``usage_week``
    maps (lower-cased material name, unit) to the quantity used in 7 days."""
    ordered = sorted(levels, key=lambda lvl: float(lvl["current_stock"]))  # trouble first
    rows: list[StockRow] = []
    for level in ordered[:MAX_ROWS]:
        stock = float(level["current_stock"])
        received = float(level["received"])
        left = days_left(stock, usage_week.get((str(level["material_name"]).lower(), str(level["unit"])), 0.0))
        red = stock <= 0
        low = red or (left is not None and left < LOW_DAYS)
        if red:
            note = "out of stock" if stock == 0 else "used more than recorded"
        elif left is not None:
            note = f"≈{max(1, math.floor(left))} days at this week's use"
        else:
            note = f"received {_fmt(received)}"
        bar = round(100 * stock / received) if received > 0 and stock > 0 else 0
        rows.append(
            StockRow(
                name=clip(str(level["material_name"]).title(), 26),
                unit=str(level["unit"]),
                stock=_fmt(stock),
                bar_pct=min(100, max(3, bar)) if stock > 0 else 0,
                note=note,
                red=red,
                low=low,
                days=max(1, math.floor(left)) if left is not None else 0,
            )
        )
    return StockCard(where=where, rows=tuple(rows), more=max(0, len(ordered) - MAX_ROWS))


def stock_html(card: StockCard) -> str:
    return render_html(
        _BODY,
        tag="Stock",
        where=clip(card.where, 34),
        footer=card.footer,
        footer_red=card.low,
        style=_STYLE,
        rows=card.rows,
        more=card.more,
    )
