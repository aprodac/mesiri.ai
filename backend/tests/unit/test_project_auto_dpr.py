"""due_projects_for_auto_dpr -- unit test of the is_due filtering (fake conn,
no real Postgres). Mirrors this codebase's existing convention for the
automations scheduler (automation_actions.py/automation_audience.py have no
unit tests either -- their DB-touching logic is covered by CI's
live-Postgres integration lane, not here); this only locks down that the
SQL-row -> is_due() wiring picks the right projects."""

from __future__ import annotations

import datetime
import uuid

from mesiri.application.projects.auto_dpr import due_projects_for_auto_dpr

ORG = uuid.uuid4()
# 2026-07-30 12:30 UTC == 18:00 IST (UTC+5:30) -- exactly the default
# reporting_cutoff_time ("18:00") in the default reporting_timezone.
NOW_UTC = datetime.datetime(2026, 7, 30, 12, 30, tzinfo=datetime.UTC)


def _project_row(
    *, cutoff="18:00", tz="Asia/Kolkata", last_run_on=None
) -> dict:
    return {
        "id": uuid.uuid4(),
        "organization_id": ORG,
        "reporting_cutoff_time": cutoff,
        "reporting_timezone": tz,
        "auto_dpr_last_run_on": last_run_on,
    }


class _FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def execute(self, *args, **kwargs):
        return _FakeResult(self._rows)


async def test_a_project_past_its_own_cutoff_and_not_yet_run_today_is_due():
    due_row = _project_row()
    conn = _FakeConn([due_row])

    due = await due_projects_for_auto_dpr(conn, now_utc=NOW_UTC)

    assert [row["id"] for row in due] == [due_row["id"]]


async def test_a_project_already_run_today_in_its_own_timezone_is_not_due_again():
    already_ran = _project_row(last_run_on=datetime.date(2026, 7, 30))
    conn = _FakeConn([already_ran])

    due = await due_projects_for_auto_dpr(conn, now_utc=NOW_UTC)

    assert due == []


async def test_a_project_before_its_own_cutoff_is_not_due_yet():
    not_yet = _project_row(cutoff="23:00")
    conn = _FakeConn([not_yet])

    due = await due_projects_for_auto_dpr(conn, now_utc=NOW_UTC)

    assert due == []


async def test_multiple_projects_are_filtered_independently():
    due_row = _project_row()
    not_due_row = _project_row(cutoff="23:00")
    conn = _FakeConn([due_row, not_due_row])

    due = await due_projects_for_auto_dpr(conn, now_utc=NOW_UTC)

    assert [row["id"] for row in due] == [due_row["id"]]


def test_company_status_is_compared_case_insensitively():
    """BE-07: companies were stored "Active" and this query compared
    `o.status = 'active'`, which Postgres matches case-sensitively, so the
    automatic DPR found no company at all. Rows from before migration 0463
    (or an older build after a rollback) may still say "Active"."""
    import inspect

    from mesiri.application.projects import auto_dpr

    sql = inspect.getsource(auto_dpr.due_projects_for_auto_dpr)
    # Since SS-02 the rule lives in one place (lifecycle.operational_sql),
    # which compares lower(status) and also admits running trials.
    assert 'operational_sql("o")' in sql
    assert "AND o.status = 'active'" not in sql
