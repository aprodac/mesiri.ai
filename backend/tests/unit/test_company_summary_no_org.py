"""GET /company/summary for a token with no company in it.

A platform admin's token carries an empty `org` claim. The summary used to
call uuid.UUID() on it and crash with a 500, which the browser reports as a
CORS error because the crash response has no CORS headers. It now answers
400 "Token missing org claim", like every other /company route.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mesiri.domains.identity.auth_service import create_access_token
from mesiri.domains.organizations.router import router
from mesiri.infrastructure.postgres.dependency import get_db_conn


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)

    async def no_db():
        yield None

    app.dependency_overrides[get_db_conn] = no_db
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("claims", [{"org": ""}, {}])
def test_summary_without_org_is_400_not_500(client: TestClient, claims: dict):
    token = create_access_token(data={"sub": str(uuid.uuid4()), "role": "ADMIN", **claims})

    res = client.get("/company/summary", headers={"Authorization": f"Bearer {token}"})

    assert res.status_code == 400
    assert res.json() == {"detail": "Token missing org claim"}
