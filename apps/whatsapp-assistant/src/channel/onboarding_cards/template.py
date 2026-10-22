"""HTML for the onboarding cards: one Swiss-minimal stylesheet, three bodies.

540 x 675 CSS px (4:5); ReceiptRenderer's 2x scale makes the 1080 x 1350
image. White, black Inter, a 10 px tracked header over a 2 px rule, thin
grey row rules, green only for "done", one black action box at the bottom.
No other colours, no icons. Every value is escaped (the site and company
names come from the owner's messages).
"""

from __future__ import annotations

from html import escape

from channel.receipt.template import _font_css  # the same embedded Inter + Noto fonts

from .data import ProgressCard, ReadyCard, WelcomeCard

_GREEN = "#1a7f4b"
_GREY = "#9a9a9a"
_RULE = "#e3e3e3"

_STYLE = f"""
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ background: #fff; }}
body {{ width: 540px; font-family: "Inter", "Noto Sans Malayalam", "Helvetica Neue", Helvetica,
  Arial, sans-serif; color: #000; -webkit-font-smoothing: antialiased; }}
.card {{ width: 540px; height: 675px; background: #fff; padding: 36px 40px 40px; display: flex;
  flex-direction: column; }}
.head {{ font-size: 10px; font-weight: 700; letter-spacing: 0.22em; text-transform: uppercase;
  padding-bottom: 12px; border-bottom: 2px solid #000; }}
.main {{ flex: 1; display: flex; flex-direction: column; padding-top: 30px; min-height: 0; }}
.kicker {{ font-size: 13px; color: {_GREY}; margin-bottom: 14px; }}
h1 {{ font-size: 38px; font-weight: 700; line-height: 1.12; letter-spacing: -0.02em; }}
h1.ml {{ font-size: 32px; line-height: 1.3; letter-spacing: 0; }}
.sub {{ font-size: 15px; color: {_GREY}; margin-top: 10px; }}
.rows {{ margin-top: 26px; }}
.row {{ display: flex; align-items: center; gap: 14px; padding: 13px 0;
  border-top: 1px solid {_RULE}; font-size: 17px; }}
.row:last-child {{ border-bottom: 1px solid {_RULE}; }}
.row .n {{ font-size: 12px; font-weight: 700; color: {_GREY}; width: 16px; }}
.row .k {{ font-weight: 700; min-width: 74px; }}
.row .v {{ margin-left: auto; font-weight: 600; }}
.dot {{ width: 14px; height: 14px; border-radius: 50%; flex: none;
  border: 1.5px solid {_GREY}; }}
.dot.done {{ background: {_GREEN}; border-color: {_GREEN}; }}
.row.pending {{ color: #000; }}
.check {{ width: 56px; height: 56px; border-radius: 50%; background: {_GREEN};
  margin-bottom: 22px; position: relative; }}
.check::after {{ content: ""; position: absolute; left: 19px; top: 11px; width: 13px; height: 25px;
  border: solid #fff; border-width: 0 4px 4px 0; transform: rotate(45deg); }}
.foot {{ font-size: 12px; color: {_GREY}; margin-top: auto; padding-top: 14px; }}
.big {{ font-size: 84px; font-weight: 700; line-height: 1; letter-spacing: -0.04em; }}
.big span {{ color: {_GREY}; font-weight: 300; }}
.bar {{ height: 6px; background: {_RULE}; margin-top: 18px; }}
.bar i {{ display: block; height: 6px; background: {_GREEN}; }}
.action {{ background: #000; color: #fff; padding: 16px 20px; margin-top: 18px; }}
.action b {{ display: block; font-size: 10px; letter-spacing: 0.22em; text-transform: uppercase;
  margin-bottom: 7px; }}
.ml .head, .ml .action b {{ letter-spacing: 0; }}
.ml .row .k {{ min-width: 108px; }}
.action p {{ font-size: 17px; font-weight: 600; line-height: 1.35; }}
"""


def _page(body: str) -> str:
    return (
        '<!doctype html><html><head><meta charset="utf-8"><style>'
        + _font_css()
        + _STYLE
        + "</style></head><body>"
        + body
        + "</body></html>"
    )


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _headline_class(lang: str) -> str:
    return "ml" if lang == "ml" else ""


def _action(label: str, text: str) -> str:
    return f'<div class="action"><b>{_e(label)}</b><p>{_e(text)}</p></div>'


def render_welcome(card: WelcomeCard) -> str:
    rows = "".join(
        f'<div class="row"><span class="n">{i}</span><span class="k">{_e(k)}</span>'
        f"<span>{_e(v)}</span></div>"
        for i, (k, v) in enumerate(card.rows, start=1)
    )
    return _page(
        f'<div class="card {card.lang}"><div class="head">{_e(card.header)}</div><div class="main">'
        f'<div class="kicker">{_e(card.kicker)}</div>'
        f'<h1 class="{_headline_class(card.lang)}">{_e(card.headline)}</h1>'
        f'<div class="rows">{rows}</div>'
        f'<div class="foot">{_e(card.footer)}</div></div></div>'
    )


def render_ready(card: ReadyCard) -> str:
    rows = "".join(
        f'<div class="row"><span class="dot{" done" if done else ""}"></span>'
        f"<span>{_e(label)}</span>"
        + (f'<span class="v">{_e(value)}</span>' if value else "")
        + "</div>"
        for label, value, done in card.rows
    )
    return _page(
        f'<div class="card {card.lang}"><div class="head">{_e(card.header)}</div><div class="main">'
        '<div class="check"></div>'
        f'<h1 class="{_headline_class(card.lang)}">{_e(card.headline)}</h1>'
        f'<div class="sub">{_e(card.subline)}</div>'
        f'<div class="rows">{rows}</div>'
        f'<div style="margin-top:auto">{_action(card.action_label, card.action_text)}</div>'
        "</div></div>"
    )


def render_progress(card: ProgressCard) -> str:
    rows = "".join(
        f'<div class="row{"" if done else " pending"}">'
        f'<span class="dot{" done" if done else ""}"></span><span>{_e(label)}</span></div>'
        for label, done in card.steps
    )
    pct = round(100 * card.done / card.total)
    return _page(
        f'<div class="card {card.lang}"><div class="head">{_e(card.header)}</div><div class="main" '
        'style="padding-top:22px">'
        f'<div class="big">{card.done}<span> / {card.total}</span></div>'
        f'<div class="bar"><i style="width:{pct}%"></i></div>'
        f'<div class="sub">{_e(card.subline)}</div>'
        f'<div class="rows" style="margin-top:18px">{rows}</div>'
        f'<div style="margin-top:auto">{_action(card.action_label, card.action_text)}</div>'
        "</div></div>"
    )


def render_html(card: WelcomeCard | ReadyCard | ProgressCard) -> str:
    if isinstance(card, WelcomeCard):
        return render_welcome(card)
    if isinstance(card, ReadyCard):
        return render_ready(card)
    return render_progress(card)
