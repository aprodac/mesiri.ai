"""WA-215: the draft slip, the card a ready list is shown on before Save (the "site ticket" design Ilan picked, 5 Nov).

It must never be mistaken for a saved record: a hazard-tape stripe, a dark "DRAFT · NOT SAVED" chip, warm paper and a
perforated tear line, no record number. Every line of the list is a numbered row (the numbers the ✏️ Edit list uses)
with an icon per kind and the quantity large. The receipt card (template.py) stays the SAVED card; this file only
draws the slip, from plain data (``Slip``), so it renders the same for any caller.

Fonts are the receipt's own, embedded (the page runs with no network, channel/locked_page.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

from .template import _font_css

#: Rows drawn before "+N more" (the card stays a phone-screen tall).
MAX_LINES = 8

#: kind -> (icon background, icon colour, icon path). Colour follows the receipt's kinds: material amber, labour blue,
#: work green, issue red, expense purple; a list change (new material, a size, a project) is slate.
KINDS: dict[str, tuple[str, str, str]] = {
    "material": ("#FDE8CC", "#B4500C", "M3 8l9-5 9 5v8l-9 5-9-5z M3 8l9 5 9-5 M12 13v8"),
    "labour": ("#DFE8FB", "#2459C7", "M5 13a7 7 0 0 1 14 0v2H5z M12 6V3 M3 15h18 M8 19a4 4 0 0 0 8 0"),
    "work": ("#DCF1E3", "#1D7A3C", "M4 20l7-7 M14 4l6 6-3 3-6-6z M11 7l-2 2"),
    "issue": ("#FBE0DD", "#B23A2E", "M12 3l10 18H2z M12 10v5 M12 18v.5"),
    "expense": ("#ECE3FA", "#6B3FB8", "M6 4h12 M6 9h12 M9 4c5 0 5 10 0 10H6l8 7"),
    "list": ("#E6E9EE", "#46536A", "M4 6h16 M4 12h10 M4 18h7 M18 15v6 M15 18h6"),
}


@dataclass(frozen=True)
class SlipLine:
    number: int
    kind: str
    title: str
    note: str = ""
    quantity: str = ""
    unit: str = ""
    new: bool = False


@dataclass(frozen=True)
class Slip:
    site: str
    when: str
    lines: list[SlipLine] = field(default_factory=list)


def _icon(kind: str) -> str:
    bg, fg, path = KINDS.get(kind, KINDS["list"])
    return (f'<span class="ic" style="background:{bg};color:{fg}"><svg viewBox="0 0 24 24"><path d="{path}" '
            'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
            "</svg></span>")


def _row(line: SlipLine) -> str:
    new = '<span class="new">NEW</span>' if line.new else ""
    note = f"<small>{escape(line.note)}</small>" if line.note else ""
    unit = f"<small>{escape(line.unit)}</small>" if line.unit else ""
    qty = f'<span class="qty">{escape(line.quantity)}{unit}</span>' if line.quantity else '<span class="qty"></span>'
    return (f'<li><span class="n">{line.number}</span>{_icon(line.kind)}'
            f'<span class="what"><span class="t">{escape(line.title)}</span>{new}{note}</span>{qty}</li>')


def render_slip_html(slip: Slip) -> str:
    """The slip as one self-contained HTML page; the renderer screenshots its ``.card``."""
    shown = slip.lines[:MAX_LINES] if len(slip.lines) <= MAX_LINES else slip.lines[: MAX_LINES - 1]
    more = len(slip.lines) - len(shown)
    rows = "".join(_row(line) for line in shown)
    if more:
        rows += f'<li class="more"><span></span><span></span><span class="what">+{more} more on the list</span></li>'
    count = f"{len(slip.lines)} line{'s' if len(slip.lines) != 1 else ''}"
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_font_css()}{_CSS}</style></head><body>
<div class="card">
  <div class="hazard"></div>
  <div class="head">
    <span class="chip"><i></i>DRAFT · NOT SAVED</span>
    <span class="site">{escape(slip.site or "Your site")}</span>
    <span class="when">{escape(slip.when)}</span>
  </div>
  <div class="perf"></div>
  <ol>{rows}</ol>
  <div class="foot"><span>Check it, then tap <b>Save</b></span><span>{count}</span></div>
</div></body></html>"""


_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #E8E2D9; padding: 0; font-family: "Inter", "Noto Sans Malayalam", "Noto Sans Devanagari",
  sans-serif; color: #1C1A18; -webkit-font-smoothing: antialiased; }
.card { width: 620px; background: #FFFAF3; overflow: hidden; border: 3px solid #F0C48F; }
.hazard { height: 14px; background: repeating-linear-gradient(135deg, #F2A541 0 18px, #2B2622 18px 36px); }
.head { display: grid; grid-template-columns: 1fr auto; gap: 10px 16px; align-items: end; padding: 22px 28px 18px;
  background: linear-gradient(180deg, #FFF1DE, #FFFAF3); }
.chip { grid-column: 1 / -1; justify-self: start; display: inline-flex; gap: 10px; align-items: center;
  background: #2B2622; color: #FFD9A6; font-weight: 800; font-size: 17px; letter-spacing: .14em;
  padding: 8px 15px; border-radius: 9px; }
.chip i { width: 12px; height: 12px; border-radius: 50%; background: #F2A541;
  box-shadow: 0 0 0 5px rgba(242,165,65,.28); }
.site { font-weight: 800; font-size: 36px; line-height: 1.1; letter-spacing: -.01em; overflow-wrap: anywhere; }
.when { font-size: 19px; color: #8A6E52; text-align: right; white-space: nowrap; padding-bottom: 4px; }
.perf { height: 20px; background: radial-gradient(circle at 10px 10px, #E8E2D9 7px, transparent 7.5px)
  0 0 / 26px 20px repeat-x; }
ol { list-style: none; padding: 2px 22px 8px; }
li { display: grid; grid-template-columns: 30px 60px 1fr auto; gap: 16px; align-items: center; padding: 15px 0;
  border-bottom: 2px dashed #EAD7BF; }
li:last-child { border-bottom: 0; }
.n { font-weight: 800; font-size: 21px; color: #C4620F; text-align: center; font-variant-numeric: tabular-nums; }
.ic { width: 60px; height: 60px; border-radius: 16px; display: grid; place-items: center; }
.ic svg { width: 30px; height: 30px; }
.what { min-width: 0; font-size: 25px; line-height: 1.25; }
.what .t { font-weight: 700; overflow-wrap: anywhere; }
.what small { display: block; font-size: 19px; color: #7A7067; font-weight: 500; margin-top: 2px; }
.new { display: inline-block; margin-left: 10px; vertical-align: 4px; background: #2B2622; color: #FFD9A6;
  font-size: 14px; font-weight: 800; letter-spacing: .1em; padding: 3px 10px; border-radius: 999px; }
.qty { font-weight: 800; font-size: 31px; white-space: nowrap; font-variant-numeric: tabular-nums; text-align: right; }
.qty small { font-size: 18px; font-weight: 600; color: #7A7067; margin-left: 5px; }
li.more .what { font-size: 20px; color: #8A6E52; font-weight: 600; }
.foot { display: flex; justify-content: space-between; align-items: center; padding: 16px 28px;
  background: #FFF1DE; border-top: 3px dashed #F0C48F; font-size: 19px; color: #8A4A0B; }
.foot b { font-weight: 800; }
"""
