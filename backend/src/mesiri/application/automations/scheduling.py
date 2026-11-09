"""Pure "is this automation due right now?" decision -- no I/O, no DB.

Mirrors application/notifications/checks.py's reasoning exactly: the
at-most-once guarantee itself lives in the database (notifications'
UNIQUE constraint), so this only needs to answer the timing question
correctly -- getting it wrong either fires an automation twice in one day
(if `last_run_on` were ignored) or never fires it at all (if the weekday/
time comparison is wrong), and both are the kind of bug nobody notices
until a user complains their 5pm DPR never arrived.

`automations.timezone` is the row's OWN timezone (set at creation, from
the creating user's resolved context or the project's `reporting_timezone`
default) -- everything here is evaluated in that zone, never server/UTC
time, since "5pm" means 5pm where the person who asked lives.
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

# 0=Monday .. 6=Sunday, matching Python's date.weekday().
_WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def parse_time_of_day(value: str) -> datetime.time:
    """"HH:MM" -> a time object. Raises ValueError on anything else -- the
    caller (validation.py) is what turns that into a rejection reason; this
    stays a pure parser."""
    hour_str, minute_str = value.split(":", 1)
    return datetime.time(hour=int(hour_str), minute=int(minute_str))


def local_now(*, timezone_name: str, now_utc: datetime.datetime) -> datetime.datetime:
    """`now_utc` (aware) converted into the automation's own timezone.
    Falls back to UTC for a malformed/unknown zone name rather than
    raising -- a bad timezone string should degrade to "never quite fires
    at the right hour" not "the whole runner tick crashes"."""
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    return now_utc.astimezone(tz)


def is_due(
    *,
    frequency: str,
    day_of_week: int | None,
    time_of_day: str,
    timezone_name: str,
    last_run_on: datetime.date | None,
    now_utc: datetime.datetime,
) -> bool:
    """True once per local day, at or after `time_of_day`, matching
    `frequency` -- never twice for the same local date (that's what
    `last_run_on` guards), regardless of how often the runner ticks."""
    local = local_now(timezone_name=timezone_name, now_utc=now_utc)
    today = local.date()

    if last_run_on == today:
        return False

    try:
        cutoff = parse_time_of_day(time_of_day)
    except (ValueError, IndexError):
        return False
    if local.time() < cutoff:
        return False

    if frequency == "WEEKDAYS":
        return local.weekday() < 5  # Monday-Friday
    if frequency == "WEEKLY":
        return day_of_week is not None and local.weekday() == day_of_week
    if frequency == "MONTHLY":
        # PRC-20: the monthly report goes on the 1st (D-R2: a calendar month, the one just finished).
        return local.day == 1
    # DAILY, and any unrecognized value -- fail toward "fires every day"
    # rather than "silently never fires", since a typo'd frequency string
    # is far more likely than someone wanting genuinely undefined behaviour.
    return True
