"""DprRequestQueryService's guard clauses -- only the paths that return
before ever touching the database are unit-testable without a live
Postgres (the real query is exercised by CI's live-Postgres integration
lane, not here, same split as test_actor_reader_notifications.py)."""

from __future__ import annotations

import datetime

from runtime.dpr_request_query import DprRequestQueryService

TODAY = datetime.date(2026, 7, 27)


async def test_missing_project_id_returns_not_generated_without_touching_the_db():
    service = DprRequestQueryService(db="unused -- must never be touched")
    result = await service.find_report(
        organization_id="11111111-1111-4111-8111-111111111111",
        project_id=None,
        site_id="44444444-4444-4444-8444-444444444444",
        report_date=TODAY,
    )
    assert result == {"status": "not_generated", "object_key": None, "code": None}


async def test_missing_site_id_with_a_project_id_queries_the_project_level_report():
    """site_id=None is now a valid PROJECT-level lookup (added for
    runtime/project_auto_dpr.py), not a guard-clause short-circuit -- it
    must reach the database, scoped to level='PROJECT' rows. The real query
    shape is exercised by CI's live-Postgres integration lane; this only
    checks the guard clause changed as intended (a fake DB stands in so no
    real Postgres is touched here)."""

    class _FakeResult:
        def mappings(self):
            return self

        def first(self):
            return None

    class _FakeConn:
        async def execute(self, *args, **kwargs):
            return _FakeResult()

    class _FakeTransaction:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, *exc):
            return False

    class _FakeDb:
        def transaction(self):
            return _FakeTransaction()

    service = DprRequestQueryService(db=_FakeDb())
    result = await service.find_report(
        organization_id="11111111-1111-4111-8111-111111111111",
        project_id="33333333-3333-4333-8333-333333333333",
        site_id=None,
        report_date=TODAY,
    )
    assert result == {"status": "not_generated", "object_key": None, "code": None}


async def test_malformed_organization_id_returns_not_generated_without_touching_the_db():
    service = DprRequestQueryService(db="unused -- must never be touched")
    result = await service.find_report(
        organization_id="not-a-uuid",
        project_id="33333333-3333-4333-8333-333333333333",
        site_id="44444444-4444-4444-8444-444444444444",
        report_date=TODAY,
    )
    assert result == {"status": "not_generated", "object_key": None, "code": None}


def _compiled(site_id):
    import uuid

    from sqlalchemy.dialects.postgresql import asyncpg

    from runtime.dpr_request_query import _report_query

    query = _report_query(
        organization_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        site_id=site_id,
        report_date=TODAY,
    )
    return str(query.compile(dialect=asyncpg.dialect()))


def test_level_is_compared_as_the_postgres_enum_not_as_varchar():
    """Regression (request 57, B1): 'send me today's report' said 'can't look
    up today's report' because `daily_report_level = VARCHAR` is not a
    Postgres operator. Once a project is known the query really runs, so the
    bind must be typed as the enum (a ::daily_report_level cast)."""
    import uuid

    for site in (uuid.uuid4(), None):
        sql = _compiled(site)
        assert "::daily_report_level" in sql
        assert "::VARCHAR" not in sql
