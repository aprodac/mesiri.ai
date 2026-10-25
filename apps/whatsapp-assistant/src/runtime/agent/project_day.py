"""The project's day (request 90): ONE place that says what "today",
"yesterday" and "this week" are for the agent's lookups.

The day is the project's own, in the company's time zone (organizations.
timezone, India by default -- a blank or default "UTC" counts as India, as in
``channel.receipt.data.company_zone``). It is never the server's UTC day: at
02:03 IST on 23 Oct the server is still on 22 Oct, and "innu ethra per
vannu?" counted the 2 painters of the day before.

Read-only: nothing here writes. Every agent tool that reads a day (labour
count, work log, the day's summary, a past day's report, the "today so far"
line, the work-site expiry) gets its date from here.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from channel.receipt.data import company_zone


def project_zone(name: str | None) -> ZoneInfo:
    """The project's time zone; India when unset, "UTC" (the untouched
    default) or unknown."""
    zone = company_zone(name)
    return zone if isinstance(zone, ZoneInfo) else ZoneInfo("Asia/Kolkata")


def project_zone_name(name: str | None) -> str:
    """The zone's IANA name, for the lookups that take a name."""
    return str(project_zone(name))


def project_now(name: str | None, now: dt.datetime | None = None) -> dt.datetime:
    """The current moment on the project's clock (``now`` is for tests)."""
    zone = project_zone(name)
    moment = now or dt.datetime.now(dt.UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(zone)


def project_today(name: str | None, now: dt.datetime | None = None) -> dt.date:
    return project_now(name, now).date()


def project_yesterday(name: str | None, now: dt.datetime | None = None) -> dt.date:
    return project_today(name, now) - dt.timedelta(days=1)


def week_start(name: str | None, now: dt.datetime | None = None) -> dt.date:
    """Monday of the project's current week."""
    today = project_today(name, now)
    return today - dt.timedelta(days=today.weekday())


#: The periods a lookup may name (``date_range``) besides a single day.
DAY_RANGES = ("today", "yesterday", "this_week", "last_week", "this_month")


def day_label(day: dt.date, today: dt.date) -> str:
    """"today", "yesterday (24 Oct)" or "24 Oct" -- how an answer names its day."""
    if day == today:
        return "today"
    short = f"{day.day} {day:%b}"
    return f"yesterday ({short})" if day == today - dt.timedelta(days=1) else short


def resolve_period(
    date_range: str | None,
    day: object,
    name: str | None,
    now: dt.datetime | None = None,
) -> tuple[dt.date, dt.date, str] | None:
    """WRK-03 / MAT-03: the dates a work-log or material question is about, in
    the project's own zone: (first day, last day, label). ``day`` is the
    tool's ``date`` ("yesterday", "day before yesterday", an ISO date) and
    wins over ``date_range``. None when the question names no period (the
    caller answers as before: all-time stock, or today for the work log)."""
    from canonicalization.occurred_date import parse_stated_date

    today = project_today(name, now)
    if day not in (None, ""):
        stated = parse_stated_date(day, today=today)
        if stated is not None:
            return stated, stated, day_label(stated, today)
    key = str(date_range or "").strip().lower()
    if key == "today":
        return today, today, "today"
    if key == "yesterday":
        yesterday = today - dt.timedelta(days=1)
        return yesterday, yesterday, day_label(yesterday, today)
    if key == "this_week":
        return week_start(name, now), today, "this week"
    if key == "last_week":
        start = week_start(name, now) - dt.timedelta(days=7)
        return start, start + dt.timedelta(days=6), "last week"
    if key == "this_month":
        return today.replace(day=1), today, "this month"
    return None
