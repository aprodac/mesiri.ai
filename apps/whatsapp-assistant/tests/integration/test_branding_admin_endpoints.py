"""SA-09: the control panel's branding requests and letterhead routes, on
Postgres: photos are served only by position in the company's own request,
"mark done" hands over to the assistant, every change is audited, and a
company admin can't use any of it."""

from __future__ import annotations

import base64
import datetime as dt
import uuid
from types import SimpleNamespace

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.fixtures.db import build_sync_engine

from mesiri.domains.admin.branding_router import router as branding_router
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY
from mesiri.domains.organizations import setup_questions
from mesiri.infrastructure.objectstorage.fake import FakeObjectStorage
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PHOTO = b"\xff\xd8\xff\xe0" + b"photo" * 10
_NOW = dt.datetime(2026, 10, 15, 9, 0, tzinfo=dt.UTC)


def _password() -> str:
    import os

    return os.environ.get("MESIRI_POSTGRES__PASSWORD", "mesiri_local_dev")


def _token(role: str, org: uuid.UUID | None) -> dict:
    claims = {
        "sub": str(uuid.uuid4()),
        "role": role,
        "org": str(org) if org else "",
        "name": "Alan",
    }
    return {"Authorization": "Bearer " + jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)}


@pytest.fixture
def world():
    import json

    engine = build_sync_engine()
    org = uuid.uuid4()
    storage = FakeObjectStorage()
    # One request with two photos; the second photo's file is gone (the
    # in-memory storage forgets on restart, INF-09).
    requests, _ = setup_questions.add_branding_files(
        [],
        object_key=f"org/{org}/branding-requests/a.jpg",
        content_type="image/jpeg",
        sent_by="owner",
        now=_NOW,
    )
    requests, _ = setup_questions.add_branding_files(
        requests,
        object_key=f"org/{org}/branding-requests/b.jpg",
        content_type="image/jpeg",
        sent_by="owner",
        now=_NOW,
    )
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO organizations (id, name, status, db_route, deployment_type, address) "
                "VALUES (:id, 'Skyline Builders', 'trial', 'shared', 'SaaS', 'Old address')"
            ),
            {"id": org},
        )
        c.execute(
            text(
                "INSERT INTO organization_settings (id, organization_id, key, value) "
                "VALUES (:id, :org, 'branding_requests', CAST(:v AS jsonb))"
            ),
            {"id": uuid.uuid4(), "org": org, "v": json.dumps(requests)},
        )

    import asyncio

    asyncio.run(
        storage.put_object(f"org/{org}/branding-requests/a.jpg", PHOTO, content_type="image/jpeg")
    )

    app = FastAPI()
    app.state.container = SimpleNamespace(object_storage=storage)
    app.include_router(branding_router)

    async def db_conn():
        engine_ = create_async_engine(
            str(engine.url).replace("+psycopg", "+asyncpg").replace("***", _password())
        )
        async with engine_.begin() as conn:
            yield conn
        await engine_.dispose()

    app.dependency_overrides[get_db_conn] = db_conn
    client = TestClient(app)
    client.__enter__()
    yield SimpleNamespace(
        client=client,
        engine=engine,
        storage=storage,
        org=org,
        request_id=requests[0]["id"],
        admin=_token("ADMIN", None),
        company_admin=_token("ADMIN", org),
    )
    with engine.begin() as c:
        c.execute(text("DELETE FROM admin_audit_log WHERE organization_id = :o"), {"o": org})
        c.execute(text("DELETE FROM organization_settings WHERE organization_id = :o"), {"o": org})
        c.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
    engine.dispose()


def _audit(world) -> list[str]:
    with world.engine.begin() as c:
        rows = c.execute(
            text(
                "SELECT summary FROM admin_audit_log WHERE organization_id = :o ORDER BY occurred_at"
            ),
            {"o": world.org},
        )
        return [r.summary for r in rows]


def test_open_request_is_listed_with_its_company(world):
    resp = world.client.get("/admin/branding-requests", headers=world.admin)

    assert resp.status_code == 200
    mine = [r for r in resp.json() if r["organization_id"] == str(world.org)]
    assert len(mine) == 1
    assert mine[0]["organization_name"] == "Skyline Builders"
    assert mine[0]["status"] == "open"
    assert mine[0]["file_count"] == 2


def test_photos_are_served_by_position_and_a_lost_file_is_404(world):
    base = f"/admin/organizations/{world.org}/branding-requests/{world.request_id}/files"

    first = world.client.get(f"{base}/0", headers=world.admin)
    lost = world.client.get(f"{base}/1", headers=world.admin)
    beyond = world.client.get(f"{base}/2", headers=world.admin)
    other_company = world.client.get(
        f"/admin/organizations/{uuid.uuid4()}/branding-requests/{world.request_id}/files/0",
        headers=world.admin,
    )

    assert first.status_code == 200 and first.content == PHOTO
    assert first.headers["content-type"] == "image/jpeg"
    assert lost.status_code == 404 and lost.json()["detail"] == "File no longer available"
    assert beyond.status_code == 404 and other_company.status_code == 404


def test_letterhead_fields_contact_and_logo_are_saved_and_audited(world):
    url = f"/admin/organizations/{world.org}/branding"

    saved = world.client.put(
        url,
        headers=world.admin,
        json={"gstin": "27aapfu0939f1zv", "signatory_name": "Ravi", "address": " 12  MG Road "},
    )
    bad = world.client.put(url, headers=world.admin, json={"gstin": "nope"})
    logo = world.client.put(
        f"{url}/logo",
        headers=world.admin,
        json={"content_type": "image/png", "data_base64": base64.b64encode(PNG).decode()},
    )

    assert saved.status_code == 200
    letterhead = saved.json()["letterhead"]
    assert letterhead["gstin"] == "27AAPFU0939F1ZV"
    assert letterhead["address"] == "12 MG Road"
    assert bad.status_code == 422
    assert logo.status_code == 200 and logo.json()["letterhead"]["has_logo"] is True
    assert _audit(world) == [
        "Letterhead updated: address, gstin, signatory_name",
        "Letterhead logo uploaded",
    ]


def test_mark_done_hands_over_to_the_assistant_once(world):
    url = f"/admin/organizations/{world.org}/branding-requests/{world.request_id}/done"

    done = world.client.post(url, headers=world.admin)
    again = world.client.post(url, headers=world.admin)

    assert done.status_code == 200 and done.json()["status"] == "done"
    assert again.status_code == 409
    with world.engine.begin() as c:
        stored = c.execute(
            text(
                "SELECT value FROM organization_settings "
                "WHERE organization_id = :o AND key = 'branding_requests'"
            ),
            {"o": world.org},
        ).scalar_one()
    # What the assistant reads to tell the owner "your letterhead is set up".
    assert setup_questions.request_to_announce(stored)["id"] == world.request_id
    assert _audit(world) == ["Skyline Builders: branding request done"]


def test_a_company_admin_cannot_use_any_of_it(world):
    for method, path in (
        ("get", "/admin/branding-requests"),
        ("get", f"/admin/organizations/{world.org}/branding"),
        ("post", f"/admin/organizations/{world.org}/branding-requests/{world.request_id}/done"),
    ):
        resp = getattr(world.client, method)(path, headers=world.company_admin)
        assert resp.status_code == 403, path


def test_company_name_and_contact_are_edited_and_audited(world):
    """SA-03: rename the company and set its primary contact; only real
    changes are audited, with their before and after."""
    resp = world.client.patch(
        f"/admin/organizations/{world.org}/details",
        json={"name": "  Skyline   Builders Pvt Ltd ", "primary_contact": "Suresh 98765 43210"},
        headers=world.admin,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Skyline Builders Pvt Ltd"
    assert resp.json()["primary_contact"] == "Suresh 98765 43210"

    # Same values again: nothing changes, nothing is audited.
    again = world.client.patch(
        f"/admin/organizations/{world.org}/details",
        json={"name": "Skyline Builders Pvt Ltd"},
        headers=world.admin,
    )
    assert again.status_code == 200
    assert _audit(world) == ["Company details updated: name, primary_contact"]
    with world.engine.begin() as c:
        details = c.execute(
            text("SELECT details FROM admin_audit_log WHERE organization_id = :o"), {"o": world.org}
        ).scalar_one()
    assert details["changes"]["name"] == {
        "before": "Skyline Builders",
        "after": "Skyline Builders Pvt Ltd",
    }


def test_company_details_refuse_an_empty_name_and_strangers(world):
    empty = world.client.patch(
        f"/admin/organizations/{world.org}/details", json={"name": "   "}, headers=world.admin
    )
    missing = world.client.patch(
        f"/admin/organizations/{uuid.uuid4()}/details", json={"name": "X"}, headers=world.admin
    )
    company_admin = world.client.patch(
        f"/admin/organizations/{world.org}/details",
        json={"name": "Hijacked"},
        headers=world.company_admin,
    )
    assert (empty.status_code, missing.status_code, company_admin.status_code) == (422, 404, 403)
    assert _audit(world) == []
