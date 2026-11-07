"""The test company's "today", the way the API decides it.

The API puts "today" on the company's calendar (``project_day.company_today``: the company's zone, India when
it is unset or the "UTC" a new company starts with). The machine's ``datetime.date.today()`` is the UTC date,
which is a day behind India from 18:30 to 24:00 UTC, so an order or request "for today" read as late in the
evening. The contract tests' companies keep the default zone, so their today is India's.
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

from mesiri.application.dpr.project_day import DEFAULT_ZONE


def company_today() -> datetime.date:
    """Today for a test company with the default zone (same answer as ``project_day.company_today``)."""
    return datetime.datetime.now(ZoneInfo(DEFAULT_ZONE)).date()
