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

#: kind -> (tint, colour, icon path, label). WA-262 (Ilan, 8 Nov: "let everything have a difference in the visual
#: appearance itself"): every kind of line has its own colour, icon and a label on the row, so a request never looks
#: like a delivery and an issue never like a usage; the header names the kinds on the slip.
KINDS: dict[str, tuple[str, str, str, str]] = {
    "receipt": ("#D5F1EC", "#0F766E", "M3 9l9-5 9 5v8l-9 5-9-5z M12 2v8 M9 7l3 3 3-3", "DELIVERY"),
    "usage": ("#FDE8CC", "#B4500C", "M3 9l9-5 9 5v8l-9 5-9-5z M12 13V5 M9 8l3-3 3 3", "USED"),
    "transfer": ("#D9EEF8", "#0B6E99", "M4 8h14 M14 4l4 4-4 4 M20 16H6 M10 12l-4 4 4 4", "TRANSFER"),
    "request": ("#FBE3F0", "#B0246F", "M8 4h8v3H8z M6 6H5v15h14V6h-1 M9 12h6 M9 16h4", "REQUEST"),
    "order": ("#DFE7FB", "#1E4FB8", "M3 4h3l2 11h11l2-8H7 M9 20h.5 M17 20h.5", "ORDER"),
    "labour": ("#E7E5FB", "#4338CA", "M5 13a7 7 0 0 1 14 0v2H5z M12 6V3 M3 15h18 M8 19a4 4 0 0 0 8 0", "LABOUR"),
    "work": ("#DCF1E3", "#1D7A3C", "M4 20l7-7 M14 4l6 6-3 3-6-6z M11 7l-2 2", "WORK DONE"),
    "issue": ("#FBE0DD", "#B23A2E", "M12 3l10 18H2z M12 10v5 M12 18v.5", "ISSUE"),
    "issue_close": ("#D8F3E4", "#047857", "M12 3l10 18H2z M8 14l3 3 5-6", "ISSUE CLOSED"),
    "expense": ("#F0E3FB", "#7E22CE", "M6 4h12 M6 9h12 M9 4c5 0 5 10 0 10H6l8 7", "EXPENSE"),
    "payment": ("#EAF3D6", "#4D7C0F", "M3 7h18v10H3z M3 11h18 M7 15h3", "PAYMENT"),
    "undo": ("#ECEAE7", "#57534E", "M9 7L4 12l5 5 M4 12h11a5 5 0 0 1 0 10h-2", "TAKE BACK"),
    "send": ("#E3EAF2", "#334E6E", "M3 12l18-8-7 18-3-7z M11 15l10-11", "SEND"),
    "list": ("#E6E9EE", "#46536A", "M4 6h16 M4 12h10 M4 18h7 M18 15v6 M15 18h6", "SETTING"),
}
#: Older callers' kind for any material line.
KINDS["material"] = KINDS["usage"][:3] + ("MATERIAL",)


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


def _kind(kind: str) -> tuple[str, str, str, str]:
    return KINDS.get(kind, KINDS["list"])


def _icon(kind: str) -> str:
    bg, fg, path, _label = _kind(kind)
    return (f'<span class="ic" style="background:{bg};color:{fg}"><svg viewBox="0 0 24 24"><path d="{path}" '
            'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
            "</svg></span>")


def _tag(kind: str) -> str:
    bg, fg, _path, label = _kind(kind)
    return f'<span class="tag" style="background:{bg};color:{fg}">{escape(label)}</span>'


def _row(line: SlipLine) -> str:
    new = '<span class="new">NEW</span>' if line.new else ""
    note = f"<small>{escape(line.note)}</small>" if line.note else ""
    unit = f"<small>{escape(line.unit)}</small>" if line.unit else ""
    qty = f'<span class="qty">{escape(line.quantity)}{unit}</span>' if line.quantity else '<span class="qty"></span>'
    colour = _kind(line.kind)[1]
    return (f'<li style="--k:{colour}"><span class="n">{line.number}</span>{_icon(line.kind)}'
            f'<span class="what">{_tag(line.kind)}<span class="t">{escape(line.title)}</span>{new}{note}</span>'
            f"{qty}</li>")


def render_slip_html(slip: Slip) -> str:
    """The slip as one self-contained HTML page; the renderer screenshots its ``.card``."""
    shown = slip.lines[:MAX_LINES] if len(slip.lines) <= MAX_LINES else slip.lines[: MAX_LINES - 1]
    more = len(slip.lines) - len(shown)
    rows = "".join(_row(line) for line in shown)
    if more:
        rows += f'<li class="more"><span></span><span></span><span class="what">+{more} more on the list</span></li>'
    count = f"{len(slip.lines)} line{'s' if len(slip.lines) != 1 else ''}"
    kinds = list(dict.fromkeys(line.kind for line in slip.lines))
    # WA-262: the header names what is on the slip; one kind also colours the card's frame.
    badges = "".join(_tag(k) for k in kinds)
    frame = _kind(kinds[0])[1] if len(kinds) == 1 else "#F0C48F"
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_font_css()}{_CSS}</style></head><body>
<div class="card" style="border-color:{frame}">
  <div class="hazard"></div>
  <div class="head">
    <span class="chip"><i></i>DRAFT · NOT SAVED</span>
    <span class="kinds">{badges}</span>
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
.card { width: 620px; background: #FFFAF3; overflow: hidden; border: 4px solid #F0C48F; }
.hazard { height: 14px; background: repeating-linear-gradient(135deg, #F2A541 0 18px, #2B2622 18px 36px); }
.head { display: grid; grid-template-columns: 1fr auto; gap: 10px 16px; align-items: end; padding: 22px 28px 18px;
  background: linear-gradient(180deg, #FFF1DE, #FFFAF3); }
.chip { grid-column: 1 / -1; justify-self: start; display: inline-flex; gap: 10px; align-items: center;
  background: #2B2622; color: #FFD9A6; font-weight: 800; font-size: 17px; letter-spacing: .14em;
  padding: 8px 15px; border-radius: 9px; }
.chip i { width: 12px; height: 12px; border-radius: 50%; background: #F2A541;
  box-shadow: 0 0 0 5px rgba(242,165,65,.28); }
.kinds { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 8px; }
.kinds:empty { display: none; }
.tag { display: inline-block; font-size: 14px; font-weight: 800; letter-spacing: .1em; padding: 4px 10px;
  border-radius: 7px; line-height: 1.2; }
.what .tag { display: table; margin-bottom: 5px; font-size: 13px; padding: 3px 9px; }
.site { font-weight: 800; font-size: 36px; line-height: 1.1; letter-spacing: -.01em; overflow-wrap: anywhere; }
.when { font-size: 19px; color: #8A6E52; text-align: right; white-space: nowrap; padding-bottom: 4px; }
.perf { height: 20px; background: radial-gradient(circle at 10px 10px, #E8E2D9 7px, transparent 7.5px)
  0 0 / 26px 20px repeat-x; }
ol { list-style: none; padding: 2px 22px 8px; }
li { display: grid; grid-template-columns: 30px 60px 1fr auto; gap: 16px; align-items: center; padding: 15px 0 15px 12px;
  border-bottom: 2px dashed #EAD7BF; border-left: 7px solid var(--k, transparent); margin-left: -12px; }
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
