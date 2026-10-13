"""BE-08: the site's working day -- status rules and the readiness check
(pure, application/dpr/site_day.py) and how the DPR repository applies them
(fake connection, no Postgres)."""

from __future__ import annotations

import datetime
import json
import uuid

import pytest

from mesiri.application.dpr import site_day
from mesiri.application.dpr.site_day import (
    APPROVED,
    DRAFT,
    IN_REVIEW,
    NEEDS_DETAILS,
    NOT_REPORTED,
    PUBLISHED,
    READY,
    InvalidSiteDayTransition,
)
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

COMPLETE = {
    "activity_count": 2,
    "labour": {"headcount": 14},
    "evidence_count": 3,
    "materials": [{"material_name": "Cement"}],
}


# ---------------------------------------------------------------------------
# Readiness rule (approved 13 Oct: a work item AND a labour count)
# ---------------------------------------------------------------------------


def test_a_day_with_work_and_labour_is_ready():
    assert site_day.readiness_status(COMPLETE) == READY
    assert site_day.missing_sections(COMPLETE) == {"blocking": [], "optional": []}


def test_a_day_without_labour_needs_details():
    payload = {**COMPLETE, "labour": {"headcount": 0}}
    assert site_day.readiness_status(payload) == NEEDS_DETAILS
    assert site_day.missing_sections(payload)["blocking"] == ["labour"]


def test_a_day_without_work_items_needs_details():
    payload = {**COMPLETE, "activity_count": 0}
    assert site_day.missing_sections(payload)["blocking"] == ["work_done"]


def test_an_empty_day_is_missing_everything():
    assert site_day.missing_sections(None) == {
        "blocking": ["work_done", "labour"],
        "optional": ["photos", "materials"],
    }


def test_missing_photos_and_materials_never_block():
    payload = {"activity_count": 1, "labour": {"headcount": 5}}
    assert site_day.readiness_status(payload) == READY
    assert site_day.missing_sections(payload)["optional"] == ["photos", "materials"]


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (DRAFT, NEEDS_DETAILS),
        (DRAFT, READY),
        (NEEDS_DETAILS, READY),
        (READY, NEEDS_DETAILS),
        (READY, IN_REVIEW),
        (NEEDS_DETAILS, IN_REVIEW),
        (IN_REVIEW, APPROVED),
        (IN_REVIEW, NEEDS_DETAILS),
        (APPROVED, PUBLISHED),
        (NOT_REPORTED, READY),
    ],
)
def test_allowed_moves(current, target):
    site_day.check_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (PUBLISHED, APPROVED),
        (APPROVED, IN_REVIEW),
        (APPROVED, READY),
        (DRAFT, PUBLISHED),
        (READY, PUBLISHED),
        (IN_REVIEW, DRAFT),
        (NEEDS_DETAILS, DRAFT),
    ],
)
def test_refused_moves(current, target):
    with pytest.raises(InvalidSiteDayTransition):
        site_day.check_transition(current, target)


def test_sources_for_match_the_transition_table():
    assert site_day.sources_for(IN_REVIEW) == [DRAFT, NEEDS_DETAILS, READY]
    assert site_day.sources_for(APPROVED) == [DRAFT, IN_REVIEW, NEEDS_DETAILS, READY]
    assert site_day.sources_for(PUBLISHED) == [APPROVED]


# ---------------------------------------------------------------------------
# Status after a regeneration
# ---------------------------------------------------------------------------


def test_before_cutoff_a_day_keeps_collecting():
    assert site_day.status_after_refresh(DRAFT, COMPLETE, evaluate_readiness=False) == DRAFT


def test_at_cutoff_a_day_is_labelled():
    assert site_day.status_after_refresh(DRAFT, COMPLETE, evaluate_readiness=True) == READY
    assert site_day.status_after_refresh(DRAFT, {}, evaluate_readiness=True) == NEEDS_DETAILS


def test_a_late_labour_count_turns_a_needs_details_day_ready_without_another_cutoff():
    assert site_day.status_after_refresh(NEEDS_DETAILS, COMPLETE, evaluate_readiness=False) == READY


def test_a_day_with_the_engineer_stays_with_the_engineer():
    assert site_day.status_after_refresh(IN_REVIEW, {}, evaluate_readiness=True) == IN_REVIEW


@pytest.mark.parametrize("frozen", [APPROVED, PUBLISHED])
def test_a_confirmed_day_cannot_be_refreshed(frozen):
    with pytest.raises(InvalidSiteDayTransition):
        site_day.status_after_refresh(frozen, COMPLETE, evaluate_readiness=True)


# ---------------------------------------------------------------------------
# Repository wiring (fake connection)
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, rows=None, rowcount=1):
        self._rows = rows or []
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _Conn:
    """Answers by matching a fragment of the SQL; records every statement."""

    def __init__(self, answers: dict[str, _Result]):
        self.answers = answers
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        for fragment, result in self.answers.items():
            if fragment in sql:
                return result
        return _Result()

    def updates_to_daily_reports(self):
        return [p for sql, p in self.calls if sql.strip().startswith("UPDATE daily_reports SET")]


def _version_answers(status: str, level: str = "SITE") -> dict[str, _Result]:
    return {
        "level::text AS level": _Result([{"status": status, "level": level}]),
        "COALESCE(MAX(version_no)": _Result([{"next": 2}]),
    }


async def test_create_version_at_cutoff_labels_the_day_and_records_what_is_missing():
    conn = _Conn(_version_answers(DRAFT))
    payload = {**COMPLETE, "labour": {"headcount": 0}}

    await PostgresDprRepository(conn).create_version(
        daily_report_id=uuid.uuid4(), payload=payload, evaluate_readiness=True
    )

    [update] = conn.updates_to_daily_reports()
    assert update["status"] == NEEDS_DETAILS
    assert json.loads(update["missing"])["blocking"] == ["labour"]


async def test_create_version_no_longer_pulls_a_day_back_from_the_engineer():
    conn = _Conn(_version_answers(IN_REVIEW))

    await PostgresDprRepository(conn).create_version(
        daily_report_id=uuid.uuid4(), payload={}, evaluate_readiness=True
    )

    [update] = conn.updates_to_daily_reports()
    assert update["status"] == IN_REVIEW


async def test_create_version_for_a_project_roll_up_is_not_readiness_checked():
    conn = _Conn(_version_answers(DRAFT, level="PROJECT"))

    await PostgresDprRepository(conn).create_version(
        daily_report_id=uuid.uuid4(), payload={}, evaluate_readiness=True
    )

    [update] = conn.updates_to_daily_reports()
    assert update["status"] == DRAFT
    assert update["missing"] is None


async def test_create_version_still_refuses_a_confirmed_day():
    conn = _Conn(_version_answers(APPROVED))

    with pytest.raises(ValueError):
        await PostgresDprRepository(conn).create_version(daily_report_id=uuid.uuid4(), payload={})


async def test_confirming_records_who_confirmed():
    conn = _Conn({})
    user_id = uuid.uuid4()

    ok = await PostgresDprRepository(conn).approve_report(
        organization_id=uuid.uuid4(), user_id=user_id, report_id=uuid.uuid4(), notes=None
    )

    assert ok
    [status_update, version_update] = conn.calls
    assert status_update[1]["from_statuses"] == site_day.sources_for(APPROVED)
    assert "approved_by_user_id" in version_update[0]
    assert version_update[1]["user_id"] == user_id


async def test_a_refused_confirmation_stamps_nothing():
    conn = _Conn({"SET status = 'APPROVED'": _Result(rowcount=0)})

    ok = await PostgresDprRepository(conn).approve_report(
        organization_id=uuid.uuid4(), user_id=uuid.uuid4(), report_id=uuid.uuid4(), notes=None
    )

    assert not ok
    assert len(conn.calls) == 1


async def test_open_site_days_labels_a_site_that_logged_nothing_without_a_version(monkeypatch):
    site_id = uuid.uuid4()
    report_id = uuid.uuid4()
    conn = _Conn(
        {
            "FROM sites": _Result([{"id": site_id}]),
            "SELECT status::text AS status, current_version_id": _Result(
                [{"status": DRAFT, "current_version_id": None}]
            ),
        }
    )
    repo = PostgresDprRepository(conn)

    async def _existing_day(**_):
        return report_id

    async def _empty_payload(**_):
        return {"activity_count": 0, "labour": {"headcount": 0}}

    monkeypatch.setattr(repo, "get_or_create_daily_report", _existing_day)
    monkeypatch.setattr(repo, "assemble_site_report_payload", _empty_payload)

    labelled = await repo.open_site_days(
        organization_id=uuid.uuid4(), project_id=uuid.uuid4(), report_date=datetime.date(2026, 10, 13)
    )

    assert labelled == 1
    [update] = conn.updates_to_daily_reports()
    assert update["status"] == NEEDS_DETAILS
    assert not any("INSERT INTO daily_report_versions" in sql for sql, _ in conn.calls)


async def test_open_site_days_leaves_drafted_and_reviewed_days_alone(monkeypatch):
    conn = _Conn(
        {
            "FROM sites": _Result([{"id": uuid.uuid4()}, {"id": uuid.uuid4()}]),
        }
    )
    repo = PostgresDprRepository(conn)
    rows = iter(
        [
            {"status": READY, "current_version_id": uuid.uuid4()},  # already drafted
            {"status": IN_REVIEW, "current_version_id": None},  # with the engineer
        ]
    )

    async def _day(**_):
        return uuid.uuid4()

    async def _execute(statement, params=None):
        sql = str(statement)
        conn.calls.append((sql, params or {}))
        if "current_version_id" in sql and sql.strip().startswith("SELECT"):
            return _Result([next(rows)])
        if "FROM sites" in sql:
            return conn.answers["FROM sites"]
        return _Result()

    monkeypatch.setattr(repo, "get_or_create_daily_report", _day)
    monkeypatch.setattr(conn, "execute", _execute)

    labelled = await repo.open_site_days(
        organization_id=uuid.uuid4(), project_id=uuid.uuid4(), report_date=datetime.date(2026, 10, 13)
    )

    assert labelled == 0
    assert conn.updates_to_daily_reports() == []
