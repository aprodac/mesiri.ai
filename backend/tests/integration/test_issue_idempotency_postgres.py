"""MOB-05: a problem sent twice with the same Idempotency-Key is one problem (the app's form, then the assistant's
Save of the same entry; or a retry), as work, deliveries, use, attendance and expenses already are."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import text

from mesiri.authorization.context import (
    AccessPolicy,
    AuthorizationContext,
    ProjectAccessScope,
    SiteAccessScope,
)
from mesiri.domains.progress.responses import CreateSiteIssueRequest
from mesiri.domains.progress.router import create_issue

# Needs a real Postgres: run with the integration tests, not in the deploy's unit job ("not integration").
pytestmark = pytest.mark.integration


@pytest.fixture
async def conn():
    from sqlalchemy.ext.asyncio import create_async_engine

    from mesiri.bootstrap.settings import Settings

    engine = create_async_engine(Settings().postgres.dsn())
    async with engine.connect() as connection:
        tx = await connection.begin()
        yield connection
        await tx.rollback()
    await engine.dispose()


_USERS: dict[uuid.UUID, uuid.UUID] = {}


async def _site(conn):
    org, project, site, user = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await conn.execute(text("INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at) "
                            "VALUES (:id, 'MOB-05 Co', 'local', 'default', 'active', now())"), {"id": org})
    await conn.execute(text("INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, "
                            "access_policy, created_at, updated_at) VALUES (:id, :o, :e, 'x', 'Ravi', 'site_engineer', "
                            "'active', CAST('{\"mode\": \"all_projects\", \"projects\": []}' AS jsonb), now(), now())"),
                       {"id": user, "o": org, "e": f"{user}@mob05.invalid"})
    _USERS[org] = user
    await conn.execute(text("INSERT INTO projects (id, organization_id, name) VALUES (:id, :o, 'Villa')"),
                       {"id": project, "o": org})
    await conn.execute(text("INSERT INTO sites (id, organization_id, project_id, name) VALUES (:id, :o, :p, 'Annex')"),
                       {"id": site, "o": org, "p": project})
    return org, project, site


def _auth(org: uuid.UUID, project: uuid.UUID) -> AuthorizationContext:
    return AuthorizationContext(
        user_id=_USERS[org],
        organization_id=org,
        role="ADMIN",
        status="active",
        access_policy=AccessPolicy(mode="all_projects", projects=[]),
        project_scope=ProjectAccessScope(mode="all_projects", project_ids=set()),
        site_scopes={project: SiteAccessScope(mode="all_sites", site_ids=set())},
    )


def _problem(project, site, words="Water leak at the sump") -> CreateSiteIssueRequest:
    return CreateSiteIssueRequest(project_id=project, site_id=site, issue_type="OTHER", severity="MEDIUM",
                                  narrative=words)


async def _count(conn, site) -> int:
    return (await conn.execute(text("SELECT count(*) FROM site_issues WHERE site_id = :s"), {"s": site})).scalar_one()


async def test_the_same_key_twice_is_one_problem_and_the_second_answer_is_the_first(conn):
    org, project, site = await _site(conn)
    auth = _auth(org, project)
    first_response, second_response = Response(), Response()
    first_response.status_code = second_response.status_code = None  # as FastAPI injects it: the route's 201 applies

    first = await create_issue(_problem(project, site), first_response, "k-1", auth, conn)
    second = await create_issue(_problem(project, site), second_response, "k-1", auth, conn)

    assert await _count(conn, site) == 1
    assert str(second["id"]) == str(first["id"])
    assert second_response.status_code == 200  # the same key again
    assert first_response.status_code is None  # left alone: 201 recorded


async def test_without_a_key_or_with_another_key_each_send_is_a_problem(conn):
    """Guard: nothing changes for a caller that sends no key (the dashboard's form today)."""
    org, project, site = await _site(conn)
    auth = _auth(org, project)

    await create_issue(_problem(project, site), Response(), None, auth, conn)
    await create_issue(_problem(project, site), Response(), None, auth, conn)
    await create_issue(_problem(project, site, "Cracks in the parapet"), Response(), "k-2", auth, conn)

    assert await _count(conn, site) == 3


async def test_two_companies_using_the_same_key_never_meet(conn):
    org_a, project_a, site_a = await _site(conn)
    org_b, project_b, site_b = await _site(conn)

    await create_issue(_problem(project_a, site_a), Response(), "same", _auth(org_a, project_a), conn)
    await create_issue(_problem(project_b, site_b), Response(), "same", _auth(org_b, project_b), conn)

    assert await _count(conn, site_a) == 1 and await _count(conn, site_b) == 1


async def test_a_key_still_being_saved_is_refused_not_saved_again(conn):
    from mesiri.domains.shared.execution import idempotency_uuid

    org, project, site = await _site(conn)
    await conn.execute(text("INSERT INTO idempotency_keys (key, command_type, status) VALUES (:k, 'x', 'in_progress')"),
                       {"k": idempotency_uuid(org, "busy")})

    with pytest.raises(HTTPException) as refused:
        await create_issue(_problem(project, site), Response(), "busy", _auth(org, project), conn)

    assert refused.value.status_code == 409 and await _count(conn, site) == 0
