"""Work out which day a report is about.

Every operational module needs this and none of them had it. Material,
Expense and Labour each stamped ``date.today()`` at the moment of saving and
recorded ``occurred_date_source="inferred_at_confirmation"`` to admit the
guess — but nothing ever showed the guess to the user, and nothing ever used
a date the user actually stated.

**Why this lives in canonicalization rather than in each module's mapper.**
The mapper runs at confirmation time and holds only the command being built:
it knows neither what the message said nor where the sender is. Those are
exactly the two things needed to date a report correctly, and both are in
hand here — the extracted fields, and the resolved context's timezone. The
old placement is the direct cause of both bugs below; moving the decision to
where the information already exists fixes them at the root rather than
patching each module.

Two failures this closes:

1. **A stated date was ignored.** "yesterday 12 masons worked" was recorded
   as today. Attendance is append-only, so that cannot be edited afterwards —
   only superseded — which makes getting it right at capture the only cheap
   moment. (The extraction prompt has asked for ``occurred_on`` on expenses
   for some time; nothing ever read it.)

2. **"Today" meant the server's today.** ``date.today()`` uses the host
   clock, which runs UTC. For a site in India (UTC+5:30) every report between
   midnight and 05:30 local was filed under the previous day. Early starts
   are normal on a construction site, so this is a real window, not a
   theoretical one.

Deliberately **not** a question. Principle P9: a prompt on every single
report costs far more than a visible assumption the user can see and correct
at confirmation. This module's job is to make the date honest and legible,
never to interrogate.

Built module-agnostic on purpose. Labour uses it today; Material and Expense
can adopt it by calling `resolve_occurred_date` and reading the two fields it
sets, with no change to their own logic.
"""

from __future__ import annotations

import datetime
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mesiri.domains.shared import clock

#: Recorded on the command so a reader can tell a real answer from a fallback.
SOURCE_STATED = "stated_by_user"
SOURCE_INFERRED = "inferred_at_confirmation"

#: Field the AI puts a stated date in, and the two fields this module sets.
EXTRACTED_DATE_FIELD = "occurred_on"
OCCURRED_DATE_FIELD = "occurred_date"
OCCURRED_DATE_SOURCE_FIELD = "occurred_date_source"

#: Relative words worth understanding, as offsets in days. Kept small and
#: literal: "last Friday" and "the 3rd" are ambiguous enough that guessing
#: wrong is worse than falling back to today, which at least announces
#: itself as an assumption at confirmation.
_RELATIVE_DAYS: dict[str, int] = {
    "today": 0,
    "tonight": 0,
    "yesterday": -1,
    "y'day": -1,
    "yday": -1,
    "day before yesterday": -2,
    "tomorrow": 1,
}

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def today_for(timezone_name: str | None) -> datetime.date:
    """Today where the *sender* is, falling back to the host's today.

    An unknown or missing timezone falls back rather than raising: not
    knowing where someone is must never stop them recording work. On a host
    without the tz database installed (Windows without `tzdata`), ZoneInfo
    raises ZoneInfoNotFoundError — also treated as "just use the host clock".
    """
    if clock.override() is not None:  # SS-74a: a learning sample company lives on its own date
        return clock.override()
    if timezone_name:
        try:
            return datetime.datetime.now(ZoneInfo(timezone_name)).date()
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            pass
    return clock.today()


def parse_stated_date(value: object, *, today: datetime.date) -> datetime.date | None:
    """Turn what the AI read into a real date, or None if it isn't one.

    Accepts an ISO date (``2026-07-25``) or a small set of relative words.
    Anything else — a bare "Friday", "last week", a malformed string — returns
    None so the caller falls back to today and says so. Half-understanding a
    date is worse than admitting the assumption.

    Future dates are rejected. A report is a record of work already done, so
    a date after today is a misread ("tomorrow", or a year typo), and filing
    work in the future would quietly break every "today"/"this week" total.
    """
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value if value <= today else None
    if isinstance(value, datetime.datetime):
        return value.date() if value.date() <= today else None

    text = str(value or "").strip().lower()
    if not text:
        return None

    relative = _RELATIVE_DAYS.get(text)
    if relative is not None:
        stated = today + datetime.timedelta(days=relative)
        return stated if stated <= today else None

    match = _ISO_DATE.match(text)
    if match:
        try:
            stated = datetime.date(int(match[1]), int(match[2]), int(match[3]))
        except ValueError:
            return None
        return stated if stated <= today else None

    return None


def resolve_occurred_date(fields: dict, *, timezone_name: str | None) -> dict:
    """Set ``occurred_date`` and ``occurred_date_source`` on a copy of fields.

    Consumes the AI's ``occurred_on`` (removing it, so the raw extracted
    value never also renders as its own line in the confirmation next to the
    date it produced — the same alias-popping discipline
    ``_normalize_material_fields`` follows).

    Always sets both fields, so downstream code never has to decide what a
    missing date means. `occurred_date_source` is what lets the confirmation
    say "(assumed today)" honestly instead of presenting a guess as fact.
    """
    out = dict(fields)
    stated_raw = out.pop(EXTRACTED_DATE_FIELD, None)

    today = today_for(timezone_name)
    stated = parse_stated_date(stated_raw, today=today)

    out[OCCURRED_DATE_FIELD] = (stated or today).isoformat()
    out[OCCURRED_DATE_SOURCE_FIELD] = SOURCE_STATED if stated else SOURCE_INFERRED
    return out
