"""BE-42: a member limited to some sites sees only those sites on the Today
page (GET /dpr/site-days) and in the Daily Reports history (GET /dpr/daily-reports)."""

from __future__ import annotations

import datetime
import uuid

import pytest

from mesiri.authorization.context import (
    AccessPolicy,
    AuthorizationContext,
    ProjectAccessScope,
    SiteAccessScope,
)
from mesiri.domains.dpr import router as dpr_router

ORG = uuid.uuid4()
P1, P2 = uuid.uuid4(), uuid.uuid4()
S1A, S1B, S2A = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _ctx(site_scopes, *, all_projects=False):
    return AuthorizationContext(
        user_id=uuid.uuid4(),
        organization_id=ORG,
        role="SITE_ENGINEER",
        status="active",
        access_policy=AccessPolicy(mode="custom_projects", projects=[]),
        project_scope=ProjectAccessScope(
            mode="all_projects" if all_projects else "custom_projects",
            project_ids=set() if all_projects else set(site_scopes),
        ),
        site_scopes=site_scopes,
    )


LIMITED = _ctx(
    {
        P1: SiteAccessScope(mode="custom_sites", site_ids={S1A}),
        P2: SiteAccessScope(mode="all_sites", site_ids=set()),
    }
)
ADMIN = _ctx(
    {
        P1: SiteAccessScope(mode="all_sites", site_ids=set()),
        P2: SiteAccessScope(mode="all_sites", site_ids=set()),
    },
    all_projects=True,
)


def test_site_filter_names_the_limited_projects_and_their_sites():
    assert dpr_router._site_filter(LIMITED, {P1, P2}) == ({P1}, {S1A})
    assert dpr_router._site_filter(LIMITED, {P2}) == (set(), set())
    assert dpr_router._site_filter(ADMIN, None) == (set(), set())
    # A project missing from the scopes is denied every site (as _site_denied does).
    stray = uuid.uuid4()
    assert dpr_router._site_filter(LIMITED, {stray}) == ({stray}, set())


class _FakeRepo:
    calls: dict = {}

    def __init__(self, conn):
        pass

    async def list_site_days(self, **kw):
        return [
            {"site_id": S1A, "project_id": P1},
            {"site_id": S1B, "project_id": P1},
            {"site_id": S2A, "project_id": P2},
        ]

    async def list_project_days(self, **kw):
        return [{"project_id": P1}, {"project_id": P2}]

    async def list_reports(self, **kw):
        _FakeRepo.calls = kw
        return [], 0


class _FakeReviews:
    def __init__(self, conn):
        pass

    async def draft_counts_by_site(self, **kw):
        return {}


@pytest.fixture
def fakes(monkeypatch):
    monkeypatch.setattr(dpr_router, "PostgresDprRepository", _FakeRepo)
    monkeypatch.setattr(dpr_router, "PostgresFactReviewRepository", _FakeReviews)


async def test_today_page_hides_the_sites_a_limited_member_cannot_see(fakes):
    out = await dpr_router.list_site_days(
        report_date=datetime.date(2026, 10, 19), project_id=None, auth_context=LIMITED, conn=None
    )
    assert [i["site_id"] for i in out["items"]] == [S1A, S2A]
    assert len(out["projects"]) == 2


async def test_today_page_is_unchanged_for_full_access(fakes):
    out = await dpr_router.list_site_days(
        report_date=datetime.date(2026, 10, 19), project_id=None, auth_context=ADMIN, conn=None
    )
    assert len(out["items"]) == 3


async def test_history_passes_the_site_limit_to_the_query(fakes):
    await dpr_router.list_daily_reports(
        project_id=None,
        site_id=None,
        status=None,
        level=None,
        category=None,
        date_from=None,
        date_to=None,
        limit=50,
        offset=0,
        auth_context=LIMITED,
        conn=None,
    )
    assert _FakeRepo.calls["restricted_project_ids"] == {P1}
    assert _FakeRepo.calls["allowed_site_ids"] == {S1A}
    await dpr_router.list_daily_reports(
        project_id=None,
        site_id=None,
        status=None,
        level=None,
        category=None,
        date_from=None,
        date_to=None,
        limit=50,
        offset=0,
        auth_context=ADMIN,
        conn=None,
    )
    assert _FakeRepo.calls["restricted_project_ids"] == set()
