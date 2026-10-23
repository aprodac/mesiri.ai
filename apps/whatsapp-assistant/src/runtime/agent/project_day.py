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
