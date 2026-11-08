"""Contract test for the drawing reader's route (DR-04): POST /drawings/read with a PDF body; nothing stored."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import create_access_token
from mesiri.http.app import create_app
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration


def _pdf() -> bytes:
    from fpdf import FPDF

    pdf = FPDF(unit="pt", format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", size=6)
    for x, y, text in [(340, 300, "ROOM-1"), (334, 307, "1740 x 590"), (336, 314, "1217 Sq.ft"),
                       (340, 420, "ROOM-2"), (334, 427, "1740 x 650"), (336, 434, "1217 Sq.ft"),
                       (409, 722, "DWG.TITLE:"), (469, 734, "GROUND FLOOR PLAN"), (458, 771, "1:100")]:
        pdf.text(x, y, text)
    return bytes(pdf.output())


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def clean_db(test_engine: AsyncEngine):
    yield  # the route stores nothing: nothing to clean


@pytest.fixture
async def client(test_engine: AsyncEngine, monkeypatch, clean_db):
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    app = create_app()

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


async def _org(engine) -> uuid.UUID:
    org_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
                "VALUES (:id, 'Drawings Org', 'local', 'default', 'active', now(), now())"
            ),
            {"id": org_id},
        )
    return org_id


async def _user(engine, org_id, role: str, policy: str = '{"mode": "all_projects", "projects": []}') -> str:
    user_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, "
                "access_policy, created_at, updated_at) VALUES (:id, :org, :email, 'hash', 'T', :role, "
                "'active', CAST(:policy AS jsonb), now(), now())"
            ),
            {"id": user_id, "org": org_id, "email": f"{uuid.uuid4().hex[:8]}@example.com", "role": role, "policy": policy},
        )
    return create_access_token(data={"sub": str(user_id), "org": str(org_id), "role": role})


async def _project(engine, org_id) -> uuid.UUID:
    project_id, site_id = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                "VALUES (:id, :org, 'Villa Kakkanad', now(), now())"
            ),
            {"id": project_id, "org": org_id},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO sites (id, project_id, organization_id, name, status, created_at, updated_at) "
                "VALUES (:id, :p, :org, 'Main building', 'active', now(), now())"
            ),
            {"id": site_id, "p": project_id, "org": org_id},
        )
    return project_id


async def _h(engine, org, role: str) -> dict:
    token = await _user(engine, org, role)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/pdf", "X-File-Name": "set.pdf"}


async def test_read_a_drawing_pdf(client, test_engine):
    org = await _org(test_engine)
    r = await client.post("/drawings/read", content=_pdf(), headers=await _h(test_engine, org, "admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["file_name"] == "set.pdf" and body["pages"] == 1 and body["floors"] == ["Ground floor"]
    assert body["checks"][0]["kind"] == "area_label"


async def test_refuses_what_is_not_a_pdf_and_roles_that_do_not_plan(client, test_engine):
    org = await _org(test_engine)
    admin = await _h(test_engine, org, "admin")
    assert (await client.post("/drawings/read", content=b"hello", headers=admin)).status_code == 422
    assert (await client.post("/drawings/read", content=b"%PDF-1.4 broken", headers=admin)).status_code == 422
    engineer = await _h(test_engine, org, "site_engineer")
    assert (await client.post("/drawings/read", content=_pdf(), headers=engineer)).status_code == 403
