"""WA-77 (Alan, 25 Oct) for attendance, the site log and issues: what counts
is what was saved. A labour line counts once its report is saved, and an
unsaved later report replaces nothing; the Site log, Issues and analytics
leave out entries still waiting for their Save."""

from __future__ import annotations

import inspect
import uuid

from mesiri.infrastructure.postgres.repositories import analytics, progress, workforce


def test_a_labour_line_counts_once_its_report_is_saved():
    sql = workforce.counted_line_sql("lal", "lar")
    assert "fr_c.fact_type = 'labour_report' AND fr_c.fact_id = lar.id" in sql
    # A later report replaces an earlier line only once it is saved itself.
    assert "fr_c.fact_id = later_report.id" in sql
    assert "{" not in sql


class _Rows:
    def mappings(self):
        return self

    def first(self):
        return {"total": 0}

    def all(self):
        return []


class _Conn:
    def __init__(self) -> None:
        self.sql: list[str] = []

    async def execute(self, stmt, params=None):
        self.sql.append(str(stmt))
        return _Rows()


async def test_the_site_log_and_issues_leave_out_unsaved_entries():
    conn = _Conn()
    repo = progress.PostgresProgressReadRepository(conn)
    common = dict(organization_id=uuid.uuid4(), project_ids=None, site_id=None, limit=10, offset=0)
    await repo.list_activities(date_from=None, date_to=None, status=None, **common)
    await repo.list_issues(status=None, severity=None, **common)

    assert all("fact_reviews" in sql for sql in conn.sql)
    assert any("fr_c.fact_id = activities.id" in sql for sql in conn.sql)
    assert any("fr_c.fact_id = site_issues.id" in sql for sql in conn.sql)


def test_analytics_counts_saved_work_and_issues():
    source = inspect.getsource(analytics)
    assert 'counted_sql(fact_review.ACTIVITY, "a.id")' in source
    assert 'counted_sql(fact_review.SITE_ISSUE, "si.id")' in source


def test_an_unsaved_section_is_reported_not_missing():
    """The engineer is asked to keep a draft, not to send the section again."""
    from mesiri.application.dpr import site_day

    nothing = {"activity_count": 0, "labour": {"headcount": 0}}
    assert site_day.missing_sections(nothing)["blocking"] == ["work_done", "labour"]
    unsaved = {**nothing, "drafts": {"activities": 1, "labour_reports": 1}}
    assert site_day.missing_sections(unsaved)["blocking"] == []
