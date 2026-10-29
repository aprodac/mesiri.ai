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


def period_for(bucket: str | None, today: dt.date) -> tuple[dt.date, dt.date, str] | None:
    """(first day, last day, label) of a named period on the project's calendar,
    from the project's ``today``; None for a bucket that names none. The ONE
    place that says what "yesterday" or "last week" is (request 127, P2)."""
    key = str(bucket or "").strip().lower()
    monday = today - dt.timedelta(days=today.weekday())
    if key == "today":
        return today, today, "today"
    if key == "yesterday":
        yesterday = today - dt.timedelta(days=1)
        return yesterday, yesterday, day_label(yesterday, today)
    if key == "this_week":
        return monday, today, "this week"
    if key == "last_week":
        start = monday - dt.timedelta(days=7)
        return start, start + dt.timedelta(days=6), "last week"
    if key == "this_month":
        return today.replace(day=1), today, "this month"
    return None


def resolve_period(
    date_range: str | None,
    day: object,
    name: str | None,
    now: dt.datetime | None = None,
    *,
    today: dt.date | None = None,
) -> tuple[dt.date, dt.date, str] | None:
    """WRK-03 / MAT-03: the dates a work-log, labour or material question is
    about, in the project's own zone: (first day, last day, label). ``day`` is
    the tool's ``date`` ("yesterday", "day before yesterday", an ISO date) and
    wins over ``date_range``. None when the question names no period (the
    caller answers as before: all-time stock, or today for the work log).
    ``today`` is for a caller that already holds the sender's day."""
    from canonicalization.occurred_date import parse_stated_date

    today = today or project_today(name, now)
    if day not in (None, ""):
        stated = parse_stated_date(day, today=today)
        if stated is not None:
            return stated, stated, day_label(stated, today)
    return period_for(date_range, today)


def mark_carried_over(work: dict, last_day: dt.date) -> None:
    """Request 132: an issue still open from before the period's last day says since
    when ("since 24 Oct"), so a summary never calls the rain of 24 Oct "today's".
    Marks each open issue with ``since`` (and ``carried_over``) in place."""
    for issue in (work.get("open_issues") if isinstance(work, dict) else None) or []:
        if not isinstance(issue, dict):
            continue
        try:
            opened = dt.date.fromisoformat(str(issue.get("occurred_at"))[:10])
        except ValueError:
            continue
        issue["carried_over"] = opened < last_day
        if opened < last_day:
            issue["since"] = f"{opened.day} {opened:%b}"


async def read_period(
    *,
    organization_id: str,
    project_id: str | None,
    site_id: str | None,
    period: tuple[dt.date, dt.date, str],
    activity_search: object | None = None,
    labour_query: object | None = None,
    work_type: str | None = None,
    trade: str | None = None,
    include_unsaved: bool = False,
) -> dict:
    """The day's (or period's) figures for one site scope, read the one way:
    the work log with its open issues, and the labour headcount, both for the
    same dates and scope. Used by "how many workers today?", "what was done
    today?", "yesterday ...", the "today so far" line. A part whose service is
    missing is left out (None). Read-only."""
    start, end, label = period
    scope = {"organization_id": organization_id, "project_id": project_id, "site_id": site_id}
    work = None
    if activity_search is not None:
        extra = {"include_unsaved": True} if include_unsaved else {}
        work = await activity_search.search(  # type: ignore[attr-defined]
            **scope, start_date=start, end_date=end, work_type=work_type, **extra
        )
        work["date_range_label"] = label
        mark_carried_over(work, end)
    labour = None
    if labour_query is not None:
        labour = await labour_query.summarize_attendance(  # type: ignore[attr-defined]
            **scope, start_date=start, end_date=end, trade=trade
        )
        labour["date_range_label"] = label
    return {"label": label, "work": work, "labour": labour}
