"""The receipt card -- one Swiss-minimal stylesheet and one template.

A white 620 px card, square corners, no shadows. Colour carries the record
type (work green, labour blue, material amber, issue red, expense purple) and
so does a shape (■ ● ▲ ▼ ◆ ▬), so the card still reads without colour.
data.py decides what goes on the card; this file only decides how it looks.

Fonts are embedded (Inter, plus Noto Sans Malayalam / Devanagari for the
scripts people write notes in): the page runs with no network at all (see
channel/locked_page.py), so nothing may be fetched. All three are SIL OFL;
the licence is in fonts/OFL.txt.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from .data import KIND_STYLE, STATUS_DRAFT, STATUS_SAVED, ReceiptData, ReceiptKind

if TYPE_CHECKING:
    from jinja2 import Template

_FONT_DIR = Path(__file__).parent / "fonts"

_INK = "#111111"
_SUB = "#6B7280"
_LINE = "#E5E7EB"

_SHAPES = {
    "square": '<rect x="1" y="1" width="12" height="12"/>',
    "circle": '<circle cx="7" cy="7" r="6.2"/>',
    "up": '<polygon points="7,0.8 13.4,12.6 0.6,12.6"/>',
    "down": '<polygon points="0.6,1.4 13.4,1.4 7,13.2"/>',
    "diamond": '<polygon points="7,0 14,7 7,14 0,7"/>',
    "bar": '<rect x="0" y="4" width="14" height="6"/>',
    "ring": '<circle cx="7" cy="7" r="5.2" fill="none" stroke-width="2"/>',
}


@lru_cache(maxsize=1)
def _font_css() -> str:
    """@font-face rules with the fonts inlined as data URIs (cached: read once)."""

    def face(family: str, file: str, weight: str, unicode_range: str = "") -> str:
        data = base64.b64encode((_FONT_DIR / file).read_bytes()).decode("ascii")
        rng = f"unicode-range: {unicode_range};" if unicode_range else ""
        return (
            f'@font-face {{ font-family: "{family}"; font-weight: {weight}; font-style: normal; '
            f'src: url(data:font/woff2;base64,{data}) format("woff2"); {rng} }}\n'
        )

    return (
        face("Inter", "Inter.woff2", "100 900")
        + face("Noto Sans Malayalam", "NotoSansMalayalam.woff2", "400 700", "U+0D00-0D7F")
        + face("Noto Sans Devanagari", "NotoSansDevanagari.woff2", "400 700", "U+0900-097F")
    )


#: Live 29 Oct: a card waiting for Save and a saved card must not look alike, whatever
#: the record: the tag and the stripe across the top say which (amber / green).
TO_SAVE_COLOUR = "#B45309"
SAVED_COLOUR = "#15803D"


def status_colour(status: str, kind_colour: str) -> str:
    """The tag's colour: amber while it waits for Save, green once saved; an undone
    or late card keeps its record's colour."""
    if STATUS_DRAFT in status:
        return TO_SAVE_COLOUR
    if STATUS_SAVED in status:
        return SAVED_COLOUR
    return kind_colour


_STYLE = """
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { background: #FFFFFF; }
body { width: 620px; font-family: "Inter", "Noto Sans Malayalam", "Noto Sans Devanagari",
  "Noto Sans", sans-serif; color: {{ ink }}; font-variant-numeric: tabular-nums;
  -webkit-font-smoothing: antialiased; }
.card { width: 620px; background: #FFFFFF; padding: 22px 32px 22px; border-top: 6px solid {{ status_colour }}; }
.top { display: flex; align-items: center; justify-content: space-between; }
.brand { font-size: 15px; font-weight: 800; letter-spacing: 0.2em; }
.tag { display: flex; align-items: center; gap: 7px; background: {{ status_colour }}; color: #FFFFFF;
  font-size: 12px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
  padding: 7px 12px; }
.hero { margin-top: 26px; }
.cat { display: flex; align-items: center; gap: 9px; color: {{ colour }}; font-size: 13px;
  font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; }
.hero-main { display: flex; align-items: baseline; gap: 12px; margin-top: 10px; }
.num { font-size: 72px; font-weight: 700; line-height: 1; letter-spacing: -0.03em;
  color: {{ colour }}; }
.unit { font-size: 24px; font-weight: 600; color: {{ sub }}; }
.title { font-size: 30px; font-weight: 700; line-height: 1.15; letter-spacing: -0.01em;
  color: {{ colour }}; overflow-wrap: anywhere; }
.hero-status { margin-left: auto; font-size: 13px; font-weight: 700; letter-spacing: 0.12em;
  text-transform: uppercase; color: {{ colour }}; white-space: nowrap; }
.site { margin-top: 14px; font-size: 19px; font-weight: 600; line-height: 1.3;
  overflow-wrap: anywhere; }
.meta { margin-top: 4px; font-size: 14px; color: {{ sub }}; overflow-wrap: anywhere; }
.rule { height: 2px; background: #000000; margin-top: 18px; }
.row { display: grid; grid-template-columns: 22px 112px 1fr auto; column-gap: 10px;
  align-items: start; padding: 13px 0; border-bottom: 1px solid {{ line }}; }
.row .mk { padding-top: 4px; }
.row .rt { padding-top: 4px; font-size: 11px; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; color: {{ sub }}; }
.row .tx { font-size: 17px; line-height: 1.35; overflow-wrap: anywhere; min-width: 0; }
.row .vl { font-size: 17px; font-weight: 700; text-align: right; line-height: 1.35;
  white-space: nowrap; }
.row .vl.em { text-transform: uppercase; font-size: 14px; letter-spacing: 0.08em;
  padding-top: 2px; }
.row.trade { grid-template-columns: 22px 150px 1fr 44px; align-items: center; }
.row.trade .rt { padding-top: 0; font-size: 15px; letter-spacing: 0; text-transform: none;
  font-weight: 500; color: {{ ink }}; overflow-wrap: anywhere; }
.row.trade .mk { padding-top: 0; }
.bar { height: 14px; background: #EFF4FF; }
.bar i { display: block; height: 14px; background: {{ labour }}; }
.row.trade .vl { font-size: 18px; }
.old { color: #9CA3AF; text-decoration: line-through; font-weight: 500; }
.arrow { color: {{ sub }}; margin: 0 8px; }
.new { font-weight: 700; }
.more { padding: 13px 0 4px 32px; font-size: 14px; font-weight: 600; color: {{ sub }}; }
.foot { display: flex; justify-content: space-between; gap: 16px; margin-top: 16px;
  font-size: 12px; color: {{ sub }}; }
.foot .id { font-weight: 600; letter-spacing: 0.04em; }
.foot .note { text-align: right; }
"""

_BODY = """
<div class="card">
  <div class="top">
    <div class="brand">MESIRI</div>
    <div class="tag">{% if not undone and not to_save %}{{ check }}{% endif %}{{ data.status }}</div>
  </div>

  <div class="hero">
    <div class="cat">{{ marker(data.kind, 13) }}<span>{{ data.category }}</span></div>
    <div class="hero-main">
      {% if data.hero_number %}
        <span class="num">{{ data.hero_number }}</span>
        {% if data.hero_unit %}<span class="unit">{{ data.hero_unit }}</span>{% endif %}
      {% elif data.hero_title %}
        <span class="title">{{ data.hero_title }}</span>
      {% endif %}
      {% if data.hero_status %}<span class="hero-status">{{ data.hero_status }}</span>{% endif %}
    </div>
    <div class="site">{{ data.site_line }}</div>
    <div class="meta">{{ data.meta_line }}</div>
  </div>
  <div class="rule"></div>

  {% if data.correction %}
  <div class="row">
    <div class="mk">{{ marker(data.kind, 14) }}</div>
    <div class="rt">Quantity</div>
    <div class="tx"><span class="old">{{ data.correction.old_value }}</span><span class="arrow">&rarr;</span><span class="new">{{ data.correction.new_value }}</span></div>
    <div></div>
  </div>
  {% endif %}

  {% for t in data.trades %}
  <div class="row trade">
    <div class="mk">{{ marker(data.kind, 14) }}</div>
    <div class="rt">{{ t.name }}</div>
    <div class="bar"><i style="width: {{ bar_pct(t.count) }}%"></i></div>
    <div class="vl">{{ t.count }}</div>
  </div>
  {% endfor %}

  {% for r in data.rows %}
  <div class="row">
    <div class="mk">{{ marker(r.kind, 14) }}</div>
    <div class="rt">{{ r.tag }}</div>
    <div class="tx">{{ r.text }}</div>
    <div class="vl{{ ' em' if r.emphasis else '' }}"{% if r.emphasis %} style="color: {{ colour_of(r.kind) }}"{% endif %}>{{ r.value }}</div>
  </div>
  {% endfor %}

  {% if data.more %}
  <div class="more">+{{ data.more }} more &mdash; all saved</div>
  {% endif %}

  <div class="foot">
    <div class="id">{{ data.record_id }}</div>
    <div class="note">{{ data.footer_note }}</div>
  </div>
</div>
"""

_card_template: Template | None = None


def render_html(data: ReceiptData) -> str:
    # jinja2 is only required if a receipt is actually rendered -- lazy
    # import + lazy Template compilation, matching how playwright is lazily
    # imported in render.py, so the core test suite (and everything that
    # merely imports channel.receipt, e.g. runtime/dependencies.py) runs
    # without jinja2 installed. See pyproject.toml's "receipt" extra.
    global _card_template
    if _card_template is None:
        from jinja2 import Template

        # BE-36: every value is escaped (receipt text comes from WhatsApp
        # messages); only the built-in SVG markers and fonts are trusted markup.
        _card_template = Template(
            "<!doctype html><html><head><meta charset=\"utf-8\"><style>{{ fonts }}"
            + _STYLE
            + "</style></head><body>"
            + _BODY
            + "</body></html>",
            autoescape=True,
        )

    from markupsafe import Markup

    def marker(kind: ReceiptKind, size: int) -> Markup:
        style = KIND_STYLE[kind]
        return Markup(
            f'<svg width="{size}" height="{size}" viewBox="0 0 14 14" fill="{style.colour}" '
            f'stroke="{style.colour}" stroke-width="0">{_SHAPES[style.shape]}</svg>'
        )

    peak = max((t.count for t in data.trades), default=0)

    def bar_pct(count: int) -> int:
        return max(4, round(100 * count / peak)) if peak > 0 and count > 0 else 0

    check = Markup(
        '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" '
        'stroke-width="4" stroke-linecap="square"><path d="M4 12l6 6L20 6"/></svg>'
    )
    return _card_template.render(
        data=data,
        fonts=Markup(_font_css()),
        ink=_INK,
        sub=_SUB,
        line=_LINE,
        colour=KIND_STYLE[data.kind].colour,
        status_colour=status_colour(data.status, KIND_STYLE[data.kind].colour),
        to_save=STATUS_DRAFT in data.status,
        labour=KIND_STYLE[ReceiptKind.LABOUR].colour,
        colour_of=lambda kind: KIND_STYLE[kind].colour,
        undone=data.kind is ReceiptKind.UNDONE,
        marker=marker,
        bar_pct=bar_pct,
        check=check,
    )
