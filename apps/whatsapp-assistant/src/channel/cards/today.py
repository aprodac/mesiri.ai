"""The Today card: the evening confirm of a site's day in one picture.

Four tiles -- Workers, top material, Progress, Issues -- read from the day's
report payload (the same ``daily_report_versions.payload`` the DPR draft is
built from, so the numbers match the report). Labour is only READ here.
The card travels in a notification payload as a plain dict (``to_dict`` /
``from_dict``) and is rendered when the row is sent.
"""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass
from typing import Any

from .base import clip, render_html

_BODY = """
<div class="grid">
  <div class="tile">
    <div class="label">Workers</div>
    <div class="big">{{ c.workers_total }}</div>
    <div class="sub">{% if c.trades %}{% for name, n in c.trades %}{{ n }} {{ name }}{{ ' · ' if not loop.last }}{% endfor %}{% else %}no count yet{% endif %}</div>
  </div>
  <div class="tile">
    <div class="label">{{ c.material_name or 'Material' }}</div>
    {% if c.material_name %}
    <div class="big{{ ' red' if c.material_low }}">{{ c.material_stock }}</div>
    <div class="sub">{% if c.material_stock == '–' %}{{ c.material_used }} {{ c.material_unit }} used today{% else %}{{ c.material_unit }} in stock &middot; &minus;{{ c.material_used }} today{% endif %}</div>
    {% else %}
    <div class="big">&ndash;</div>
    <div class="sub">no material today</div>
    {% endif %}
  </div>
  <div class="tile">
    <div class="label">Progress</div>
    {% if c.progress %}{% for line in c.progress %}<div class="text line">{{ line }}</div>{% endfor %}
    {% else %}<div class="text line sub">nothing logged yet</div>{% endif %}
  </div>
  <div class="tile">
    <div class="label">Issues</div>
    <div class="big{{ ' red' if c.issue_count }}">{{ c.issue_count }}</div>
    <div class="sub">{{ c.first_issue if c.first_issue else 'none open' }}</div>
  </div>
</div>
"""

_STYLE = """
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 26px 28px; }
.tile { min-width: 0; border-top: 1px solid #E5E7EB; padding-top: 14px; }
.tile .big { margin: 8px 0 8px; }
.tile .line { margin-top: 8px; font-size: 16px; }
"""


@dataclass(frozen=True, slots=True)
class TodayCard:
    site: str
    date_label: str
    workers_total: int
    trades: tuple[tuple[str, int], ...]
    material_name: str | None
    material_stock: str
    material_used: str
    material_unit: str
    material_low: bool
    progress: tuple[str, ...]
    issue_count: int
    first_issue: str | None
    footer: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TodayCard:
        fields = dict(data)
        fields["trades"] = tuple((str(n), int(c)) for n, c in fields.get("trades") or ())
        fields["progress"] = tuple(fields.get("progress") or ())
        return cls(**fields)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value:,.0f}" if abs(value - round(value)) < 0.005 else f"{value:,.1f}"


def _title(text: object) -> str:
    return " ".join(str(text or "").replace("_", " ").split()).capitalize()


def build_today_card(
    day_payload: dict[str, Any],
    *,
    site_name: str,
    report_date: datetime.date,
    footer: str,
) -> TodayCard:
    """The card for one site day, from its report payload."""
    labour = day_payload.get("labour") or {}
    trades = sorted(
        ((_title(t.get("trade")), int(t.get("headcount") or 0)) for t in labour.get("trades") or []),
        key=lambda t: -t[1],
    )
    shown = [t for t in trades if t[0] and t[1] > 0][:3]
    rest = sum(n for _, n in trades[3:])
    if rest:
        shown.append(("other", rest))

    # The material that moved most today (stock left, and what was used).
    materials = [m for m in day_payload.get("materials") or [] if m.get("material_name")]
    top = max(materials, key=lambda m: _number(m.get("used")) or 0.0, default=None)
    stock = _number(top.get("closing")) if top else None

    progress: list[str] = []
    for activity in day_payload.get("activities") or []:
        what = activity.get("work_type") or activity.get("narrative")
        if what and len(progress) < 2:
            progress.append(clip(_title(what) if activity.get("work_type") else what, 46))
    if not progress and day_payload.get("activity_count"):
        progress.append(f"{day_payload['activity_count']} items logged")

    issue = next(
        (i for i in day_payload.get("issues") or [] if i.get("status") == "OPEN"), None
    )
    first_issue = clip(issue.get("narrative") or _title(issue.get("issue_type")), 46) if issue else None

    return TodayCard(
        site=site_name,
        date_label=f"{report_date.day} {report_date:%b}",
        workers_total=int(labour.get("headcount") or 0),
        trades=tuple(shown),
        material_name=clip(top["material_name"], 22).title() if top else None,
        material_stock=_fmt(stock),
        material_used=_fmt(_number(top.get("used"))) if top else "0",
        material_unit=str(top.get("unit") or "") if top else "",
        material_low=stock is not None and stock <= 0,
        progress=tuple(progress),
        issue_count=int(day_payload.get("open_issue_count") or 0),
        first_issue=first_issue,
        footer=footer,
    )


def today_html(card: TodayCard) -> str:
    return render_html(
        _BODY,
        tag="Today",
        where=f"{clip(card.site, 28)} · {card.date_label}",
        footer=card.footer,
        style=_STYLE,
        c=card,
    )
