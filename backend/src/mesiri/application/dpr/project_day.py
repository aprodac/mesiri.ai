"""The project's day of a moment: the one date rule for every site-day reader.

A site's day is the company's calendar day, in the company's time zone. Before
this rule, the DPR family put a timestamped fact on a day with a bare
``occurred_at::date``, the UTC date: anything recorded between 00:00 and 05:30
IST sat on the day before, while the activities next to it (``activity_date``,
written in the project's zone) sat on the right one (ADR draft-per-message §19.4).

Every reader that places a ``timestamptz`` on a site's day uses ``local_date_sql``:
the DPR assembly, its late entries, the review log, the auto-DPR scan, the
assistant's Day Facts. Columns that already hold the project's date
(``activity_date``, ``occurred_date``) are used as they are.

The zone is the company's (``organizations.timezone``); India when it is unset
or the untouched "UTC" a new company starts with, the same rule as the
assistant's ``channel.receipt.data.company_zone``.
"""

from __future__ import annotations

DEFAULT_ZONE = "Asia/Kolkata"


def zone_sql(organization_sql: str) -> str:
    """SQL for the company's zone. ``organization_sql`` is SQL from code (a
    column or a bound parameter), never input."""
    return (
        "COALESCE(NULLIF((SELECT o_z.timezone FROM organizations o_z "
        f"WHERE o_z.id = {organization_sql}), 'UTC'), '{DEFAULT_ZONE}')"
    )


def local_date_sql(moment_sql: str, organization_sql: str) -> str:
    """SQL for the project's calendar date of a ``timestamptz``. Both arguments
    are SQL from code, never input. With a bound parameter for the company
    (``:org_id``) Postgres reads the zone once per statement."""
    return f"CAST(({moment_sql} AT TIME ZONE {zone_sql(organization_sql)}) AS date)"
