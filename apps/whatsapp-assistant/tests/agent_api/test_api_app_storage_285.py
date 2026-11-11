"""[285] (live, 11 Nov 12:57 and 12:58, New India): "one week report" -> period_report was "unavailable" twice.

Root cause: the API app v3 calls in the worker (``build_api_app``) put only the database on
``app.state.container``. ``get_object_storage`` reads ``container.object_storage``, so every route that takes
the storage dependency (the period report, and the siblings: DPR, materials, expenses, progress, tasks,
workforce, places, documents, orders, returns) raised AttributeError -> 500 -> "could not check it right now".
"""

from __future__ import annotations

from fastapi import Depends
from fastapi.testclient import TestClient

from agent_api.app import API_ROUTERS, build_api_app
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri_contracts.common.storage import ObjectStoragePort


def _storage_of(app) -> object:
    @app.get("/_probe_storage")
    async def probe(storage=Depends(get_object_storage)) -> dict:  # noqa: B008
        return {"storage": type(storage).__name__, "port": isinstance(storage, ObjectStoragePort)}

    with TestClient(app) as client:
        return client.get("/_probe_storage")


def test_a_route_that_needs_storage_gets_it_in_the_agent_app() -> None:
    response = _storage_of(build_api_app(None))
    assert response.status_code == 200, response.text
    assert response.json()["port"] is True


def test_the_worker_can_hand_its_own_storage_in() -> None:
    from mesiri.infrastructure.objectstorage.fake import FakeObjectStorage

    mine = FakeObjectStorage()
    app = build_api_app(None, object_storage=mine)
    assert get_object_storage(type("R", (), {"app": app})()) is mine


def test_the_database_is_still_the_workers_own() -> None:  # guard: the [WA-119] wiring is unchanged
    db = object()
    app = build_api_app(db)
    assert app.state.container.material_db is db
    assert "mesiri.domains.reports.period.router" in API_ROUTERS
