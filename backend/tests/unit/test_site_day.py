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
    "conditions": {"weather": "sunny", "tomorrow_plan": "Floor 4 shuttering"},
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
        "optional": ["photos", "materials", "weather", "tomorrow_plan"],
    }


def test_missing_photos_materials_weather_and_plan_never_block():
    payload = {"activity_count": 1, "labour": {"headcount": 5}}
    assert site_day.readiness_status(payload) == READY
    assert site_day.missing_sections(payload)["optional"] == [
        "photos",
        "materials",
        "weather",
        "tomorrow_plan",
    ]


def test_a_no_work_day_is_ready_with_nothing_required():
    payload = {"conditions": {"site_working": "none"}}
    assert site_day.readiness_status(payload) == READY
    assert site_day.missing_sections(payload) == {"blocking": [], "optional": []}


def test_a_half_day_still_needs_work_and_labour():
    payload = {"conditions": {"site_working": "half"}}
    assert site_day.missing_sections(payload)["blocking"] == ["work_done", "labour"]


@pytest.mark.parametrize(
    "changes",
    [
        {"weather": "foggy"},
        {"site_working": "maybe"},
        {"hours_lost": -1},
        {"hours_lost": 25},
    ],
)
def test_bad_conditions_are_refused(changes):
    with pytest.raises(ValueError):
        site_day.validate_conditions(changes)


def test_good_conditions_and_clearing_are_accepted():
    site_day.validate_conditions(
        {"weather": "rainy", "site_working": "half", "hours_lost": 2.5, "tomorrow_plan": "x"}
    )
    site_day.validate_conditions({"weather": None, "hours_lost": None})


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
    # First call: the day lookup for confirming its drafts (BE-09); unknown
    # here, so nothing else is read.
    [_scope, status_update, version_update] = conn.calls
    assert status_update[1]["from_statuses"] == site_day.sources_for(APPROVED)
    assert "approved_by_user_id" in version_update[0]
    assert version_update[1]["user_id"] == user_id


async def test_a_refused_confirmation_stamps_nothing():
    conn = _Conn({"SET status = 'APPROVED'": _Result(rowcount=0)})

    ok = await PostgresDprRepository(conn).approve_report(
        organization_id=uuid.uuid4(), user_id=uuid.uuid4(), report_id=uuid.uuid4(), notes=None
    )

    assert not ok
    assert len(conn.calls) == 2  # the day lookup and the refused status update
    assert not any("approved_by_user_id" in sql for sql, _ in conn.calls)


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


# ---------------------------------------------------------------------------
# BE-14: site conditions
# ---------------------------------------------------------------------------


def test_payload_carries_the_days_conditions():
    from mesiri.application.dpr.assembly import build_site_report_payload

    payload = build_site_report_payload(
        project_name="P",
        site_name="S",
        report_date=datetime.date(2026, 10, 13),
        activity_rows=[],
        quantities_by_activity={},
        evidence_count_by_activity={},
        issue_rows=[],
        conditions={"weather": "rainy", "hours_lost": 3, "site_working": "half", "tomorrow_plan": "Rebar"},
    )

    assert payload["conditions"] == {
        "weather": "rainy",
        "site_working": "half",
        "tomorrow_plan": "Rebar",
        "hours_lost": "3",
        "hours_lost_source": "entered",
    }


def test_hours_lost_defaults_to_the_days_issue_delays():
    from mesiri.application.dpr.assembly import build_site_report_payload

    payload = build_site_report_payload(
        project_name="P",
        site_name="S",
        report_date=datetime.date(2026, 10, 13),
        activity_rows=[],
        quantities_by_activity={},
        evidence_count_by_activity={},
        issue_rows=[
            {"issue_type": "WEATHER", "status": "OPEN", "delay_duration_minutes": 90},
            {"issue_type": "ACCESS", "status": "RESOLVED", "delay_duration_minutes": 30},
        ],
    )

    assert payload["conditions"]["hours_lost"] == "2.0"
    assert payload["conditions"]["hours_lost_source"] == "issues"


def test_hours_lost_from_issues_is_never_more_than_a_day():
    from mesiri.application.dpr.assembly import build_site_report_payload

    payload = build_site_report_payload(
        project_name="P",
        site_name="S",
        report_date=datetime.date(2026, 10, 13),
        activity_rows=[],
        quantities_by_activity={},
        evidence_count_by_activity={},
        issue_rows=[
            {"issue_type": "WEATHER", "status": "OPEN", "delay_duration_minutes": 2880},
            {"issue_type": "ACCESS", "status": "OPEN", "delay_duration_minutes": 240},
        ],
    )

    assert payload["conditions"]["hours_lost"] == "24.0"


def test_no_conditions_and_no_delays_leave_everything_unset():
    from mesiri.application.dpr.assembly import build_site_report_payload

    payload = build_site_report_payload(
        project_name="P",
        site_name="S",
        report_date=datetime.date(2026, 10, 13),
        activity_rows=[],
        quantities_by_activity={},
        evidence_count_by_activity={},
        issue_rows=[],
    )

    assert payload["conditions"]["hours_lost"] is None
    assert payload["conditions"]["weather"] is None


def _conditions_repo(monkeypatch, *, status: str, payload: dict):
    conn = _Conn({"SELECT status::text AS status FROM daily_reports": _Result([{"status": status}])})
    repo = PostgresDprRepository(conn)

    async def _day(**_):
        return uuid.uuid4()

    async def _payload(**_):
        return payload

    monkeypatch.setattr(repo, "get_or_create_daily_report", _day)
    monkeypatch.setattr(repo, "assemble_site_report_payload", _payload)
    return conn, repo


async def _set(repo, changes):
    return await repo.set_site_day_conditions(
        organization_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        site_id=uuid.uuid4(),
        report_date=datetime.date(2026, 10, 13),
        changes=changes,
    )


async def test_marking_no_work_makes_a_collecting_day_ready_straight_away(monkeypatch):
    conn, repo = _conditions_repo(
        monkeypatch, status=DRAFT, payload={"conditions": {"site_working": "none"}}
    )

    result = await _set(repo, {"site_working": "none"})

    assert result["status"] == "ready"
    updates = conn.updates_to_daily_reports()
    assert updates[0] == {"site_working": "none", "id": updates[0]["id"]}
    assert updates[-1]["status"] == READY


async def test_setting_weather_before_cutoff_keeps_the_day_collecting(monkeypatch):
    conn, repo = _conditions_repo(
        monkeypatch, status=DRAFT, payload={"conditions": {"weather": "sunny"}}
    )

    result = await _set(repo, {"weather": "sunny"})

    assert result["status"] == "draft"
    assert len(conn.updates_to_daily_reports()) == 1  # the weather, no status change


async def test_conditions_of_a_confirmed_day_cannot_change(monkeypatch):
    conn, repo = _conditions_repo(monkeypatch, status=APPROVED, payload={})

    with pytest.raises(InvalidSiteDayTransition):
        await _set(repo, {"weather": "sunny"})
    assert conn.updates_to_daily_reports() == []


async def test_only_known_condition_fields_are_written(monkeypatch):
    conn, repo = _conditions_repo(monkeypatch, status=DRAFT, payload={"conditions": {}})

    await _set(repo, {"weather": "cloudy", "status": "APPROVED"})

    [update] = conn.updates_to_daily_reports()
    assert set(update) == {"weather", "id"}


def test_plain_pdf_shows_conditions_and_tomorrows_plan():
    from mesiri.domains.dpr.pdf import _conditions_line, render_dpr_pdf_bytes

    assert _conditions_line({"weather": "rainy", "site_working": "half", "hours_lost": "2.0"}) == (
        "Weather: Rain  |  Site working: Half day  |  Hours lost: 2.0 h"
    )
    assert _conditions_line({}) == "Weather: Not set  |  Site working: Not set  |  Hours lost: -"
    pdf = render_dpr_pdf_bytes(
        code="DPR-1",
        report_date="2026-10-13",
        project_name="P",
        site_name="S",
        workflow_status="draft",
        payload={"level": "SITE", "conditions": {"weather": "sunny", "tomorrow_plan": "Rebar"}},
    )
    assert pdf.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# WEB-03: the Today page's data
# ---------------------------------------------------------------------------


async def test_site_days_carry_live_counts_as_numbers_and_parsed_missing_sections():
    row = {
        "site_id": uuid.uuid4(),
        "site_name": "Tower B",
        "project_id": uuid.uuid4(),
        "project_name": "Green Valley",
        "daily_report_id": None,
        "code": None,
        "status": "needs_details",
        "missing_sections": '{"blocking": ["labour"], "optional": []}',
        "site_working": None,
        "workers": None,
        "work_items": 4,
        "photos": 0,
        "open_issues": 2,
        "materials": 3,
        "issues_today": None,
        "progress_updates": 1,
        "last_update_at": None,
        "last_update_by": None,
        "latest_update": None,
    }
    conn = _Conn({"WITH acts AS": _Result([row])})

    [day] = await PostgresDprRepository(conn).list_site_days(
        organization_id=uuid.uuid4(), project_ids=None, report_date=datetime.date(2026, 10, 13)
    )

    assert day["missing_sections"] == {"blocking": ["labour"], "optional": []}
    assert (day["workers"], day["work_items"], day["open_issues"]) == (0, 4, 2)
    assert (day["materials"], day["issues_today"], day["progress_updates"]) == (3, 0, 1)
    sql, params = conn.calls[0]
    assert "COALESCE(NULLIF(lal.headcount, 0), 1)" in sql  # same per-line rule as the DPR
    assert "project_ids" not in params


async def test_site_days_are_limited_to_the_projects_the_user_can_see():
    conn = _Conn({"WITH acts AS": _Result([])})
    allowed = {uuid.uuid4()}

    await PostgresDprRepository(conn).list_site_days(
        organization_id=uuid.uuid4(), project_ids=allowed, report_date=datetime.date(2026, 10, 13)
    )

    sql, params = conn.calls[0]
    assert "s.project_id = ANY(:project_ids)" in sql
    assert params["project_ids"] == list(allowed)


async def test_project_days_skip_projects_without_active_sites():
    with_sites = {
        "project_id": uuid.uuid4(),
        "project_name": "A",
        "reporting_cutoff_time": "18:00",
        "dpr_send_deadline": "21:00",
        "auto_generate_dpr": True,
        "sent": None,
        "send_requested": None,
        "site_count": 2,
        "project_report_status": None,
        "project_report_id": None,
    }
    without_sites = {**with_sites, "project_id": uuid.uuid4(), "project_name": "B", "site_count": 0}
    conn = _Conn({"FROM projects p": _Result([with_sites, without_sites])})

    projects = await PostgresDprRepository(conn).list_project_days(
        organization_id=uuid.uuid4(), project_ids=None, report_date=datetime.date(2026, 10, 13)
    )

    assert [p["project_name"] for p in projects] == ["A"]
    assert projects[0]["sent"] is False and projects[0]["send_requested"] is False
