"""Contract/integration tests for the narrow Expenses REST API.

Covers: idempotent RecordExpense (retried request with the same
Idempotency-Key returns the original outcome, not a second expense),
validation rejection, org isolation on read, and site/project authorization.

Requires a live Postgres reachable via Settings().postgres.dsn() — run with
`pytest -m integration`. Mirrors the fixture style of
test_materials_api_contract.py.
"""

from __future__ import annotations

import datetime
import uuid
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


@pytest.fixture
async def test_engine():
    settings = Settings()
    engine = create_async_engine(settings.postgres.dsn(), echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def clean_db(test_engine: AsyncEngine):
    async with test_engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM idempotency_keys WHERE command_type = 'record_expense'"))
        await conn.execute(sa.text("DELETE FROM expense_payments"))
        await conn.execute(sa.text("DELETE FROM expense_attachments"))
        await conn.execute(sa.text("DELETE FROM money_transactions"))
        await conn.execute(sa.text("DELETE FROM expenses"))
        await conn.execute(sa.text("DELETE FROM money_accounts"))
        await conn.execute(sa.text("DELETE FROM expense_categories"))
        await conn.execute(sa.text("DELETE FROM sites"))
        await conn.execute(sa.text("DELETE FROM projects"))
        await conn.execute(sa.text("DELETE FROM users"))
        await conn.execute(sa.text("DELETE FROM organizations"))
    yield


@pytest.fixture
async def client(test_engine: AsyncEngine, monkeypatch):
    # The module gate reads enabled modules through the app container's
    # Postgres, which is the in-memory fake under the test storage settings
    # (no `transaction`). Same patch as test_materials_api_contract.py.
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
    # /expenses and /finance sit behind the finance module, which is off by
    # default for a new company. These tests are about the endpoints, not the gate.
    monkeypatch.setattr(
        "mesiri.domains.shared.modules.org_settings.module_enabled", lambda module, stored: True
    )
    app = create_app()

    async def override_get_db_conn():
        async with test_engine.begin() as conn:
            yield conn

    app.dependency_overrides[get_db_conn] = override_get_db_conn
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as test_client:
        yield test_client


@pytest.fixture
async def test_org(test_engine: AsyncEngine, clean_db):
    org_id = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, deployment_type, db_route, status, "
                "created_at, updated_at) VALUES (:id, :name, 'local', 'default', 'active', now(), now())"
            ),
            {"id": org_id, "name": "Test Org"},
        )
    return org_id


async def _make_user(test_engine, org_id, role: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO users (id, organization_id, email, hashed_password, full_name, "
                "role, status, access_policy, created_at, updated_at) "
                "VALUES (:id, :org_id, :email, 'hash', 'Test User', :role, 'active', "
                "CAST(:policy AS jsonb), now(), now())"
            ),
            {
                "id": user_id,
                "org_id": org_id,
                "email": f"{uuid.uuid4().hex[:8]}@example.com",
                "role": role,
                "policy": '{"mode": "all_projects", "projects": []}',
            },
        )
    return user_id


def _token(user_id: uuid.UUID, org_id: uuid.UUID, role: str) -> str:
    return create_access_token(data={"sub": str(user_id), "org": str(org_id), "role": role})


async def _make_project(test_engine, org_id) -> uuid.UUID:
    project_id = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                "VALUES (:id, :org_id, 'Test Project', now(), now())"
            ),
            {"id": project_id, "org_id": org_id},
        )
    return project_id


async def _make_category(test_engine, org_id, user_id) -> uuid.UUID:
    category_id = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO expense_categories (id, organization_id, name, status, created_by) "
                "VALUES (:id, :org_id, 'materials', 'active', :user_id)"
            ),
            {"id": category_id, "org_id": org_id, "user_id": user_id},
        )
    return category_id


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_ctx(test_engine, test_org):
    user_id = await _make_user(test_engine, test_org, "admin")
    project_id = await _make_project(test_engine, test_org)
    category_id = await _make_category(test_engine, test_org, user_id)
    token = _token(user_id, test_org, "admin")
    return {
        "user_id": user_id,
        "project_id": project_id,
        "category_id": category_id,
        "token": token,
    }


def _body(ctx: dict, **overrides) -> dict:
    base = {
        "project_id": str(ctx["project_id"]),
        "category_id": str(ctx["category_id"]),
        "amount": "150.00",
        "occurred_date": datetime.date.today().isoformat(),
    }
    base.update(overrides)
    return base


async def test_record_expense_creates_confirmed_unpaid_expense(client, admin_ctx):
    resp = await client.post(
        "/expenses",
        json=_body(admin_ctx),
        headers={**_auth(admin_ctx["token"]), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 201, resp.text
    expense_id = resp.json()["id"]
    assert resp.json()["status"] == "succeeded"

    get_resp = await client.get(f"/expenses/{expense_id}", headers=_auth(admin_ctx["token"]))
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["workflow_status"] == "confirmed"
    assert body["payment_status"] == "unpaid"
    assert Decimal(body["amount"]) == Decimal("150.00")


async def test_retried_record_expense_with_same_key_does_not_double_post(client, admin_ctx):
    key = str(uuid.uuid4())
    first = await client.post(
        "/expenses", json=_body(admin_ctx), headers={**_auth(admin_ctx["token"]), "Idempotency-Key": key}
    )
    second = await client.post(
        "/expenses",
        json=_body(admin_ctx, amount="999.00"),  # different body, same key
        headers={**_auth(admin_ctx["token"]), "Idempotency-Key": key},
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["status"] == "already_executed"


async def test_non_uuid_idempotency_key_is_accepted_and_stays_idempotent(client, admin_ctx):
    """The Idempotency-Key header is client-supplied and never guaranteed to
    be a UUID (unlike Materials' CQRS path, whose idempotency_key IS a
    workflow_instance_id). The claim/replay logic and the workflow_instances
    phase-transition no-op (see PostgresExpenseExecutionRepository._transition)
    must both handle a plain non-UUID string without raising."""
    key = "order-42-not-a-uuid"
    first = await client.post(
        "/expenses",
        json=_body(admin_ctx),
        headers={**_auth(admin_ctx["token"]), "Idempotency-Key": key},
    )
    second = await client.post(
        "/expenses",
        json=_body(admin_ctx, amount="999.00"),
        headers={**_auth(admin_ctx["token"]), "Idempotency-Key": key},
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["status"] == "already_executed"


async def test_missing_idempotency_key_header_is_rejected(client, admin_ctx):
    resp = await client.post("/expenses", json=_body(admin_ctx), headers=_auth(admin_ctx["token"]))
    assert resp.status_code == 422


async def test_non_positive_amount_is_rejected(client, admin_ctx):
    resp = await client.post(
        "/expenses",
        json=_body(admin_ctx, amount="0"),
        headers={**_auth(admin_ctx["token"]), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 422


async def test_write_to_inaccessible_project_is_rejected(client, test_engine, test_org, admin_ctx):
    other_project_id = await _make_project(test_engine, test_org)
    user_id = await _make_user(test_engine, test_org, "site_engineer")
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE users SET access_policy = CAST(:policy AS jsonb) WHERE id = :id"
            ),
            {
                "id": user_id,
                "policy": f'{{"mode": "custom_projects", "projects": [{{"project_id": "{admin_ctx["project_id"]}", "site_ids": null}}]}}',
            },
        )
    token = _token(user_id, test_org, "site_engineer")

    resp = await client.post(
        "/expenses",
        json=_body(admin_ctx, project_id=str(other_project_id)),
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 403


async def test_cross_organization_read_is_rejected(client, test_engine, admin_ctx):
    resp = await client.post(
        "/expenses",
        json=_body(admin_ctx),
        headers={**_auth(admin_ctx["token"]), "Idempotency-Key": str(uuid.uuid4())},
    )
    expense_id = resp.json()["id"]

    other_org_id = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, deployment_type, db_route, status, "
                "created_at, updated_at) VALUES (:id, 'Other Org', 'local', 'default', 'active', now(), now())"
            ),
            {"id": other_org_id},
        )
    other_user_id = await _make_user(test_engine, other_org_id, "admin")
    other_token = _token(other_user_id, other_org_id, "admin")

    resp = await client.get(f"/expenses/{expense_id}", headers=_auth(other_token))
    assert resp.status_code == 404


async def _second_company_ctx(test_engine) -> dict:
    """A separate organization with its own admin, project and category."""
    org_id = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, deployment_type, db_route, status, "
                "created_at, updated_at) VALUES (:id, 'Company B', 'local', 'default', 'active', now(), now())"
            ),
            {"id": org_id},
        )
    user_id = await _make_user(test_engine, org_id, "admin")
    project_id = await _make_project(test_engine, org_id)
    category_id = await _make_category(test_engine, org_id, user_id)
    return {
        "org_id": org_id,
        "user_id": user_id,
        "project_id": project_id,
        "category_id": category_id,
        "token": _token(user_id, org_id, "admin"),
    }


async def test_idempotency_key_is_scoped_to_the_company(client, test_engine, admin_ctx):
    """Company B reusing company A's Idempotency-Key records B's own expense
    instead of being handed A's (the idempotency_keys table is shared)."""
    key = f"shared-{uuid.uuid4()}"
    a_first = await client.post(
        "/expenses", json=_body(admin_ctx), headers={**_auth(admin_ctx["token"]), "Idempotency-Key": key}
    )
    assert a_first.status_code == 201, a_first.text

    b_ctx = await _second_company_ctx(test_engine)
    b_resp = await client.post(
        "/expenses",
        json=_body(b_ctx, amount="75.00"),
        headers={**_auth(b_ctx["token"]), "Idempotency-Key": key},
    )
    assert b_resp.status_code == 201, b_resp.text
    assert b_resp.json()["status"] == "succeeded"
    assert b_resp.json()["id"] != a_first.json()["id"]
    b_get = await client.get(f"/expenses/{b_resp.json()['id']}", headers=_auth(b_ctx["token"]))
    assert b_get.status_code == 200
    assert Decimal(b_get.json()["amount"]) == Decimal("75.00")

    a_retry = await client.post(
        "/expenses", json=_body(admin_ctx), headers={**_auth(admin_ctx["token"]), "Idempotency-Key": key}
    )
    assert a_retry.status_code == 200
    assert a_retry.json()["status"] == "already_executed"
    assert a_retry.json()["id"] == a_first.json()["id"]


async def _two_cash_accounts(test_engine, org_id, user_id) -> tuple[uuid.UUID, uuid.UUID]:
    ids = (uuid.uuid4(), uuid.uuid4())
    async with test_engine.begin() as conn:
        for account_id, name in zip(ids, ("Office Cash", "Site Cash"), strict=True):
            await conn.execute(
                sa.text(
                    "INSERT INTO money_accounts (id, organization_id, name, account_type, "
                    "currency, opening_balance, opening_balance_date, status, created_by) "
                    "VALUES (:id, :org_id, :name, 'cash', 'INR', 5000.00, current_date, "
                    "'active', :user_id)"
                ),
                {"id": account_id, "org_id": org_id, "name": name, "user_id": user_id},
            )
    return ids


async def test_money_transfer_idempotency_key_is_scoped_to_the_company(
    client, test_engine, test_org, admin_ctx
):
    """Same guarantee on POST /finance/transfers, which shares the table."""
    key = f"shared-{uuid.uuid4()}"
    a_from, a_to = await _two_cash_accounts(test_engine, test_org, admin_ctx["user_id"])
    a_first = await client.post(
        "/finance/transfers",
        json={"from_account_id": str(a_from), "to_account_id": str(a_to), "amount": "100.00"},
        headers={**_auth(admin_ctx["token"]), "Idempotency-Key": key},
    )
    assert a_first.status_code == 201, a_first.text

    b_ctx = await _second_company_ctx(test_engine)
    b_from, b_to = await _two_cash_accounts(test_engine, b_ctx["org_id"], b_ctx["user_id"])
    b_resp = await client.post(
        "/finance/transfers",
        json={"from_account_id": str(b_from), "to_account_id": str(b_to), "amount": "60.00"},
        headers={**_auth(b_ctx["token"]), "Idempotency-Key": key},
    )
    assert b_resp.status_code == 201, b_resp.text
    assert b_resp.json()["id"] != a_first.json()["id"]
    async with test_engine.begin() as conn:
        b_rows = (
            await conn.execute(
                sa.text("SELECT count(*) FROM money_transactions WHERE organization_id = :org"),
                {"org": b_ctx["org_id"]},
            )
        ).scalar_one()
    assert b_rows > 0

    a_retry = await client.post(
        "/finance/transfers",
        json={"from_account_id": str(a_from), "to_account_id": str(a_to), "amount": "100.00"},
        headers={**_auth(admin_ctx["token"]), "Idempotency-Key": key},
    )
    assert a_retry.json()["id"] == a_first.json()["id"]
