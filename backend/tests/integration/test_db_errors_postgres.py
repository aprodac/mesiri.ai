"""[282] (7 Nov 2026): a value Postgres cannot read is a 422 that says what was
meant, never a crash. Reproduces the live failure through the REAL route and
the REAL `get_db_conn` (whose transaction re-raises every database error as
MesiriError[POSTGRES_UNAVAILABLE]; a stand-in route missed that, and the first
fix still gave production a 500): the assistant listed open issues with
`status=open`; `site_issues.status` is an enum (`OPEN`).
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import APIRouter, FastAPI

from mesiri.authorization.context import AuthorizationContext, ProjectAccessScope
from mesiri.domains.progress.router import router as progress_router
from mesiri.domains.projects.router import get_auth_context
from mesiri.http import db_errors
from mesiri_contracts.common.errors import ErrorCode, MesiriError

pytestmark = pytest.mark.integration


def _app(*, handler: bool) -> FastAPI:
    app = FastAPI()
    if handler:
        db_errors.install(app)
    app.include_router(progress_router)
    app.dependency_overrides[get_auth_context] = lambda: AuthorizationContext(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role="ADMIN",
        status="active",
        access_policy={},  # type: ignore[arg-type]
        project_scope=ProjectAccessScope(mode="all_projects", project_ids=set()),
    )
    outage = APIRouter()

    @outage.get("/outage")
    async def _outage():
        raise MesiriError(ErrorCode.POSTGRES_UNAVAILABLE, "postgres error: connection refused")

    app.include_router(outage)
    return app


async def _get(app: FastAPI, path: str, params: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.get(path, params=params)


async def test_without_the_handler_a_lower_case_status_crashes() -> None:
    """The failure as it was: a 500, which the assistant turned into 'The tool failed'."""
    res = await _get(_app(handler=False), "/progress/issues", {"status": "open"})
    assert res.status_code == 500


async def test_a_lower_case_status_is_a_422_naming_the_meant_value() -> None:
    res = await _get(_app(handler=True), "/progress/issues", {"status": "open"})
    assert res.status_code == 422
    assert "Did you mean 'OPEN'?" in res.json()["detail"]


async def test_a_lower_case_severity_is_a_422_too() -> None:
    """Sibling: the same route's other enum filter."""
    res = await _get(_app(handler=True), "/progress/issues", {"severity": "high"})
    assert res.status_code == 422
    assert "Did you mean 'HIGH'?" in res.json()["detail"]


async def test_the_right_value_still_answers() -> None:
    """Guard: a correct call is untouched."""
    res = await _get(_app(handler=True), "/progress/issues", {"status": "OPEN"})
    assert res.status_code == 200
    assert res.json()["total"] == 0


async def test_a_real_database_failure_is_still_a_500() -> None:
    """Guard: an outage is not turned into a 422 or hidden from error reporting."""
    res = await _get(_app(handler=True), "/outage")
    assert res.status_code == 500


def test_a_made_up_id_is_explained() -> None:
    """Sibling: the model wrote a site id that is not a uuid (7 Nov, Site B); asyncpg's own message."""
    message = ("invalid input for query argument $2: '11116a12-47aa-436c-88be-7a5ea29cc1b92' "
               "(invalid UUID '11116a12-47aa-436c-88be-7a5ea29cc1b92': length must be between 32..36 characters)")
    assert "not a valid id" in (db_errors.invalid_value_detail(message) or "")
