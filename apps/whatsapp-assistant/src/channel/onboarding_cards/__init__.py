"""The three onboarding cards: Welcome, Site ready, Setup progress.

Swiss-minimal 4:5 images (1080x1350) sent on WhatsApp during signup. data.py
builds each card's view model from plain inputs (pure); template.py turns it
into HTML; rendering reuses channel/receipt's ReceiptRenderer."""

from __future__ import annotations

from .data import (
    STEP_KEYS,
    Lang,
    ProgressCard,
    ProgressFacts,
    ReadyCard,
    WelcomeCard,
    build_progress_card,
    build_ready_card,
    build_welcome_card,
)
from .render import detect_lang, language_to_lang, render_card_png
from .template import render_html

__all__ = [
    "STEP_KEYS",
    "Lang",
    "ProgressCard",
    "ProgressFacts",
    "ReadyCard",
    "WelcomeCard",
    "build_progress_card",
    "build_ready_card",
    "build_welcome_card",
    "detect_lang",
    "language_to_lang",
    "render_card_png",
    "render_html",
]
