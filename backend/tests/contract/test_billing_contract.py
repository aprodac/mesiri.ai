"""Contract tests for client billing (NXT-01 clients and contracts, NXT-02 RA bills).

Requires a live Postgres reachable via Settings().postgres.dsn() -- run with
`pytest -m integration`. Fixtures mirror test_materials_api_contract.py.
"""

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


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def clean_db(test_engine: AsyncEngine):
    yield


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
                "VALUES (:id, 'Billing Org', 'local', 'default', 'active', now(), now())"
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


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def ctx(test_engine):
    org = await _org(test_engine)
    return {"org": org, "project": await _project(test_engine, org), "admin": await _user(test_engine, org, "admin")}


async def _section(client, ctx, name="Plastering", **extra) -> dict:
    r = await client.post(f"/projects/{ctx['project']}/boq/sections", json={"name": name, **extra}, headers=_h(ctx["admin"]))
    assert r.status_code == 201, r.text
    return r.json()


async def _add_line(client, ctx, section_id, **body) -> dict:
    r = await client.post(
        f"/projects/{ctx['project']}/boq/sections/{section_id}/lines", json=body, headers=_h(ctx["admin"])
    )
    assert r.status_code == 201, r.text


async def test_contract_terms_with_a_new_client_then_an_existing_one(client, ctx, test_engine):
    url, h = f"/projects/{ctx['project']}/contract", _h(ctx["admin"])
    r = (await client.get(url, headers=h)).json()
    assert r["contract"] is None and r["project"]["name"] == "Villa Kakkanad"

    terms = {"contract_value": "8500000", "retention_pct": "5", "mobilisation_advance": "850000",
             "advance_recovery_pct": "10", "gst_pct": "18", "tds_pct": "2", "defect_liability_months": 12,
             "signed_on": "2026-11-01", "contract_no": "KV/2026/14"}
    r = await client.put(url, json={**terms, "new_client": {"name": "Mr. Thomas", "gstin": "32abcde1234f1z5"}}, headers=h)
    assert r.status_code == 200, r.text
    c = r.json()["contract"]
    assert c["client_name"] == "Mr. Thomas" and c["contract_value"] == "8500000.00" and c["retention_pct"] == "5.00"
    async with test_engine.begin() as conn:
        shown = (await conn.execute(sa.text("SELECT client FROM projects WHERE id = :p"), {"p": ctx["project"]})).scalar()
    assert shown == "Mr. Thomas"  # the name shown across the app follows the contract's client

    clients = (await client.get("/billing/clients", headers=h)).json()
    assert [(x["name"], x["gstin"], [p["contract_value"] for p in x["projects"]]) for x in clients] == [
        ("Mr. Thomas", "32ABCDE1234F1Z5", ["8500000.00"])]
    # The same name again is refused; picking the saved client works; terms not sent become empty.
    again = await client.put(url, json={"new_client": {"name": "mr. thomas"}}, headers=h)
    assert again.status_code == 409
    r = (await client.put(url, json={"client_id": clients[0]["id"], "contract_value": "9000000"}, headers=h)).json()
    assert r["contract"]["contract_value"] == "9000000.00" and r["contract"]["retention_pct"] is None


async def test_contract_validation_and_who_may_see_it(client, ctx, test_engine):
    url, h = f"/projects/{ctx['project']}/contract", _h(ctx["admin"])
    for body in ({"retention_pct": "101"}, {"contract_value": "-1"}, {"new_client": {"name": "X", "gstin": "123"}},
                 {"contract_value": "100", "mobilisation_advance": "200"}, {"client_id": str(uuid.uuid4())}):
        assert (await client.put(url, json=body, headers=h)).status_code == 422, body
    for role, code in (("finance", 200), ("project_manager", 403), ("site_engineer", 403)):
        token = await _user(test_engine, ctx["org"], role)
        assert (await client.get(url, headers=_h(token))).status_code == code, role
        assert (await client.get("/billing/clients", headers=_h(token))).status_code == code, role
    assert (await client.get(f"/projects/{uuid.uuid4()}/contract", headers=h)).status_code == 404


async def test_client_details_change_and_names_stay_unique(client, ctx):
    h = _h(ctx["admin"])
    a = (await client.post("/billing/clients", json={"name": "Abdullakutty", "phone": "98470 00000"}, headers=h)).json()
    await client.post("/billing/clients", json={"name": "Kaleido"}, headers=h)
    r = await client.patch(f"/billing/clients/{a['id']}", json={"name": "Kaleido"}, headers=h)
    assert r.status_code == 409
    r = await client.patch(f"/billing/clients/{a['id']}", json={"address": "Kondotty"}, headers=h)
    assert r.json()["address"] == "Kondotty" and r.json()["phone"] == "98470 00000"


async def test_project_start_lists_the_contract_step_without_money(client, ctx):
    h = _h(ctx["admin"])
    steps = (await client.get(f"/projects/{ctx['project']}/start", headers=h)).json()["steps"]
    step = next(s for s in steps if s["key"] == "contract")
    assert step["done"] is False and [s["key"] for s in steps][:2] == ["dates", "contract"]
    await client.put(f"/projects/{ctx['project']}/contract", json={"contract_value": "100"}, headers=h)
    step = next(s for s in (await client.get(f"/projects/{ctx['project']}/start", headers=h)).json()["steps"]
                if s["key"] == "contract")
    assert step["done"] is True and "100" not in step["detail"]
