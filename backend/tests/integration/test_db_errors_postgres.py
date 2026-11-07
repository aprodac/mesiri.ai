"""[282] (7 Nov 2026): a value Postgres cannot read is a 422 that says what was
meant, never a crash. Reproduces the live failure: the assistant listed open
issues with `status=open`; `site_issues.status` is an enum (`OPEN`), the query
raised, and the person read "The tool failed".
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI

from mesiri.http import db_errors
from mesiri.infrastructure.postgres.repositories.progress import PostgresProgressReadRepository

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    from mesiri.bootstrap.settings import Settings

    eng = create_async_engine(Settings().postgres.dsn())
    yield eng
    await eng.dispose()


def _app(engine, *, handler: bool) -> FastAPI:
    app = FastAPI()
    if handler:
        db_errors.install(app)

    @app.get("/issues")
    async def issues(status: str | None = None, site_id: str | None = None):
        async with engine.connect() as conn:
            items, total = await PostgresProgressReadRepository(conn).list_issues(
                organization_id=uuid.uuid4(), project_ids=None, site_id=site_id,
                status=status, severity=None, limit=10, offset=0,
            )
        return {"items": items, "total": total}

    return app


async def _get(app: FastAPI, params: dict) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.get("/issues", params=params)


async def test_without_the_handler_a_lower_case_status_crashes(engine) -> None:
    """The failure as it was: a 500, which the assistant turned into 'The tool failed'."""
    assert (await _get(_app(engine, handler=False), {"status": "open"})).status_code == 500


async def test_a_lower_case_status_is_a_422_naming_the_meant_value(engine) -> None:
    res = await _get(_app(engine, handler=True), {"status": "open"})
    assert res.status_code == 422
    assert "Did you mean 'OPEN'?" in res.json()["detail"]


async def test_a_made_up_id_is_a_422_not_a_crash(engine) -> None:
    """Sibling: the model wrote a site id that is not a uuid (7 Nov, Site B)."""
    res = await _get(_app(engine, handler=True), {"site_id": "11116a12-47aa-436c-88be-7a5ea29cc1b92"})
    assert res.status_code == 422
    assert "not a valid id" in res.json()["detail"]


async def test_the_right_value_still_answers(engine) -> None:
    """Guard: a correct call is untouched."""
    res = await _get(_app(engine, handler=True), {"status": "OPEN"})
    assert res.status_code == 200
    assert res.json() == {"items": [], "total": 0}
