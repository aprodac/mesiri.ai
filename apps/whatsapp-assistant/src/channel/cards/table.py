"""The Table card: any flat lookup (workers, stock, expenses, balances, work
log) as pictures, for "send it as an image".

Same look as the Stock card (header with the site, the thick rule, a footer
bar). The rows come from ``runtime.inbound_journey.seeding._query_table``, the
one function the PDF is built from too, so the picture and the PDF always show
the same rows. A long list is split into several cards of ``ROWS_PER_IMAGE``
rows with "1/3" in the corner: three readable pictures beat one tiny one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .base import clip, render_html

#: Rows on one picture; a longer table becomes several.
ROWS_PER_IMAGE = 25

_NUMBER = re.compile(r"^[-+]?[\d,]*\.?\d+%?$")

_BODY = """
{% if subtitle %}<div class="sub tsub">{{ subtitle }}</div>{% endif %}
{% if rows %}
<table class="tbl">
  <thead><tr>{% for c in columns %}<th class="{{ 'num' if c.num }}">{{ c.name }}</th>{% endfor %}</tr></thead>
  <tbody>
  {% for r in rows %}<tr>{% for v in r %}<td class="{{ 'num' if columns[loop.index0].num }}">{{ v }}</td>{% endfor %}</tr>
  {% endfor %}
  </tbody>
</table>
{% else %}<div class="text sub">{{ empty_message }}</div>{% endif %}
"""

_STYLE = """
.tsub { margin-bottom: 14px; }
.tbl { width: 100%; border-collapse: collapse; }
.tbl th { font-size: 11px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
  color: #6B7280; text-align: left; padding: 0 8px 8px 0; border-bottom: 2px solid #111111; }
.tbl td { font-size: 15px; padding: 9px 8px 9px 0; border-bottom: 1px solid #E5E7EB;
  vertical-align: top; overflow-wrap: anywhere; }
.tbl th.num, .tbl td.num { text-align: right; padding-right: 0; padding-left: 8px; white-space: nowrap; }
.tbl tr:last-child td { border-bottom: 0; }
"""


@dataclass(frozen=True, slots=True)
class TableCard:
    title: str
    where: str
    subtitle: str | None
    columns: tuple[tuple[str, bool], ...]  # (name, right-aligned number column)
    rows: tuple[tuple[str, ...], ...]
    empty_message: str
    page: int = 1
    pages: int = 1
    total_rows: int = 0

    @property
    def footer(self) -> str:
        if not self.total_rows:
            return self.title
        return f"{self.title} · {self.total_rows} row{'s' if self.total_rows != 1 else ''}"


def _cell(value: Any) -> str:
    return clip(value, 80) if value not in (None, "") else "-"


def build_table_cards(
    *,
    title: str,
    subtitle: str | None,
    columns: list[str],
    rows: list[list[Any]],
    empty_message: str,
    where: str,
    per_image: int = ROWS_PER_IMAGE,
) -> list[TableCard]:
    """One card per ``per_image`` rows (at least one, so an empty list still
    says "nothing found")."""
    cells = [tuple(_cell(v) for v in row) for row in rows]
    numeric = tuple(
        bool(cells) and all(_NUMBER.match(row[i]) or row[i] == "-" for row in cells) and any(row[i] != "-" for row in cells)
        for i in range(len(columns))
    )
    cols = tuple(zip(columns, numeric, strict=True))
    chunks = [cells[i : i + per_image] for i in range(0, len(cells), per_image)] or [[]]
    return [
        TableCard(
            title=title,
            where=where,
            subtitle=subtitle,
            columns=cols,
            rows=tuple(chunk),
            empty_message=empty_message,
            page=n,
            pages=len(chunks),
            total_rows=len(cells),
        )
        for n, chunk in enumerate(chunks, start=1)
    ]


def table_html(card: TableCard) -> str:
    where = clip(card.where, 28)
    if card.pages > 1:
        where = f"{where} · {card.page}/{card.pages}"
    return render_html(
        _BODY,
        tag=clip(card.title, 22),
        where=where,
        footer=card.footer,
        style=_STYLE,
        subtitle=card.subtitle,
        columns=[{"name": n, "num": num} for n, num in card.columns],
        rows=card.rows,
        empty_message=card.empty_message,
    )
