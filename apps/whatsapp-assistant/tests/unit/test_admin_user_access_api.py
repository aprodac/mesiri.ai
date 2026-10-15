from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from projects import router as projects_router
from users.access_service import AccessPolicy
from users.access_service import validate_access_policy as _validate_access_policy


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, results):
        self._results = list(results)
        self.executed = []

    async def execute(self, statement):
        self.executed.append(statement)
        return _Result(self._results.pop(0))


class _ConnectContext:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _Engine:
    def __init__(self, conn):
        self._conn = conn

    def connect(self):
        return _ConnectContext(self._conn)

    def begin(self):
        return _ConnectContext(self._conn)


@pytest.mark.asyncio
async def test_list_project_sites_returns_org_scoped_sites(monkeypatch):
    project_id = uuid.uuid4()
    site_id = uuid.uuid4()
    conn = _Conn(
        [
            [SimpleNamespace(id=project_id)],
            [
                SimpleNamespace(
                    id=site_id,
                    project_id=project_id,
                    name="Tower A",
                    status="active",
                )
            ],
        ]
    )
    monkeypatch.setattr(projects_router, "get_engine", lambda: _Engine(conn))

    sites = await projects_router.list_project_sites(project_id, {"org": str(uuid.uuid4())})

    assert len(sites) == 1
    assert sites[0].id == site_id
    assert sites[0].project_id == project_id
    assert sites[0].name == "Tower A"


@pytest.mark.asyncio
async def test_list_project_sites_rejects_project_outside_org(monkeypatch):
    conn = _Conn([[]])
    monkeypatch.setattr(projects_router, "get_engine", lambda: _Engine(conn))

    with pytest.raises(HTTPException) as exc:
        await projects_router.list_project_sites(uuid.uuid4(), {"org": str(uuid.uuid4())})

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_project_returns_org_scoped_project(monkeypatch):
    project_id = uuid.uuid4()
    conn = _Conn(
        [
            [
                SimpleNamespace(
                    id=project_id,
                    name="Marina Tower",
                    location="Dubai Marina",
                    code="MT-01",
                    client="Acme",
                    description="Residential tower",
                    status="on_track",
                    progress=40,
                    open_issues=2,
                )
            ]
        ]
    )
    monkeypatch.setattr(projects_router, "get_engine", lambda: _Engine(conn))

    project = await projects_router.get_project(project_id, {"org": str(uuid.uuid4())})

    assert project.id == project_id
    assert project.name == "Marina Tower"
    assert project.status == "success"
    assert project.openIssues == 2


@pytest.mark.asyncio
async def test_get_project_rejects_project_outside_org(monkeypatch):
    conn = _Conn([[]])
    monkeypatch.setattr(projects_router, "get_engine", lambda: _Engine(conn))

    with pytest.raises(HTTPException) as exc:
        await projects_router.get_project(uuid.uuid4(), {"org": str(uuid.uuid4())})

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_project_site_inserts_org_scoped_site(monkeypatch):
    project_id = uuid.uuid4()
    conn = _Conn([[SimpleNamespace(id=project_id)], []])
    monkeypatch.setattr(projects_router, "get_engine", lambda: _Engine(conn))

    site = await projects_router.create_project_site(
        project_id,
        projects_router.SiteCreate(name="  Tower B  "),
        {"org": str(uuid.uuid4()), "role": "ADMIN"},
    )

    assert site.project_id == project_id
    assert site.name == "Tower B"
    assert site.status == "active"
    assert len(conn.executed) == 2  # project check, site insert


@pytest.mark.asyncio
async def test_create_project_site_rejects_project_outside_org(monkeypatch):
    conn = _Conn([[]])
    monkeypatch.setattr(projects_router, "get_engine", lambda: _Engine(conn))

    with pytest.raises(HTTPException) as exc:
        await projects_router.create_project_site(
            uuid.uuid4(),
            projects_router.SiteCreate(name="Tower B"),
            {"org": str(uuid.uuid4()), "role": "ADMIN"},
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_project_site_rejects_unauthorized_role(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        await projects_router.create_project_site(
            uuid.uuid4(),
            projects_router.SiteCreate(name="Tower B"),
            {"org": str(uuid.uuid4()), "role": "SITE_ENGINEER"},
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_project_grants_creator_membership_for_non_admin(monkeypatch):
    """A PROJECT_MANAGER (in _CREATE_ROLES, not _ORG_WIDE_ROLES) must get an
    explicit project_members row for a project they just created -- otherwise
    list_projects/get_project's membership scoping hides it from them."""
    user_id = uuid.uuid4()
    # 1: insert project, 2: _is_org_wide's access_policy lookup (no row -> {}),
    # 3: project_members insert for the creator.
    conn = _Conn([[], [], []])
    monkeypatch.setattr(projects_router, "get_engine", lambda: _Engine(conn))

    await projects_router.create_project(
        projects_router.ProjectCreate(name="Tower C"),
        {"org": str(uuid.uuid4()), "role": "PROJECT_MANAGER", "sub": str(user_id)},
    )

    assert len(conn.executed) == 3
    insert_stmt = conn.executed[2]
    compiled = insert_stmt.compile()
    assert compiled.params["user_id"] == str(user_id)
    assert compiled.params["site_access_mode"] == "all_sites"


@pytest.mark.asyncio
async def test_create_project_skips_membership_row_for_admin(monkeypatch):
    """An ADMIN is already org-wide -- no project_members row needed."""
    conn = _Conn([[]])
    monkeypatch.setattr(projects_router, "get_engine", lambda: _Engine(conn))

    await projects_router.create_project(
        projects_router.ProjectCreate(name="Tower D"),
        {"org": str(uuid.uuid4()), "role": "ADMIN", "sub": str(uuid.uuid4())},
    )

    assert len(conn.executed) == 1


@pytest.mark.asyncio
async def test_validate_access_policy_accepts_matching_project_sites():
    project_id = uuid.uuid4()
    site_id = uuid.uuid4()
    conn = _Conn(
        [
            [SimpleNamespace(id=project_id)],
            [SimpleNamespace(id=site_id, project_id=project_id)],
        ]
    )
    policy = AccessPolicy(
        mode="custom_projects",
        projects=[
            {
                "projectId": str(project_id),
                "siteAccess": {"mode": "custom_sites", "siteIds": [str(site_id)]},
            }
        ],
    )

    await _validate_access_policy(conn, str(uuid.uuid4()), policy)


@pytest.mark.asyncio
async def test_validate_access_policy_rejects_unknown_project():
    policy = AccessPolicy(
        mode="custom_projects",
        projects=[
            {
                "projectId": str(uuid.uuid4()),
                "siteAccess": {"mode": "all_sites"},
            }
        ],
    )

    with pytest.raises(HTTPException) as exc:
        await _validate_access_policy(_Conn([[]]), str(uuid.uuid4()), policy)

    assert exc.value.status_code == 400
    assert "unknown project" in exc.value.detail


@pytest.mark.asyncio
async def test_validate_access_policy_rejects_site_from_different_project():
    project_id = uuid.uuid4()
    other_project_id = uuid.uuid4()
    site_id = uuid.uuid4()
    conn = _Conn(
        [
            [SimpleNamespace(id=project_id)],
            [SimpleNamespace(id=site_id, project_id=other_project_id)],
        ]
    )
    policy = AccessPolicy(
        mode="custom_projects",
        projects=[
            {
                "projectId": str(project_id),
                "siteAccess": {"mode": "custom_sites", "siteIds": [str(site_id)]},
            }
        ],
    )

    with pytest.raises(HTTPException) as exc:
        await _validate_access_policy(conn, str(uuid.uuid4()), policy)

    assert exc.value.status_code == 400
    assert "outside project" in exc.value.detail


@pytest.mark.asyncio
async def test_update_organization_user_status(monkeypatch):
    from admin import router as admin_router
    from admin.router import UserStatusUpdate

    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    conn = _Conn(
        [
            [SimpleNamespace(id=user_id, full_name="Jane Doe", status="active")],  # user check
            [],  # update status query execution
            [],  # audit log entry (BE-05)
            [
                SimpleNamespace(
                    id=user_id,
                    full_name="Jane Doe",
                    email="jane@example.com",
                    role="MEMBER",
                    status="Inactive",
                    whatsapp_number="+1234567890",
                    access_policy=None,
                )
            ],  # fetch user rows
            [],  # fetch project rows
            [],  # fetch site rows
        ]
    )
    monkeypatch.setattr(admin_router, "get_engine", lambda: _Engine(conn))

    admin_id = uuid.uuid4()
    res = await admin_router.update_organization_user_status(
        org_id, user_id, UserStatusUpdate(status="inactive"), {"sub": str(admin_id), "name": "Ops"}
    )

    assert res.id == user_id
    assert res.status == "Inactive"
    audit_insert = conn.executed[2].compile().params
    assert audit_insert["action"] == "company_user.status_changed"
    assert audit_insert["actor_user_id"] == admin_id
    assert audit_insert["organization_id"] == org_id
    assert audit_insert["details"] == {
        "before": {"status": "active"},
        "after": {"status": "inactive"},
    }

