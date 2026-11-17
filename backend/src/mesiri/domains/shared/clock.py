"""The one "today" (SS-74a, docs/plans/guided-demo-plan.md section 18.5).

Every real company lives on the real date. A learning sample company (a sandbox, SS-66) lives on its own date: the
day its planned simulation is at (``organizations.sandbox_today``), which moves only when the person presses Next day
or goes back. So a pay week, a month, days late, stock left in days and a bill's age are all true inside the game.

How it reaches the code: the sample company's token carries its date (``today``, next to the ``sandbox`` claim);
``get_current_user`` puts it here for the rest of the request (``bind_from_token``); ``today()`` gives it, and
``company_today`` (application/dpr/project_day.py) asks here first. With nothing bound, ``today()`` is exactly what
the code used before (``date.today()``), so nothing changes for a real company and nothing is read from the database
for it. When the sample's date moves, the routes that move it give back a new token.

Kept free of other imports: everything may use it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_today: ContextVar[dt.date | None] = ContextVar("mesiri_today", default=None)


def today() -> dt.date:
    """Today for this request: the sample company's date inside one, else the real date."""
    return _today.get() or dt.date.today()


def override() -> dt.date | None:
    """The sample company's date when this request is in one; None for a real company."""
    return _today.get()


def now(zone: Any = None) -> dt.datetime:
    """This moment: the real time of day, on the sample company's date inside one. ``zone`` as for
    ``datetime.now``."""
    return at(dt.datetime.now(zone))


def at(moment: dt.datetime) -> dt.datetime:
    """``moment`` (a "now" the caller read its own way) on the sample company's date inside one, else unchanged. For
    code whose tests fake its own clock: ``clock.at(dt.datetime.now(zone))`` keeps the fake and the game's date."""
    day = _today.get()
    return moment.replace(year=day.year, month=day.month, day=day.day) if day else moment


def bind(day: dt.date | None) -> None:
    """Set the date for the rest of this request or message (None: the real date)."""
    _today.set(day)


def bind_from_token(payload: Mapping[str, Any]) -> None:
    """A sample company's token names its date; any other token leaves the real date. Called by every
    ``get_current_user`` (the dashboard's and the assistant's), so it is also how a stale binding is cleared."""
    day = None
    if payload.get("sandbox") and payload.get("today"):
        try:
            day = dt.date.fromisoformat(str(payload["today"]))
        except ValueError:
            day = None
    _today.set(day)


@contextmanager
def scope(day: dt.date | None) -> Iterator[None]:
    """The date for the block, restored afterwards."""
    token = _today.set(day)
    try:
        yield
    finally:
        _today.reset(token)
