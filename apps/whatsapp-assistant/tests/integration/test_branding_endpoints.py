"""Company branding (BE-20) and project client logo (BE-33) endpoints, on Postgres."""

from __future__ import annotations

import base64
import uuid
from types import SimpleNamespace

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.fixtures.db import build_sync_engine

from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY
from mesiri.domains.organizations.router import router as company_router
from mesiri.infrastructure.objectstorage.fake import FakeObjectStorage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from projects import router as projects_module
from projects.router import router as projects_router

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


class LinkingStorage(FakeObjectStorage):
    """In-memory storage that hands out http links, like R2 or local disk."""

    async def generate_presigned_url(self, key, *, expires_in_seconds=900, method="GET"):
        return f"https://files.test/{key}"


def _password() -> str:
    import os

    return os.environ.get("MESIRI_POSTGRES__PASSWORD", "mesiri_local_dev")


def _upload(data: bytes, content_type: str) -> dict:
    return {"content_type": content_type, "data_base64": base64.b64encode(data).decode()}


@pytest.fixture
def world():
    engine = build_sync_engine()
    org, other_org = uuid.uuid4(), uuid.uuid4()
    admin, engineer = uuid.uuid4(), uuid.uuid4()
    project, other_project = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as c:
        for oid, name in ((org, "Acme"), (other_org, "Other")):
            c.execute(
                text(
                    "INSERT INTO organizations (id, name, status, db_route, deployment_type, "
                    "address, phone, email) VALUES (:id, :n, 'active', 'shared', 'shared', "
                    "'12 MG Road, Pune', '+91 20 1234', 'office@acme.test')"
                ),
                {"id": oid, "n": name},
            )
        for uid, role in ((admin, "ADMIN"), (engineer, "SITE_ENGINEER")):
            c.execute(
                text(
                    "INSERT INTO users (id, full_name, organization_id, status, role, "
                    "hashed_password) VALUES (:id, :id, :o, 'active', :r, 'x')"
                ),
                {"id": uid, "o": org, "r": role},
            )
        for pid, oid in ((project, org), (other_project, other_org)):
            c.execute(
                text(
                    "INSERT INTO projects (id, organization_id, name, status, client) "
                    "VALUES (:id, :o, 'Tower', 'on_track', 'Client Co')"
                ),
                {"id": pid, "o": oid},
            )
    storage = LinkingStorage()
    app = FastAPI()
    app.state.container = SimpleNamespace(object_storage=storage)
    app.include_router(company_router)
    app.include_router(projects_router)

    async def db_conn():
        # One transaction per request, committed on success -- what the live
        # app's get_db_conn does.
        engine_ = create_async_engine(
            str(engine.url).replace("+psycopg", "+asyncpg").replace("***", _password())
        )
        async with engine_.begin() as conn:
            yield conn
        await engine_.dispose()

    app.dependency_overrides[get_db_conn] = db_conn
    # The projects router keeps a module-level pool; a pool bound to an
    # earlier test's event loop cannot be reused.
    projects_module._engine = None

    def token(uid, role, org_id=org):
        return {
            "Authorization": "Bearer "
            + jwt.encode(
                {"sub": str(uid), "org": str(org_id), "role": role}, SECRET_KEY, algorithm=ALGORITHM
            )
        }

    client = TestClient(app)
    client.__enter__()
    yield SimpleNamespace(
        client=client,
        storage=storage,
        engine=engine,
        org=org,
        project=project,
        other_project=other_project,
        admin=token(admin, "ADMIN"),
        engineer=token(engineer, "SITE_ENGINEER"),
        other_admin=token(uuid.uuid4(), "ADMIN", other_org),
    )
    with engine.begin() as c:
        c.execute(
            text("DELETE FROM projects WHERE id IN (:a, :b)"), {"a": project, "b": other_project}
        )
        c.execute(text("DELETE FROM users WHERE id IN (:a, :b)"), {"a": admin, "b": engineer})
        c.execute(
            text("DELETE FROM organization_settings WHERE organization_id IN (:a, :b)"),
            {"a": org, "b": other_org},
        )
        c.execute(
            text("DELETE FROM organizations WHERE id IN (:a, :b)"), {"a": org, "b": other_org}
        )
    engine.dispose()


def test_branding_starts_empty_with_company_details(world):
    resp = world.client.get("/company/branding", headers=world.admin)

    assert resp.status_code == 200
    body = resp.json()
    assert body["company_name"] == "Acme"
    assert body["address"] == "12 MG Road, Pune"
    assert body["has_logo"] is False and body["logo_url"] is None
    assert body["gstin"] is None


def test_branding_fields_are_saved_and_validated(world):
    ok = world.client.put(
        "/company/branding",
        headers=world.admin,
        json={"gstin": "27aapfu0939f1zv", "brand_color": "#1f6feb", "signatory_name": "R. Rao"},
    )
    partial = world.client.put(
        "/company/branding", headers=world.admin, json={"signatory_name": "S. Iyer"}
    )
    bad = world.client.put("/company/branding", headers=world.admin, json={"gstin": "nope"})
    sneaky = world.client.put(
        "/company/branding", headers=world.admin, json={"logo_object_key": "org/x/y.png"}
    )

    assert ok.status_code == 200 and ok.json()["gstin"] == "27AAPFU0939F1ZV"
    assert partial.json()["brand_color"] == "#1F6FEB"  # untouched fields stay
    assert partial.json()["signatory_name"] == "S. Iyer"
    assert bad.status_code == 422 and sneaky.status_code == 422


def test_only_admins_edit_branding(world):
    assert world.client.get("/company/branding", headers=world.engineer).status_code == 403
    assert world.client.put("/company/branding", headers=world.engineer, json={}).status_code == 403


def test_generic_settings_api_refuses_branding(world):
    resp = world.client.put(
        "/company/settings",
        headers=world.admin,
        json={"key": "branding", "value": {"logo_object_key": "org/other/secret.png"}},
    )
    assert resp.status_code == 422


def test_company_logo_upload_replace_and_remove(world):
    first = world.client.put(
        "/company/branding/logo", headers=world.admin, json=_upload(PNG, "image/png")
    )
    first_key = first.json()["logo_url"].removeprefix("https://files.test/")
    second = world.client.put(
        "/company/branding/logo", headers=world.admin, json=_upload(JPEG, "image/jpeg")
    )
    second_key = second.json()["logo_url"].removeprefix("https://files.test/")

    assert first.status_code == 200 and first.json()["has_logo"] is True
    assert first_key.startswith(f"org/{world.org}/branding/logo-") and first_key.endswith(".png")
    assert second_key.endswith(".jpg")
    assert first_key not in world.storage._store  # replaced file removed  # noqa: SLF001
    assert world.storage._store[second_key][0] == JPEG  # noqa: SLF001

    removed = world.client.delete("/company/branding/logo", headers=world.admin)
    assert removed.json()["has_logo"] is False
    assert second_key not in world.storage._store  # noqa: SLF001


def test_bad_logo_uploads_are_refused(world):
    svg = world.client.put(
        "/company/branding/logo", headers=world.admin, json=_upload(b"<svg/>", "image/svg+xml")
    )
    lying = world.client.put(
        "/company/branding/logo", headers=world.admin, json=_upload(JPEG, "image/png")
    )
    garbage = world.client.put(
        "/company/branding/logo",
        headers=world.admin,
        json={"content_type": "image/png", "data_base64": "%%%"},
    )
    assert {svg.status_code, lying.status_code, garbage.status_code} == {422}
    assert world.storage._store == {}  # noqa: SLF001


def test_client_logo_lifecycle(world):
    path = f"/projects/{world.project}/client-logo"

    up = world.client.put(path, headers=world.admin, json=_upload(PNG, "image/png"))
    key = up.json()["url"].removeprefix("https://files.test/")
    seen = world.client.get(path, headers=world.admin)
    project = world.client.get(f"/projects/{world.project}", headers=world.admin)

    assert up.status_code == 200 and up.json()["hasClientLogo"] is True
    assert key.startswith(f"org/{world.org}/projects/{world.project}/client-logo-")
    assert seen.json()["url"] == up.json()["url"]
    assert project.json()["hasClientLogo"] is True

    gone = world.client.delete(path, headers=world.admin)
    assert gone.json() == {"hasClientLogo": False, "url": None}
    assert key not in world.storage._store  # noqa: SLF001


def test_client_logo_is_admin_only_and_tenant_scoped(world):
    path = f"/projects/{world.project}/client-logo"
    upload = _upload(PNG, "image/png")

    assert world.client.put(path, headers=world.engineer, json=upload).status_code == 403
    assert world.client.put(path, headers=world.other_admin, json=upload).status_code == 404
    other = f"/projects/{world.other_project}/client-logo"
    assert world.client.put(other, headers=world.admin, json=upload).status_code == 404
    assert world.client.get(other, headers=world.admin).status_code == 404
    assert world.storage._store == {}  # noqa: SLF001
