"""The duplicate-day lookup must bind a real date, and must never cost a message.

Shipped broken: `occurred_date` travels through the canonical event as an ISO
*string*, and was handed straight to a DATE comparison. asyncpg is strictly
typed -- it raises DataError rather than casting -- so every labour attendance
message died, and because the seeding gather has no `return_exceptions` the
failure reached the journey's catch-all. The supervisor saw
"⚠️ Something went wrong handling that — nothing was recorded."

Two things are pinned here, because either alone would have let it through:
the parameter is bound as a `datetime.date`, and a failure in this optional
check degrades to not asking rather than losing the attendance.
"""

from __future__ import annotations

import datetime

from mesiri_contracts.assistant.planner_decision import WorkflowKey
from runtime.inbound_journey.seeding import _seed_existing_attendance
from runtime.workforce_query import PostgresWorkforceQueryService

ORG = "11111111-1111-4111-8111-111111111111"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "44444444-4444-4444-8444-444444444444"


class _CapturingConn:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))

        class _R:
            def first(self_inner):
                return None

        return _R()


class _CapturingDb:
    def __init__(self):
        self.conn = _CapturingConn()

    def transaction(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


class _Actor:
    organization_id = ORG
    user_id = "22222222-2222-4222-8222-222222222222"


class _Event:
    def __init__(self, occurred_date="2026-07-29", project_id=PRJ, site_id=SITE):
        self.project_id = project_id
        self.site_id = site_id
        self.fields = {"occurred_date": occurred_date} if occurred_date else {}


class _Decision:
    workflow_key = WorkflowKey.LABOUR_ATTENDANCE


class _Exploding:
    async def find_existing_report_for_day(self, **kwargs):
        raise RuntimeError("database is unreachable")


# --- The bug itself --------------------------------------------------------

async def test_the_date_is_bound_as_a_date_not_the_iso_string():
    """asyncpg will not coerce '2026-07-29' into a DATE. Binding the raw
    string is what took every attendance message down."""
    db = _CapturingDb()
    await PostgresWorkforceQueryService(db).find_existing_report_for_day(
        organization_id=ORG, project_id=PRJ, site_id=SITE, occurred_date="2026-07-29"
    )

    _, params = db.conn.calls[0]
    assert isinstance(params["occurred_date"], datetime.date), (
        f"bound {type(params['occurred_date'])}, which asyncpg rejects for a DATE column"
    )
    assert params["occurred_date"] == datetime.date(2026, 7, 29)


async def test_a_date_object_is_accepted_too():
    db = _CapturingDb()
    await PostgresWorkforceQueryService(db).find_existing_report_for_day(
        organization_id=ORG, project_id=PRJ, site_id=SITE,
        occurred_date=datetime.date(2026, 7, 29),
    )
    assert db.conn.calls[0][1]["occurred_date"] == datetime.date(2026, 7, 29)


async def test_an_unparseable_date_returns_none_without_querying():
    for bad in ("not-a-date", "", "   ", None):
        db = _CapturingDb()
        got = await PostgresWorkforceQueryService(db).find_existing_report_for_day(
            organization_id=ORG, project_id=PRJ, site_id=SITE, occurred_date=bad
        )
        assert got is None
        assert db.conn.calls == []


async def test_a_null_site_is_compared_with_is_null():
    """`= NULL` is always false, so a project with no named site could never
    detect its own duplicate."""
    db = _CapturingDb()
    await PostgresWorkforceQueryService(db).find_existing_report_for_day(
        organization_id=ORG, project_id=PRJ, site_id=None, occurred_date="2026-07-29"
    )
    sql, params = db.conn.calls[0]
    assert "site_id IS NULL" in sql
    assert "site_id" not in params


# --- Why it was fatal rather than merely broken ----------------------------

async def test_a_failing_lookup_does_not_take_the_message_down():
    """The seeding gather has no return_exceptions, so anything raised here
    reaches the journey's catch-all. This check improves recording; it is
    never a precondition for it."""
    event = _Event()
    await _seed_existing_attendance(event, _Decision(), _Exploding(), _Actor())
    assert "existing_report" not in event.fields


async def test_nothing_is_asked_when_the_day_has_no_date_resolved():
    class _Never:
        async def find_existing_report_for_day(self, **kwargs):
            raise AssertionError("must not query without a date")

    event = _Event(occurred_date=None)
    await _seed_existing_attendance(event, _Decision(), _Never(), _Actor())
    assert "existing_report" not in event.fields


async def test_nothing_is_asked_without_a_project():
    class _Never:
        async def find_existing_report_for_day(self, **kwargs):
            raise AssertionError("must not query without a project")

    event = _Event(project_id=None)
    await _seed_existing_attendance(event, _Decision(), _Never(), _Actor())
    assert "existing_report" not in event.fields


# --- BE-10: save-first companies are told, not asked -----------------------

class _Found:
    async def find_existing_report_for_day(self, **kwargs):
        return {
            "report_id": "55555555-5555-4555-8555-555555555555",
            "total_headcount": 10,
            "counted_lines": [{"contractor": "Ravi", "trade": "mason", "headcount": 10}],
        }


class _Settings:
    def __init__(self, mode):
        self.mode = mode

    async def get(self, *, organization_id, key):
        return self.mode


async def test_a_save_first_company_is_not_asked_and_gets_the_days_lines():
    """BE-10: labour is the latest figure per contractor + trade, so a
    save-first company is not asked "replace or separate?". What the day
    counts so far is seeded for the saved reply to say what changed."""
    event = _Event()
    await _seed_existing_attendance(
        event, _Decision(), _Found(), _Actor(), org_settings_query=_Settings("save_first")
    )
    assert "existing_report" not in event.fields
    assert event.fields["day_counted_lines"] == [
        {"contractor": "Ravi", "trade": "mason", "headcount": 10}
    ]


async def test_a_confirm_first_company_is_still_asked():
    event = _Event()
    await _seed_existing_attendance(
        event, _Decision(), _Found(), _Actor(), org_settings_query=_Settings("confirm_first")
    )
    assert event.fields["existing_report"]["report_id"]
    assert "day_counted_lines" not in event.fields


async def test_an_unreadable_capture_mode_falls_back_to_save_first():
    class _Broken:
        async def get(self, **kwargs):
            raise RuntimeError("settings table unreachable")

    event = _Event()
    await _seed_existing_attendance(
        event, _Decision(), _Found(), _Actor(), org_settings_query=_Broken()
    )
    assert "existing_report" not in event.fields
    assert "day_counted_lines" in event.fields
