"""Swiss image cards for the replies that were walls of text: Today (the
evening confirm), Stock, Welcome. One base (base.html), one renderer (the
receipt's Chromium). The text stays as the caption and the fallback."""

from __future__ import annotations

from .base import clip, render_png
from .payload import render_payload_card, today_payload
from .stock import StockCard, build_stock_card, days_left, stock_html
from .table import ROWS_PER_IMAGE, TableCard, build_table_cards, table_html
from .today import TodayCard, build_today_card, today_html
from .welcome import WelcomeCard, build_welcome_card, welcome_html

__all__ = [
    "ROWS_PER_IMAGE",
    "TableCard",
    "build_table_cards",
    "table_html",
    "StockCard",
    "TodayCard",
    "WelcomeCard",
    "build_stock_card",
    "build_today_card",
    "build_welcome_card",
    "clip",
    "days_left",
    "render_payload_card",
    "render_png",
    "stock_html",
    "today_html",
    "today_payload",
    "welcome_html",
]
