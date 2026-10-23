"""The shared Swiss card: base.html (header, thick rule, footer bar) plus the
render step every card uses.

Black on white, letter-spaced header with the site or date at the right, big
numbers, red only for a problem, a black (or red) footer bar. Each card module
(today.py, stock.py, welcome.py) holds a small dataclass and a body template
that extends base.html. The PNG comes from channel/receipt's ReceiptRenderer
(same Chromium, same ``.card`` selector). A card is an extra: when it cannot
be made the caller sends the same words as text, so nothing is lost.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from channel.receipt.template import _font_css  # the same embedded Inter + Noto fonts

if TYPE_CHECKING:
    from jinja2 import Environment, Template

    from channel.receipt import ReceiptRenderer

logger = logging.getLogger(__name__)

_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def _env() -> Environment:
    # jinja2 is imported here, not at module level, like channel/receipt/template.py:
    # the core suite runs without it. Autoescape is on: site names, material
    # names and issue text all come from WhatsApp messages.
    from jinja2 import Environment, FileSystemLoader

    return Environment(loader=FileSystemLoader(str(_DIR)), autoescape=True)


@lru_cache(maxsize=8)
def _template(body: str, style: str) -> Template:
    return _env().from_string(
        "{% extends 'base.html' %}"
        f"{{% block style %}}{style}{{% endblock %}}"
        f"{{% block body %}}{body}{{% endblock %}}"
    )


def render_html(
    body: str,
    *,
    tag: str,
    where: str,
    footer: str,
    footer_red: bool = False,
    style: str = "",
    **context: Any,
) -> str:
    """The card's HTML: ``body`` is a Jinja template for the part between the
    rule and the footer bar, ``context`` its variables."""
    from markupsafe import Markup

    return _template(body, style).render(
        fonts=Markup(_font_css()),
        tag=tag,
        where=where,
        footer=footer,
        footer_red=footer_red,
        **context,
    )


async def render_png(renderer: ReceiptRenderer | None, html: str, *, card: str) -> bytes | None:
    """The card as a PNG, or None if it could not be rendered (logged)."""
    if renderer is None:
        return None
    try:
        return await renderer.render_png(html)
    except Exception:  # noqa: BLE001 -- never block a reply over a picture
        logger.exception("card.render_failed card=%s", card)
        return None


def clip(text: object, limit: int) -> str:
    """One line of at most ``limit`` characters, cut with an ellipsis."""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"
