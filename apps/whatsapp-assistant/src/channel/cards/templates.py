"""HTML for the answer cards sent as WhatsApp images (WA-14).

Two layouts, both pure (data in, HTML string out, no I/O):

- ``TableCard``: a titled table, e.g. site stock -- rows of a name plus a few
  numbers, some rows highlighted (running low, overdue).
- ``RosterCard``: people grouped by status, e.g. who has reported today and
  who hasn't.

Every value is user or tenant data (material names, people, site names), so
the Jinja environment autoescapes everything. Unlike the receipt and DPR
templates (BE-36), nothing here is ever rendered raw: markup in a name shows
as text and cannot make the renderer fetch a URL.

Sized for a phone. WhatsApp shows a 680 px image at roughly half size, so
type is set large (24 px rows), and a card stops at ``MAX_ROWS`` rows and
says how many more there are -- the full list belongs in a PDF, not an
image nobody can read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jinja2 import Environment, Template

#: Rows drawn on one card before it switches to "+ N more".
MAX_ROWS = 12

_INK = "#1B232B"
_SUB = "#5A6672"
_LINE = "#E6EAEE"
_HEAD = "#2F4D63"
_FLAG = "#B3261E"
_OK = "#2E7D4F"
_WAIT = "#B4541B"


@dataclass(frozen=True, slots=True)
class TableCard:
    """A titled table. ``numeric_columns`` are right-aligned (column
    indexes). ``flagged_rows`` are row indexes drawn in the warning colour
    with a marker; ``flag_note`` explains the marker in the footer."""

    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    subtitle: str = ""
    numeric_columns: frozenset[int] = field(default_factory=frozenset)
    flagged_rows: frozenset[int] = field(default_factory=frozenset)
    flag_note: str = ""
    footer: str = ""


@dataclass(frozen=True, slots=True)
class RosterPerson:
    name: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RosterGroup:
    """One status group. ``tone`` picks the marker colour: ``"ok"``,
    ``"wait"`` or ``"neutral"``."""

    label: str
    people: tuple[RosterPerson, ...]
    tone: str = "neutral"


@dataclass(frozen=True, slots=True)
class RosterCard:
    title: str
    groups: tuple[RosterGroup, ...]
    subtitle: str = ""
    footer: str = ""


_BASE_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #EEF1F4; padding: 16px;
         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans",
                      "Noto Sans Malayalam", "Noto Sans Devanagari", Roboto, Arial, sans-serif;
         color: {{ ink }}; }
  .card { width: 648px; background: #FFFFFF; border-radius: 16px; overflow: hidden; }
  .head { background: {{ head }}; color: #FFFFFF; padding: 22px 26px 18px; }
  .title { font-size: 30px; font-weight: 700; line-height: 1.2; }
  .subtitle { font-size: 19px; opacity: .85; margin-top: 6px; }
  .foot { display: flex; justify-content: space-between; gap: 16px; padding: 14px 26px 18px;
          font-size: 17px; color: {{ sub }}; border-top: 1px solid {{ line }}; }
  .brand { font-weight: 700; color: {{ head }}; white-space: nowrap; }
"""

_TABLE_SRC = (
    """<!doctype html>
<html><head><meta charset="utf-8"><style>"""
    + _BASE_CSS
    + """
  table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  th { font-size: 16px; text-transform: uppercase; letter-spacing: .05em; color: {{ sub }};
       font-weight: 600; text-align: left; padding: 14px 26px 8px; }
  td { font-size: 24px; padding: 11px 26px; border-top: 1px solid {{ line }};
       vertical-align: top; overflow-wrap: anywhere; }
  .num { text-align: right; white-space: nowrap; }
  tr.flag td { color: {{ flag }}; font-weight: 600; }
  .mark { font-size: 15px; margin-right: 6px; vertical-align: 3px; }
  .more td { color: {{ sub }}; font-size: 20px; font-style: italic; }
</style></head><body>
<div class="card">
  <div class="head">
    <div class="title">{{ card.title }}</div>
    {% if card.subtitle %}<div class="subtitle">{{ card.subtitle }}</div>{% endif %}
  </div>
  <table>
    <tr>{% for col in card.columns %}<th{% if loop.index0 in card.numeric_columns %} class="num"{% endif %}>{{ col }}</th>{% endfor %}</tr>
    {% for row in shown %}
    <tr{% if row[0] in card.flagged_rows %} class="flag"{% endif %}>
      {% for cell in row[1] %}<td{% if loop.index0 in card.numeric_columns %} class="num"{% endif %}>{% if loop.first and row[0] in card.flagged_rows %}<span class="mark">&#9650;</span>{% endif %}{{ cell }}</td>{% endfor %}
    </tr>
    {% endfor %}
    {% if more %}<tr class="more"><td colspan="{{ card.columns|length }}">+ {{ more }} more</td></tr>{% endif %}
  </table>
  <div class="foot">
    <span>{% if card.flagged_rows and card.flag_note %}&#9650; {{ card.flag_note }}{% else %}{{ card.footer }}{% endif %}</span>
    <span class="brand">Mesiri</span>
  </div>
</div>
</body></html>"""
)

_ROSTER_SRC = (
    """<!doctype html>
<html><head><meta charset="utf-8"><style>"""
    + _BASE_CSS
    + """
  .group { padding: 16px 26px 6px; }
  .group + .group { border-top: 1px solid {{ line }}; }
  .label { font-size: 17px; text-transform: uppercase; letter-spacing: .05em; font-weight: 700;
           margin-bottom: 6px; }
  .ok .label { color: {{ ok }}; }
  .wait .label { color: {{ wait }}; }
  .neutral .label { color: {{ sub }}; }
  .person { display: flex; justify-content: space-between; gap: 18px; padding: 8px 0;
            font-size: 24px; }
  .name { font-weight: 600; overflow-wrap: anywhere; }
  .detail { color: {{ sub }}; font-size: 20px; text-align: right; }
  .dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%;
         margin-right: 12px; vertical-align: 3px; }
  .ok .dot { background: {{ ok }}; }
  .wait .dot { background: {{ wait }}; }
  .neutral .dot { background: {{ sub }}; }
  .more { color: {{ sub }}; font-size: 20px; font-style: italic; padding: 4px 0 8px; }
</style></head><body>
<div class="card">
  <div class="head">
    <div class="title">{{ card.title }}</div>
    {% if card.subtitle %}<div class="subtitle">{{ card.subtitle }}</div>{% endif %}
  </div>
  {% for group, people, more in groups %}
  <div class="group {{ group.tone }}">
    <div class="label">{{ group.label }}</div>
    {% for person in people %}
    <div class="person"><span class="name"><span class="dot"></span>{{ person.name }}</span>{% if person.detail %}<span class="detail">{{ person.detail }}</span>{% endif %}</div>
    {% endfor %}
    {% if more %}<div class="more">+ {{ more }} more</div>{% endif %}
  </div>
  {% endfor %}
  <div class="foot"><span>{{ card.footer }}</span><span class="brand">Mesiri</span></div>
</div>
</body></html>"""
)

_env: Environment | None = None
_compiled: dict[str, Template] = {}


def _template(source: str) -> Template:
    # jinja2 is imported lazily, same as channel/receipt/template.py, so
    # importing this module needs no optional dependency. Compiled once per
    # layout, not per render.
    global _env
    if _env is None:
        from jinja2 import Environment

        _env = Environment(autoescape=True)
    if source not in _compiled:
        _compiled[source] = _env.from_string(source)
    return _compiled[source]


def _colours() -> dict[str, str]:
    return {
        "ink": _INK,
        "sub": _SUB,
        "line": _LINE,
        "head": _HEAD,
        "flag": _FLAG,
        "ok": _OK,
        "wait": _WAIT,
    }


def render_table_card_html(card: TableCard) -> str:
    shown = list(enumerate(card.rows))[:MAX_ROWS]
    more = max(0, len(card.rows) - MAX_ROWS)
    return _template(_TABLE_SRC).render(card=card, shown=shown, more=more, **_colours())


def render_roster_card_html(card: RosterCard) -> str:
    # The row budget is shared across groups in order, so a long first group
    # can't push a short "not yet" group off the card entirely: every group
    # keeps at least one visible row when it has people.
    budget = MAX_ROWS
    groups = []
    for index, group in enumerate(card.groups):
        groups_left = len(card.groups) - index - 1
        allowance = max(1, budget - groups_left)
        people = group.people[:allowance]
        budget = max(0, budget - len(people))
        groups.append((group, people, len(group.people) - len(people)))
    return _template(_ROSTER_SRC).render(card=card, groups=groups, **_colours())
