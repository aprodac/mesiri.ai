"""The dates a period report covers (PRC-19, D-R2). Pure: no I/O.

A week is Monday to Sunday; a month is a calendar month; custom is any range of at most ``MAX_DAYS`` days. All dates
are the company's own (the caller passes the company's today). The previous period has the same length and ends the
day before; trend windows step back by whole periods.
"""

from __future__ import annotations

import calendar
import datetime
from dataclasses import dataclass
from typing import Literal

Kind = Literal["week", "month", "custom"]
KINDS: tuple[str, ...] = ("week", "month", "custom")
MAX_DAYS = 92
DAY = datetime.timedelta(days=1)


@dataclass(frozen=True)
class Period:
    kind: str
    start: datetime.date
    end: datetime.date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def dates(self) -> list[datetime.date]:
        return [self.start + DAY * i for i in range(self.days)]

    @property
    def label(self) -> str:
        """'Week 45', 'October 2026', or '3 – 20 Nov 2026'."""
        if self.kind == "week":
            return f"Week {self.start.isocalendar()[1]}"
        if self.kind == "month":
            return f"{self.start:%B %Y}"
        return range_text(self.start, self.end)

    @property
    def range_text(self) -> str:
        return range_text(self.start, self.end)

    def as_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "from": self.start.isoformat(), "to": self.end.isoformat(), "days": self.days,
                "label": self.label, "range": self.range_text}


def range_text(start: datetime.date, end: datetime.date) -> str:
    """'3 – 9 Nov 2026', '28 Oct – 3 Nov 2026', '29 Dec 2025 – 4 Jan 2026'."""
    if start.year != end.year:
        return f"{start.day} {start:%b %Y} – {end.day} {end:%b %Y}"
    if start.month != end.month:
        return f"{start.day} {start:%b} – {end.day} {end:%b %Y}"
    if start == end:
        return f"{start.day} {start:%b %Y}"
    return f"{start.day} – {end.day} {end:%b %Y}"


def week_of(day: datetime.date) -> Period:
    start = day - DAY * day.weekday()
    return Period("week", start, start + DAY * 6)


def month_of(day: datetime.date) -> Period:
    last = calendar.monthrange(day.year, day.month)[1]
    return Period("month", day.replace(day=1), day.replace(day=last))


def resolve(kind: str, today: datetime.date, *, anchor: datetime.date | None = None,
            date_from: datetime.date | None = None, date_to: datetime.date | None = None) -> Period:
    """The period asked for. With no anchor: the last *finished* week or month (the one a Monday report is about),
    unless today is past the period's end anyway. ``custom`` needs both dates.

    Raises ValueError with words a person can read."""
    if kind == "custom":
        if date_from is None or date_to is None:
            raise ValueError("Give both dates for a custom period.")
        if date_to < date_from:
            raise ValueError("The end date is before the start date.")
        if (date_to - date_from).days + 1 > MAX_DAYS:
            raise ValueError(f"A report covers at most {MAX_DAYS} days; choose a shorter range.")
        return Period("custom", date_from, date_to)
    if kind == "week":
        return week_of(anchor) if anchor else week_of(today - DAY * 7)
    if kind == "month":
        return month_of(anchor) if anchor else month_of(today.replace(day=1) - DAY)
    raise ValueError("The period is a week, a month or custom dates.")


def previous(period: Period) -> Period:
    """The period just before, of the same kind (a month steps a calendar month; custom the same number of days)."""
    if period.kind == "week":
        return week_of(period.start - DAY * 7)
    if period.kind == "month":
        return month_of(period.start - DAY)
    return Period("custom", period.start - DAY * period.days, period.start - DAY)


def following(period: Period) -> Period:
    if period.kind == "week":
        return week_of(period.start + DAY * 7)
    if period.kind == "month":
        return month_of(period.end + DAY)
    return Period("custom", period.end + DAY, period.end + DAY * period.days)


def trend(period: Period, count: int = 8) -> list[Period]:
    """``count`` periods ending with this one, oldest first."""
    out = [period]
    while len(out) < count:
        out.append(previous(out[-1]))
    return list(reversed(out))


def clip_to_today(period: Period, today: datetime.date) -> datetime.date:
    """The last day with data: the period's end, or today when the period is still running."""
    return min(period.end, today)
