"""NXT-12 contract: the Tally export from real expenses and payments, and who may take the books out.

Requires a live Postgres reachable via Settings().postgres.dsn() -- run with `pytest -m integration`."""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from decimal import Decimal

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mesiri.bootstrap.settings import Settings
from mesiri.domains.identity.auth_service import create_access_token
from mesiri.http.app import create_app
from mesiri.infrastructure.postgres.dependency import get_db_conn

pytestmark = pytest.mark.integration
_ALL = '{"mode": "all_projects", "projects": []}'


@pytest.fixture
async def test_engine():
    engine = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(test_engine: AsyncEngine, monkeypatch):
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    app = create_app()

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


async def _run(engine, sql: str, **params):
    async with engine.begin() as conn:
        return await conn.execute(sa.text(sql), params)


async def _user(engine, org, role: str) -> tuple[uuid.UUID, str]:
    user_id = uuid.uuid4()
    await _run(engine,
               "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, access_policy, "
               "created_at, updated_at) VALUES (:id, :org, :e, 'hash', 'Ravi', :role, 'active', CAST(:p AS jsonb), now(), now())",
               id=user_id, org=org, e=f"{uuid.uuid4().hex[:8]}@example.com", role=role, p=_ALL)
    return user_id, create_access_token(data={"sub": str(user_id), "org": str(org), "role": role})


async def test_the_months_expenses_and_payments_become_balanced_tally_vouchers(client, test_engine):
    org, project, account, vendor, category = (uuid.uuid4() for _ in range(5))
    await _run(test_engine, "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
               "VALUES (:id, 'Tally Org', 'local', 'default', 'active', now(), now())", id=org)
    admin_id, admin = await _user(test_engine, org, "admin")
    await _run(test_engine, "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
               "VALUES (:id, :org, 'Villa', now(), now())", id=project, org=org)
    await _run(test_engine, "INSERT INTO expense_categories (id, organization_id, name, code, created_by) "
               "VALUES (:id, :org, 'Materials', 'MAT', :u)", id=category, org=org, u=admin_id)
    await _run(test_engine, "INSERT INTO vendors (id, organization_id, name, created_by) VALUES (:id, :org, 'Malabar', :u)",
               id=vendor, org=org, u=admin_id)
    await _run(test_engine, "INSERT INTO money_accounts (id, organization_id, account_type, name, opening_balance, opening_balance_date, created_by) "
               "VALUES (:id, :org, 'bank', 'SBI current', 0, current_date - 30, :u)", id=account, org=org, u=admin_id)
    bill = uuid.uuid4()
    await _run(test_engine, "INSERT INTO expenses (id, organization_id, project_id, amount, occurred_date, created_by, "
               "category_id, vendor_id, workflow_status, tax_amount, is_tax_inclusive) VALUES (:id, :org, :p, 11800, "
               "current_date, :u, :c, :v, 'confirmed', 1800, true)", id=bill, org=org, p=project, u=admin_id, c=category,
               v=vendor)
    await _run(test_engine, "INSERT INTO expenses (id, organization_id, project_id, amount, occurred_date, created_by, "
               "category_id, workflow_status) VALUES (gen_random_uuid(), :org, :p, 999, current_date, :u, :c, 'draft')",
               org=org, p=project, u=admin_id, c=category)  # not confirmed: not exported
    await _run(test_engine, "INSERT INTO expense_payments (id, organization_id, expense_id, account_id, amount, paid_date, "
               "status, created_by) VALUES (gen_random_uuid(), :org, :e, :a, 11800, current_date, 'confirmed', :u)",
               org=org, e=bill, a=account, u=admin_id)
    h = {"Authorization": f"Bearer {admin}"}
    summary = (await client.get("/finance/tally/summary", headers=h)).json()
    assert (summary["journals"], summary["payments"], summary["gst_split"]) == (1, 1, 1)
    r = await client.get("/finance/tally/export", headers=h)
    assert r.status_code == 200 and r.headers["content-disposition"].startswith('attachment; filename="mesiri-tally-')
    root = ET.fromstring(r.text)
    vouchers = list(root.iter("VOUCHER"))
    assert [v.get("VCHTYPE") for v in vouchers] == ["Journal", "Payment"]
    for v in vouchers:  # every voucher balances
        assert sum(Decimal(e.findtext("AMOUNT")) for e in v.findall("ALLLEDGERENTRIES.LIST")) == 0
    assert root.findtext(".//SVCURRENTCOMPANY") == "Tally Org"

    _, pm = await _user(test_engine, org, "PROJECT_MANAGER")
    assert (await client.get("/finance/tally/export", headers={"Authorization": f"Bearer {pm}"})).status_code == 403
    assert (await client.get("/finance/tally/export?date_from=2026-01-01&date_to=2027-06-01", headers=h)).status_code == 422
    await _run(test_engine, "DELETE FROM organizations WHERE id = :id", id=org)
