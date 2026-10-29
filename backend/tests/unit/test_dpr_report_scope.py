"""BE-49 (audit DSH-02): every /dpr/daily-reports/{id} route checks the
report's project and site, not only the company. A member who can't see the
report's project or site gets 404 and nothing is read or changed; a member
who can see it is let through."""

from __future__ import annotations

import datetime
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mesiri.authorization.context import (
    AccessPolicy,
    AuthorizationContext,
    ProjectAccessScope,
    SiteAccessScope,
)
from mesiri.domains.dpr import router as dpr_router
from mesiri.domains.projects.router import get_auth_context
from mesiri.infrastructure.postgres.dependency import get_db_conn

ORG = uuid.uuid4()
P1, P2 = uuid.uuid4(), uuid.uuid4()
S1A, S1B = uuid.uuid4(), uuid.uuid4()
REPORT = uuid.uuid4()


def _ctx(site_scopes, *, all_projects=False):
    return AuthorizationContext(
        user_id=uuid.uuid4(),
        organization_id=ORG,
        role="PROJECT_MANAGER",
        status="active",
        access_policy=AccessPolicy(mode="custom_projects", projects=[]),
        project_scope=ProjectAccessScope(
            mode="all_projects" if all_projects else "custom_projects",
            project_ids=set() if all_projects else set(site_scopes),
        ),
        site_scopes=site_scopes,
    )


#: Project 1 only, and in it site A only.
LIMITED = _ctx({P1: SiteAccessScope(mode="custom_sites", site_ids={S1A})})
ADMIN = _ctx({}, all_projects=True)

ROUTES = [
    ("get", f"/dpr/daily-reports/{REPORT}", None),
    ("post", f"/dpr/daily-reports/{REPORT}/submit-for-review", None),
    ("post", f"/dpr/daily-reports/{REPORT}/approve", {"notes": None}),
    ("post", f"/dpr/daily-reports/{REPORT}/publish", None),
    ("post", f"/dpr/daily-reports/{REPORT}/revise", {"revision_reason": "fix"}),
    ("get", f"/dpr/daily-reports/{REPORT}/versions", None),
    ("get", f"/dpr/daily-reports/{REPORT}/pdf", None),
]


class _Repo:
    scope: dict | None = None
    acted: list[str] = []

    def __init__(self, conn):
        pass

    async def get_report_scope(self, **_):
        return self.scope

    def __getattr__(self, name):
        # Anything past the scope check: record it and stop the request there.
        async def act(*_a, **_k):
            _Repo.acted.append(name)
            raise RuntimeError("reached")

        return act


@pytest.fixture
def client(monkeypatch):
    _Repo.acted = []
    monkeypatch.setattr(dpr_router, "PostgresDprRepository", _Repo)
    app = FastAPI()
    app.include_router(dpr_router.router)
    app.dependency_overrides[get_db_conn] = lambda: object()

    def as_user(ctx):
        app.dependency_overrides[get_auth_context] = lambda: ctx
        return TestClient(app, raise_server_exceptions=False)

    return as_user


def _scope(project_id, site_id, level="SITE"):
    return {
        "project_id": project_id,
        "site_id": site_id,
        "report_date": datetime.date(2026, 10, 24),
        "level": level,
        "status": "DRAFT",
        "current_version_id": uuid.uuid4(),
    }


@pytest.mark.parametrize(("method", "url", "body"), ROUTES)
@pytest.mark.parametrize(
    "scope",
    [_scope(P2, None, "PROJECT"), _scope(P1, S1B), _scope(None, None, "PROJECT")],
    ids=["other-project", "other-site", "no-project"],
)
def test_a_report_the_member_cannot_see_is_not_found(client, method, url, body, scope):
    _Repo.scope = scope

    res = getattr(client(LIMITED), method)(url, **({"json": body} if body else {}))

    assert res.status_code == 404
    assert _Repo.acted == []  # nothing read or changed past the check


@pytest.mark.parametrize(("method", "url", "body"), ROUTES)
def test_a_report_on_the_members_own_site_gets_past_the_check(client, method, url, body):
    _Repo.scope = _scope(P1, S1A)

    getattr(client(LIMITED), method)(url, **({"json": body} if body else {}))

    assert _Repo.acted  # went on to read or change the report


def test_an_admin_reaches_every_report(client):
    _Repo.scope = _scope(P2, None, "PROJECT")

    client(ADMIN).post(f"/dpr/daily-reports/{REPORT}/approve", json={})

    assert _Repo.acted == ["approve_report"]


def test_another_companys_report_is_not_found(client):
    _Repo.scope = None

    assert client(ADMIN).get(f"/dpr/daily-reports/{REPORT}").status_code == 404


@pytest.mark.parametrize(
    ("body", "allowed"),
    [
        ({"project_id": str(P1), "site_id": str(S1A)}, True),
        ({"project_id": str(P1), "site_id": str(S1B)}, False),
        ({"project_id": str(P2)}, False),
        ({}, False),
    ],
)
def test_creating_a_report_needs_access_to_its_project_and_site(client, body, allowed):
    res = client(LIMITED).post("/dpr/daily-reports", json={"report_date": "2026-10-24", **body})

    if allowed:
        assert _Repo.acted == ["create_report"]
    else:
        assert res.status_code == 403 and _Repo.acted == []
