"""BE-28: a route's own HTTP errors come back as themselves, not as 500.

Routes take their connection from `get_db_conn`, which keeps
`PostgresDatabase.transaction()` open for the whole request. That context
manager mapped every exception raised inside it to "postgres unavailable",
so a 404/409/422 raised by the route reached the client as a 500. Database
errors must still be mapped, and both must still roll back."""

from __future__ import annotations

import contextlib
import types

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri_contracts.common.errors import MesiriError


class _FakeEngine:
    def __init__(self):
        self.outcomes: list[str] = []

    @contextlib.asynccontextmanager
    async def begin(self):
        try:
            yield object()
        except BaseException:
            self.outcomes.append("rollback")
            raise
        self.outcomes.append("commit")


def _database() -> tuple[PostgresDatabase, _FakeEngine]:
    engine = _FakeEngine()
    db = PostgresDatabase.__new__(PostgresDatabase)
    db._engine = engine
    return db, engine


async def test_an_http_error_passes_through_and_still_rolls_back():
    db, engine = _database()

    with pytest.raises(HTTPException) as exc:
        async with db.transaction():
            raise HTTPException(status_code=404, detail="Site not found")

    assert exc.value.status_code == 404
    assert engine.outcomes == ["rollback"]


async def test_a_database_error_is_still_mapped():
    db, engine = _database()

    with pytest.raises(MesiriError):
        async with db.transaction():
            raise ConnectionError("server closed the connection")

    assert engine.outcomes == ["rollback"]


async def test_success_commits():
    db, engine = _database()

    async with db.transaction():
        pass

    assert engine.outcomes == ["commit"]


@pytest.mark.parametrize("status", [401, 403, 404, 409, 422])
def test_a_route_using_get_db_conn_returns_its_own_status(status):
    db, engine = _database()
    app = FastAPI()
    app.state.container = types.SimpleNamespace(material_db=db)

    @app.get("/thing")
    async def thing(conn=Depends(get_db_conn)):
        raise HTTPException(status_code=status, detail="nope")

    response = TestClient(app, raise_server_exceptions=False).get("/thing")

    assert response.status_code == status
    assert response.json() == {"detail": "nope"}
    assert engine.outcomes == ["rollback"]
