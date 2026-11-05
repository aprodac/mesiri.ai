"""[207] (Paraclette, 2-3 Nov): "Rana Mart" was created three times in one evening from WhatsApp
(cor_f0489a74ef754046980475ad183019df, cor_80ce997a5ed64a9fa948e1f6e0f6e699, cor_62492a18946a42b3a88a4dd12303a6a8),
and adding Sahal to it as site engineer was admin-only. A project name the company already has is refused
(case, spaces and width do not count; a rename too); an admin or this project's manager may add people,
with a role they may give."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from mesiri.domains.projects import router as projects

ORG = uuid.uuid4()
PROJECT = uuid.uuid4()
OTHER = uuid.uuid4()


class FakeConn:
    def __init__(self, *results: list) -> None:
        self.results = list(results)
        self.inserts = 0

    async def execute(self, statement, params=None):  # noqa: ANN001, ANN201
        if getattr(statement, "is_insert", False):
            self.inserts += 1
            return SimpleNamespace()
        rows = self.results.pop(0) if self.results else []
        first = rows[0] if rows else None
        return SimpleNamespace(fetchall=lambda: rows, first=lambda: first, scalar=lambda: None,
                               mappings=lambda: SimpleNamespace(first=lambda: first))


def _projects(*names: str) -> list:
    return [SimpleNamespace(id=uuid.uuid4(), name=n) for n in names]


@pytest.mark.parametrize("said", ["Rana Mart", "rana mart", "  RANA   MART ", "Ｒａｎａ Ｍａｒｔ"])
async def test_the_reported_project_is_not_created_again(said: str) -> None:
    conn = FakeConn(_projects("Rana Mart", "Green Villa"))
    with pytest.raises(HTTPException) as refused:
        await projects.create_project(projects.ProjectCreate(name=said), {"org": str(ORG)}, conn)
    assert refused.value.status_code == 409 and refused.value.detail == "Rana Mart already exists"
    assert conn.inserts == 0


async def test_guard_a_different_name_still_creates() -> None:
    conn = FakeConn(_projects("Rana Mart"))
    made = await projects.create_project(projects.ProjectCreate(name="Rana Mall"), {"org": str(ORG)}, conn)
    assert made.name == "Rana Mall" and conn.inserts == 1


def _who(role: str, projects_reached: set[uuid.UUID] | None = None):  # noqa: ANN202
    scope = SimpleNamespace(grants_all_org_projects=role == "ADMIN", project_ids=projects_reached or set())
    return SimpleNamespace(role=role, organization_id=ORG, project_scope=scope)


async def _add(who, role: str = "SITE_ENGINEER"):  # noqa: ANN001, ANN202
    sahal = SimpleNamespace(id=uuid.uuid4(), email="s@x", full_name="Sahal", status="active")
    conn = FakeConn([SimpleNamespace(id=PROJECT)], [sahal])
    body = projects.ProjectMemberAdd(userId=sahal.id, role=role)
    return await projects.add_project_member(PROJECT, body, who, conn), conn


async def test_an_admin_adds_sahal_as_site_engineer() -> None:
    added, conn = await _add(_who("ADMIN"), "site_engineer")
    assert added.role == "SITE_ENGINEER" and conn.inserts == 1


async def test_sibling_this_projects_manager_may_add_a_site_engineer() -> None:
    added, _ = await _add(_who("PROJECT_MANAGER", {PROJECT}))
    assert added.role == "SITE_ENGINEER"


@pytest.mark.parametrize(("who", "role"), [
    (_who("SITE_ENGINEER", {PROJECT}), "SITE_ENGINEER"),  # a worker
    (_who("PROJECT_MANAGER", {OTHER}), "SITE_ENGINEER"),  # another project's manager
    (_who("PROJECT_MANAGER", {PROJECT}), "ADMIN"),  # a manager making an admin
])
async def test_guard_who_may_not_is_refused(who, role: str) -> None:  # noqa: ANN001
    with pytest.raises(HTTPException) as refused:
        await _add(who, role)
    assert refused.value.status_code == 403


async def test_guard_an_unknown_role_is_refused() -> None:
    with pytest.raises(HTTPException) as refused:
        await _add(_who("ADMIN"), "SUPERVISOR")
    assert refused.value.status_code == 422
