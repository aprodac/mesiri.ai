"""Rendering and language choice for the onboarding cards.

The PNG comes from channel/receipt's ReceiptRenderer (same Chromium pool,
same ``.card`` selector). A card is an extra: any failure returns None and
the caller sends its plain text instead, so onboarding is never blocked.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from .data import Lang, ProgressCard, ReadyCard, WelcomeCard
from .template import render_html

if TYPE_CHECKING:
    from channel.receipt import ReceiptRenderer

logger = logging.getLogger(__name__)

_MALAYALAM = re.compile("[ഀ-ൿ]")


def detect_lang(*texts: str | None) -> Lang:
    """"ml" when any of the owner's messages is written in Malayalam script."""
    return "ml" if any(t and _MALAYALAM.search(t) for t in texts) else "en"


def language_to_lang(language: str | None) -> Lang:
    """From the language Mesiri remembers for a sender (reply_language.py):
    Malayalam, in Malayalam script or in English letters, gets the Malayalam card."""
    value = str(language or "").strip().lower()
    return "ml" if value in {"malayalam", "ml"} else "en"


async def render_card_png(
    renderer: ReceiptRenderer | None, card: WelcomeCard | ReadyCard | ProgressCard
) -> bytes | None:
    """The card as a 1080x1350 PNG, or None if it could not be rendered."""
    if renderer is None:
        return None
    try:
        return await renderer.render_png(render_html(card))
    except Exception:  # noqa: BLE001 -- never block onboarding over a picture
        logger.exception("onboarding_card.render_failed type=%s", type(card).__name__)
        return None
