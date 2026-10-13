"""BE-16: when the project DPR is sent, and what is sent (fake connection,
no Postgres)."""

from __future__ import annotations

import datetime
import uuid

import pytest
from fastapi import HTTPException

from mesiri.application.projects import auto_dpr
from mesiri.application.projects.auto_dpr import (
    finalize_project_dpr,
    mark_project_dpr_sent,
    request_project_dpr_send,
    send_reason,
)

EVENING = datetime.datetime(2026, 10, 13, 19, 0)
LATE = datetime.datetime(2026, 10, 13, 21, 5)


# ---------------------------------------------------------------------------
# send_reason (pure)
# ---------------------------------------------------------------------------


def _reason(statuses, *, now=EVENING, deadline="21:00", requested=False, auto=True):
    return send_reason(
        site_statuses=statuses,
        local_now=now,
        send_deadline=deadline,
        requested=requested,
        auto_enabled=auto,
    )


def test_every_site_confirmed_sends_straight_away():
    assert _reason(["APPROVED", "PUBLISHED"]) == "all_confirmed"


def test_one_site_still_open_waits_for_the_deadline():
    assert _reason(["APPROVED", "READY"]) is None
    assert _reason(["APPROVED", "READY"], now=LATE) == "deadline"


def test_a_site_with_no_day_at_all_counts_as_not_confirmed():
    assert _reason(["APPROVED", None]) is None


def test_send_now_wins_even_with_the_automatic_dpr_off():
    assert _reason(["READY"], requested=True, auto=False) == "requested"


def test_nothing_is_sent_automatically_when_the_automatic_dpr_is_off():
    assert _reason(["APPROVED"], now=LATE, auto=False) is None


def test_a_project_with_no_active_site_has_nothing_to_send():
    assert _reason([], requested=True) is None


def test_a_bad_deadline_falls_back_to_nine_pm():
    assert _reason(["READY"], deadline="soon", now=LATE) == "deadline"
    assert _reason(["READY"], deadline="soon") is None


def test_a_custom_deadline_is_honoured():
    assert _reason(["READY"], deadline="18:30") == "deadline"


# ---------------------------------------------------------------------------
# Fake connection
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.rowcount = 1

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _Conn:
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        for fragment, result in self.answers.items():
            if fragment in sql:
                return result
        return _Result()


class _FakeRepo:
    """Stands in for PostgresDprRepository inside auto_dpr."""

    site_day: dict | None = None
    created: list = []
    sources: list = []

    def __init__(self, conn):
        self.conn = conn

    async def find_site_report(self, **_):
        return type(self).site_day

    async def get_or_create_project_daily_report(self, **_):
        return PROJECT_REPORT_ID

    async def assemble_project_report_payload(self, **_):
        return {"level": "PROJECT"}, [(uuid.uuid4(), None)]

    async def create_version(self, *, daily_report_id, payload):
        type(self).created.append(daily_report_id)
        return {"id": VERSION_ID}

    async def record_project_sources(self, *, project_version_id, sources):
        type(self).sources.append(project_version_id)


PROJECT_REPORT_ID = uuid.uuid4()
VERSION_ID = uuid.uuid4()


@pytest.fixture
def fake_repo(monkeypatch):
    _FakeRepo.site_day = None
    _FakeRepo.created = []
    _FakeRepo.sources = []
    monkeypatch.setattr(auto_dpr, "PostgresDprRepository", _FakeRepo)
    return _FakeRepo


async def _finalize(conn):
    return await finalize_project_dpr(
        conn,
        organization_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        report_date=datetime.date(2026, 10, 13),
    )


# ---------------------------------------------------------------------------
# finalize_project_dpr
# ---------------------------------------------------------------------------


async def test_a_single_site_project_sends_its_confirmed_site_dpr(fake_repo):
    site_id = uuid.uuid4()
    fake_repo.site_day = {"id": uuid.uuid4(), "status": "APPROVED"}
    conn = _Conn({"FROM sites": _Result([{"id": site_id}])})

    target = await _finalize(conn)

    assert target == {"daily_report_id": fake_repo.site_day["id"], "site_id": site_id, "level": "SITE"}
    assert fake_repo.created == []  # no second, near-identical report


async def test_an_unconfirmed_single_site_goes_out_as_a_roll_up_marked_not_reported(fake_repo):
    fake_repo.site_day = {"id": uuid.uuid4(), "status": "READY"}
    conn = _Conn(
        {
            "FROM sites": _Result([{"id": uuid.uuid4()}]),
            "SELECT status::text AS status FROM daily_reports": _Result([{"status": "DRAFT"}]),
        }
    )

    target = await _finalize(conn)

    assert target["level"] == "PROJECT"
    assert fake_repo.created == [PROJECT_REPORT_ID]


async def test_a_multi_site_roll_up_is_built_recorded_and_approved_by_composition(fake_repo):
    conn = _Conn(
        {
            "FROM sites": _Result([{"id": uuid.uuid4()}, {"id": uuid.uuid4()}]),
            "SELECT status::text AS status FROM daily_reports": _Result([{"status": "DRAFT"}]),
        }
    )

    target = await _finalize(conn)

    assert target == {"daily_report_id": PROJECT_REPORT_ID, "site_id": None, "level": "PROJECT"}
    assert fake_repo.created == [PROJECT_REPORT_ID]
    assert fake_repo.sources == [VERSION_ID]
    assert any("SET status = 'APPROVED'" in sql for sql, _ in conn.calls)
    assert any("approved_at = now()" in sql for sql, _ in conn.calls)


async def test_an_already_approved_roll_up_is_reused_not_rebuilt(fake_repo):
    conn = _Conn(
        {
            "FROM sites": _Result([{"id": uuid.uuid4()}, {"id": uuid.uuid4()}]),
            "SELECT status::text AS status FROM daily_reports": _Result([{"status": "APPROVED"}]),
        }
    )

    target = await _finalize(conn)

    assert target["daily_report_id"] == PROJECT_REPORT_ID
    assert fake_repo.created == []


async def test_a_project_without_active_sites_has_nothing_to_finalize(fake_repo):
    assert await _finalize(_Conn()) is None


# ---------------------------------------------------------------------------
# mark sent / send now
# ---------------------------------------------------------------------------


async def test_marking_sent_publishes_the_report_and_its_confirmed_sites_once():
    conn = _Conn()
    project_id = uuid.uuid4()

    await mark_project_dpr_sent(
        conn, project_id=project_id, report_date=datetime.date(2026, 10, 13), daily_report_id=uuid.uuid4()
    )

    report, sites, project = conn.calls
    assert "status = 'PUBLISHED'" in report[0] and "status = 'APPROVED'" in report[0]
    assert "level = 'SITE'" in sites[0]
    assert "dpr_last_sent_on" in project[0] and "dpr_send_requested_on = NULL" in project[0]


async def test_send_now_records_the_projects_local_date():
    conn = _Conn(
        {"FROM projects": _Result([{"reporting_timezone": "Asia/Kolkata", "dpr_last_sent_on": None}])}
    )
    # 20:00 UTC on 13 Oct is 01:30 on 14 Oct in India.
    now_utc = datetime.datetime(2026, 10, 13, 20, 0, tzinfo=datetime.UTC)

    report_date = await request_project_dpr_send(
        conn, organization_id=uuid.uuid4(), project_id=uuid.uuid4(), now_utc=now_utc
    )

    assert report_date == datetime.date(2026, 10, 14)
    assert conn.calls[-1][1]["d"] == datetime.date(2026, 10, 14)


async def test_send_now_is_refused_once_todays_dpr_went_out():
    today = datetime.date(2026, 10, 13)
    conn = _Conn({"FROM projects": _Result([{"reporting_timezone": "UTC", "dpr_last_sent_on": today}])})

    with pytest.raises(ValueError):
        await request_project_dpr_send(
            conn,
            organization_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            now_utc=datetime.datetime(2026, 10, 13, 12, 0, tzinfo=datetime.UTC),
        )


async def test_send_now_for_an_unknown_project_returns_none():
    assert (
        await request_project_dpr_send(
            _Conn(),
            organization_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            now_utc=datetime.datetime(2026, 10, 13, 12, 0, tzinfo=datetime.UTC),
        )
        is None
    )


# ---------------------------------------------------------------------------
# Project setting
# ---------------------------------------------------------------------------


def test_send_deadline_is_normalised_and_checked():
    from mesiri.domains.projects.router import _valid_send_deadline

    assert _valid_send_deadline("9:05") == "09:05"
    assert _valid_send_deadline("21:00") == "21:00"
    with pytest.raises(HTTPException):
        _valid_send_deadline("nine pm")
    with pytest.raises(HTTPException):
        _valid_send_deadline("25:00")
