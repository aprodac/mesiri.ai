"""Contract/integration tests for the dashboard Materials API.

Covers: catalog CRUD + org isolation, Stock Unit enforcement, valid/invalid
Inflow & Outflow writes (direction/reason enforcement, quantity>0,
site-must-belong-to-project, inaccessible-project rejection), inventory
derivation from the material_movements ledger (including negative stock),
and correction/reversal preserving the original movement.

Requires a live Postgres reachable via Settings().postgres.dsn() — run with
`pytest -m integration`. Mirrors the fixture style of
test_projects_api_contract.py.
"""

from __future__ import annotations

import asyncio
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
        await conn.execute(sa.text("DELETE FROM material_movements"))
        # A correction row points at the row it corrects, across the two tables.
        await conn.execute(sa.text("UPDATE material_usage SET reverses_movement_id = NULL"))
        await conn.execute(sa.text("UPDATE material_receipts SET reverses_movement_id = NULL"))
        await conn.execute(sa.text("DELETE FROM material_receipts"))
        await conn.execute(sa.text("DELETE FROM material_usage"))
        await conn.execute(sa.text("DELETE FROM materials_catalog"))
        await conn.execute(sa.text("DELETE FROM expense_payments"))
        await conn.execute(sa.text("DELETE FROM expense_attachments"))
        await conn.execute(sa.text("DELETE FROM budget_allocations"))
        await conn.execute(sa.text("DELETE FROM budgets"))
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
    # (no `transaction`). Every test org has the default modules, so read
    # those, as a bare app does.
    monkeypatch.setattr("mesiri.domains.shared.modules._database_for", lambda request: None)
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


async def _make_site(test_engine, org_id, project_id) -> uuid.UUID:
    site_id = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO sites (id, project_id, organization_id, name, status, "
                "created_at, updated_at) VALUES (:id, :project_id, :org_id, 'Test Site', "
                "'active', now(), now())"
            ),
            {"id": site_id, "project_id": project_id, "org_id": org_id},
        )
    return site_id


@pytest.fixture
async def admin_ctx(test_engine, test_org):
    user_id = await _make_user(test_engine, test_org, "admin")
    project_id = await _make_project(test_engine, test_org)
    site_id = await _make_site(test_engine, test_org, project_id)
    token = _token(user_id, test_org, "admin")
    return {"user_id": user_id, "project_id": project_id, "site_id": site_id, "token": token}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _bags_unit_id(client, token: str) -> str:
    resp = await client.get("/materials/units-of-measure", headers=_auth(token))
    assert resp.status_code == 200
    units = {u["code"]: u["id"] for u in resp.json()["items"]}
    return units["bags"]


async def _tons_unit_id(client, token: str) -> str:
    resp = await client.get("/materials/units-of-measure", headers=_auth(token))
    assert resp.status_code == 200
    units = {u["code"]: u["id"] for u in resp.json()["items"]}
    return units["tons"]


async def _make_material(client, token: str, name: str, unit_id: str) -> str:
    resp = await client.post(
        "/materials",
        json={"name": name, "default_unit_id": unit_id},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_create_material_and_org_isolation(client, test_engine, test_org, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    resp = await client.post(
        "/materials",
        json={"name": "Cement", "default_unit_id": bags_id},
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Cement"

    other_org = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, deployment_type, db_route, status, "
                "created_at, updated_at) VALUES (:id, 'Other Org', 'local', 'default', 'active', now(), now())"
            ),
            {"id": other_org},
        )
    other_user = await _make_user(test_engine, other_org, "admin")
    other_token = _token(other_user, other_org, "admin")

    resp = await client.get("/materials", headers=_auth(other_token))
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_duplicate_material_name_rejected(client, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    await client.post(
        "/materials", json={"name": "Sand", "default_unit_id": bags_id}, headers=_auth(admin_ctx["token"])
    )
    resp = await client.post(
        "/materials", json={"name": "Sand", "default_unit_id": bags_id}, headers=_auth(admin_ctx["token"])
    )
    assert resp.status_code == 409


async def test_create_material_with_unknown_unit_rejected(client, admin_ctx):
    resp = await client.post(
        "/materials",
        json={"name": "Gravel", "default_unit_id": str(uuid.uuid4())},
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 422


async def test_delete_unused_material_removes_catalog_entry(client, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Delete Me", bags_id)

    resp = await client.delete(f"/materials/{material_id}", headers=_auth(admin_ctx["token"]))
    assert resp.status_code == 204

    resp = await client.get("/materials", headers=_auth(admin_ctx["token"]))
    assert resp.status_code == 200
    assert all(item["id"] != material_id for item in resp.json()["items"])


async def test_delete_material_with_movements_rejected(client, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Used Cement", bags_id)
    body = {
        "project_id": str(admin_ctx["project_id"]),
        "site_id": str(admin_ctx["site_id"]),
        "material_id": material_id,
        "unit_id": bags_id,
        "quantity": "100",
        "movement_reason": "RECEIVED",
        "occurred_date": str(datetime.date.today()),
    }
    resp = await client.post("/materials/inflows", json=body, headers=_auth(admin_ctx["token"]))
    assert resp.status_code == 201

    resp = await client.delete(f"/materials/{material_id}", headers=_auth(admin_ctx["token"]))
    assert resp.status_code == 409
    assert "Deactivate it instead" in resp.json()["detail"]

    resp = await client.get("/materials", headers=_auth(admin_ctx["token"]))
    assert resp.status_code == 200
    assert any(item["id"] == material_id for item in resp.json()["items"])


async def test_valid_inflow_then_outflow_derives_inventory(client, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement", bags_id)

    body = {
        "project_id": str(admin_ctx["project_id"]),
        "site_id": str(admin_ctx["site_id"]),
        "material_id": material_id,
        "unit_id": bags_id,
        "quantity": "100",
        "movement_reason": "RECEIVED",
        "occurred_date": str(datetime.date.today()),
    }
    resp = await client.post("/materials/inflows", json=body, headers=_auth(admin_ctx["token"]))
    assert resp.status_code == 201

    out_body = {**body, "quantity": "30", "movement_reason": "CONSUMED"}
    resp = await client.post(
        "/materials/outflows", json=out_body, headers=_auth(admin_ctx["token"])
    )
    assert resp.status_code == 201

    resp = await client.get(
        "/materials/inventory",
        params={"project_id": str(admin_ctx["project_id"])},
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["current_stock"] == "70.00"
    assert rows[0]["stock_state"] == "AVAILABLE"


async def test_outflow_with_unit_mismatched_to_stock_unit_rejected(client, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    tons_id = await _tons_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Rebar", tons_id)

    out_body = {
        "project_id": str(admin_ctx["project_id"]),
        "site_id": str(admin_ctx["site_id"]),
        "material_id": material_id,
        "unit_id": bags_id,  # Rebar's Stock Unit is tons, not bags
        "quantity": "10",
        "movement_reason": "CONSUMED",
        "occurred_date": str(datetime.date.today()),
    }
    resp = await client.post(
        "/materials/outflows", json=out_body, headers=_auth(admin_ctx["token"])
    )
    assert resp.status_code == 422


async def test_outflow_exceeding_stock_surfaces_negative(client, admin_ctx):
    tons_id = await _tons_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Rebar", tons_id)

    out_body = {
        "project_id": str(admin_ctx["project_id"]),
        "site_id": str(admin_ctx["site_id"]),
        "material_id": material_id,
        "unit_id": tons_id,
        "quantity": "10",
        "movement_reason": "CONSUMED",
        "occurred_date": str(datetime.date.today()),
    }
    resp = await client.post(
        "/materials/outflows", json=out_body, headers=_auth(admin_ctx["token"])
    )
    assert resp.status_code == 201

    resp = await client.get(
        "/materials/inventory",
        params={"project_id": str(admin_ctx["project_id"])},
        headers=_auth(admin_ctx["token"]),
    )
    rows = resp.json()
    assert rows[0]["stock_state"] == "NEGATIVE_STOCK"
    assert rows[0]["current_stock"] == "-10.00"


async def test_unknown_material_id_rejected(client, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    body = {
        "project_id": str(admin_ctx["project_id"]),
        "site_id": str(admin_ctx["site_id"]),
        "material_id": str(uuid.uuid4()),
        "unit_id": bags_id,
        "quantity": "10",
        "movement_reason": "RECEIVED",
        "occurred_date": str(datetime.date.today()),
    }
    resp = await client.post("/materials/inflows", json=body, headers=_auth(admin_ctx["token"]))
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "endpoint,reason",
    [("/materials/inflows", "CONSUMED"), ("/materials/outflows", "RECEIVED")],
)
async def test_invalid_direction_reason_combo_rejected(client, admin_ctx, endpoint, reason):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement", bags_id)
    body = {
        "project_id": str(admin_ctx["project_id"]),
        "site_id": str(admin_ctx["site_id"]),
        "material_id": material_id,
        "unit_id": bags_id,
        "quantity": "10",
        "movement_reason": reason,
        "occurred_date": str(datetime.date.today()),
    }
    resp = await client.post(endpoint, json=body, headers=_auth(admin_ctx["token"]))
    assert resp.status_code == 422


async def test_non_positive_quantity_rejected(client, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement", bags_id)
    body = {
        "project_id": str(admin_ctx["project_id"]),
        "material_id": material_id,
        "unit_id": bags_id,
        "quantity": "0",
        "occurred_date": str(datetime.date.today()),
    }
    resp = await client.post("/materials/inflows", json=body, headers=_auth(admin_ctx["token"]))
    assert resp.status_code == 422


async def test_site_not_in_project_rejected(client, test_engine, test_org, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement", bags_id)
    other_project = await _make_project(test_engine, test_org)
    foreign_site = await _make_site(test_engine, test_org, other_project)
    body = {
        "project_id": str(admin_ctx["project_id"]),
        "site_id": str(foreign_site),
        "material_id": material_id,
        "unit_id": bags_id,
        "quantity": "10",
        "occurred_date": str(datetime.date.today()),
    }
    resp = await client.post("/materials/inflows", json=body, headers=_auth(admin_ctx["token"]))
    assert resp.status_code == 422


async def test_inaccessible_project_rejected(client, test_engine, test_org, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement", bags_id)
    scoped_user = await _make_user(test_engine, test_org, "site_engineer")
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE users SET access_policy = CAST(:p AS jsonb) WHERE id = :id"),
            {"p": '{"mode": "custom_projects", "projects": []}', "id": scoped_user},
        )
    token = _token(scoped_user, test_org, "site_engineer")
    other_project = uuid.uuid4()
    body = {
        "project_id": str(other_project),
        "material_id": material_id,
        "unit_id": bags_id,
        "quantity": "10",
        "occurred_date": str(datetime.date.today()),
    }
    resp = await client.post("/materials/inflows", json=body, headers=_auth(token))
    assert resp.status_code == 403


async def test_adjustment_reason_forbidden_for_non_elevated_role(
    client, test_engine, test_org, admin_ctx
):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement", bags_id)
    site_engineer = await _make_user(test_engine, test_org, "site_engineer")
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE users SET access_policy = CAST(:p AS jsonb) WHERE id = :id"),
            {"p": '{"mode": "all_projects", "projects": []}', "id": site_engineer},
        )
    token = _token(site_engineer, test_org, "site_engineer")
    body = {
        "project_id": str(admin_ctx["project_id"]),
        "material_id": material_id,
        "unit_id": bags_id,
        "quantity": "10",
        "movement_reason": "ADJUSTMENT_IN",
        "occurred_date": str(datetime.date.today()),
    }
    resp = await client.post("/materials/inflows", json=body, headers=_auth(token))
    assert resp.status_code == 403


async def test_reversal_creates_offsetting_movement_and_preserves_original(client, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement", bags_id)
    body = {
        "project_id": str(admin_ctx["project_id"]),
        "site_id": str(admin_ctx["site_id"]),
        "material_id": material_id,
        "unit_id": bags_id,
        "quantity": "100",
        "movement_reason": "RECEIVED",
        "occurred_date": str(datetime.date.today()),
    }
    resp = await client.post("/materials/inflows", json=body, headers=_auth(admin_ctx["token"]))
    receipt_id = resp.json()["id"]

    resp = await client.post(
        f"/materials/inflows/{receipt_id}/reverse",
        json={"reason_note": "wrong quantity"},
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 201

    original = await client.get(
        f"/materials/inflows/{receipt_id}", headers=_auth(admin_ctx["token"])
    )
    assert original.status_code == 200
    assert original.json()["quantity"] == "100.00"
    assert original.json()["movement_reason"] == "RECEIVED"

    resp = await client.get(
        "/materials/inventory",
        params={"project_id": str(admin_ctx["project_id"])},
        headers=_auth(admin_ctx["token"]),
    )
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["current_stock"] == "0.00"
    assert rows[0]["stock_state"] == "OUT_OF_STOCK"


async def test_ledger_running_balance(client, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement", bags_id)

    for qty, endpoint, reason in [
        ("50", "/materials/inflows", "RECEIVED"),
        ("20", "/materials/outflows", "CONSUMED"),
        ("10", "/materials/inflows", "RECEIVED"),
    ]:
        body = {
            "project_id": str(admin_ctx["project_id"]),
            "site_id": str(admin_ctx["site_id"]),
            "material_id": material_id,
            "unit_id": bags_id,
            "quantity": qty,
            "movement_reason": reason,
            "occurred_date": str(datetime.date.today()),
        }
        await client.post(endpoint, json=body, headers=_auth(admin_ctx["token"]))

    resp = await client.get(
        f"/materials/ledger/{admin_ctx['site_id']}/{material_id}", headers=_auth(admin_ctx["token"])
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 3
    assert payload["current_balance"] == "40.00"


async def test_rest_path_unique_constraint_prevents_duplicate_movement(
    test_engine: AsyncEngine,
    admin_ctx,
):
    """The REST write path (router.py's create_inflow/create_outflow) has no
    idempotency_keys claim like the CQRS path -- its only guard against a
    retried POST double-posting into the ledger is migration 0310's
    UNIQUE(source_type, source_id, movement_type) constraint on
    material_movements. This test proves that constraint actually fires at the
    DB level: a second movement insert with the same (source_type, source_id,
    movement_type) triple must raise IntegrityError rather than silently
    landing a duplicate row.

    The realistic way the constraint bites: a retried inflow POST reuses the
    same receipt row_id (e.g. a client retrying with a fixed request id, or a
    connection-level redelivery). The router generates row_id per request, so
    the HTTP surface alone can't reproduce it -- this test seeds the first
    movement directly and then attempts the duplicate.
    """
    from sqlalchemy.exc import IntegrityError

    async with test_engine.connect() as conn:
        org_id = (
            await conn.execute(
                sa.text("SELECT organization_id FROM users WHERE id = :id"),
                {"id": admin_ctx["user_id"]},
            )
        ).scalar_one()
        bags_id = (
            await conn.execute(sa.text("SELECT id FROM units_of_measure WHERE code = 'bags'"))
        ).scalar_one()

    material_id = uuid.uuid4()
    receipt_id = uuid.uuid4()

    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO materials_catalog "
                "(id, organization_id, name, default_unit_id, is_active, created_by) "
                "VALUES (:id, :org_id, 'IdempotencyTestMat', :unit_id, true, :user_id)"
            ),
            {
                "id": material_id,
                "org_id": org_id,
                "unit_id": bags_id,
                "user_id": admin_ctx["user_id"],
            },
        )
        await conn.execute(
            sa.text(
                "INSERT INTO material_receipts "
                "(id, organization_id, project_id, site_id, material_name, quantity, unit, "
                "unit_id, material_id, occurred_date, occurred_date_source, source, "
                "movement_reason, created_by) "
                "VALUES (:id, :org_id, :project_id, :site_id, 'IdempotencyTestMat', 10, 'bags', "
                ":unit_id, :material_id, :occurred_date, 'reported', 'web', 'RECEIVED', :user_id)"
            ),
            {
                "id": receipt_id,
                "org_id": org_id,
                "project_id": admin_ctx["project_id"],
                "site_id": admin_ctx["site_id"],
                "unit_id": bags_id,
                "material_id": material_id,
                "occurred_date": datetime.date.today(),
                "user_id": admin_ctx["user_id"],
            },
        )
        await conn.execute(
            sa.text(
                "INSERT INTO material_movements "
                "(id, organization_id, project_id, site_id, material_id, unit_id, movement_type, "
                "quantity, occurred_at, source_type, source_id, recorded_by_user_id, created_at) "
                "VALUES (gen_random_uuid(), :org_id, :project_id, :site_id, :material_id, :unit_id, "
                "'RECEIPT', 10, now(), 'material_receipt', :source_id, :user_id, now())"
            ),
            {
                "org_id": org_id,
                "project_id": admin_ctx["project_id"],
                "site_id": admin_ctx["site_id"],
                "material_id": material_id,
                "unit_id": bags_id,
                "source_id": receipt_id,
                "user_id": admin_ctx["user_id"],
            },
        )

    with pytest.raises(IntegrityError):
        async with test_engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO material_movements "
                    "(id, organization_id, project_id, site_id, material_id, unit_id, "
                    "movement_type, quantity, occurred_at, source_type, source_id, "
                    "recorded_by_user_id, created_at) "
                    "VALUES (gen_random_uuid(), :org_id, :project_id, :site_id, :material_id, "
                    ":unit_id, 'RECEIPT', 10, now(), 'material_receipt', :source_id, :user_id, now())"
                ),
                {
                    "org_id": org_id,
                    "project_id": admin_ctx["project_id"],
                    "site_id": admin_ctx["site_id"],
                    "material_id": material_id,
                    "unit_id": bags_id,
                    "source_id": receipt_id,
                    "user_id": admin_ctx["user_id"],
                },
            )

    async with test_engine.connect() as conn:
        movement_count = (
            await conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM material_movements "
                    "WHERE source_type = 'material_receipt' AND source_id = :id"
                ),
                {"id": receipt_id},
            )
        ).scalar_one()
        assert movement_count == 1, (
            "the UNIQUE guard must leave exactly one movement; the duplicate insert "
            "must not have partially landed despite the rolled-back transaction"
        )


async def test_inflow_with_unit_mismatched_to_stock_unit_rejected(client, admin_ctx):
    """The existing test_outflow_with_unit_mismatched_to_stock_unit_rejected
    covers the outflow path; the inflow path goes through the same
    _resolve_and_validate_material_unit gate (router.py:512) and must also
    reject a unit_id that doesn't match the material's Stock Unit. No unit
    conversion is supported in V1 -- a cement material tracked in bags must
    refuse an inflow reported in tons, not silently store it."""
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    tons_id = await _tons_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement", bags_id)

    body = {
        "project_id": str(admin_ctx["project_id"]),
        "site_id": str(admin_ctx["site_id"]),
        "material_id": material_id,
        "unit_id": tons_id,  # Cement's Stock Unit is bags, not tons
        "quantity": "10",
        "movement_reason": "RECEIVED",
        "occurred_date": str(datetime.date.today()),
    }
    resp = await client.post("/materials/inflows", json=body, headers=_auth(admin_ctx["token"]))
    assert resp.status_code == 422


async def test_stock_unit_change_rejected_after_movement_exists(client, admin_ctx):
    """update_material (router.py:233) must refuse to change default_unit_id
    once any material_movements row references this material -- a material's
    tracking unit is fixed for its lifetime in V1 (no unit conversion).
    Existing test_delete_material_with_movements_rejected covers the delete
    lock; this covers the unit-change lock, which is the more common
    real-world temptation (admin renames 'bags' to 'sacks' mid-project)."""
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    tons_id = await _tons_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Rebar", tons_id)

    inflow_body = {
        "project_id": str(admin_ctx["project_id"]),
        "site_id": str(admin_ctx["site_id"]),
        "material_id": material_id,
        "unit_id": tons_id,
        "quantity": "10",
        "movement_reason": "RECEIVED",
        "occurred_date": str(datetime.date.today()),
    }
    resp = await client.post(
        "/materials/inflows", json=inflow_body, headers=_auth(admin_ctx["token"])
    )
    assert resp.status_code == 201

    resp = await client.patch(
        f"/materials/{material_id}",
        json={"default_unit_id": bags_id},  # attempt to switch tons -> bags
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 409
    assert "Stock Unit cannot change" in resp.json()["detail"]


async def test_stock_levels_derived_exclusively_from_movement_ledger(
    client, test_engine: AsyncEngine, admin_ctx
):
    """get_stock_levels (materials.py:303) must read ONLY from
    material_movements -- never from material_receipts/material_usage. The
    V2 design's whole point is that the ledger is the single source of stock
    truth; operational rows are history-only. If a future refactor regresses
    to SUM(receipts) - SUM(usage), stock would silently drift as orphan
    receipt rows (failed movement posts, manual backfills, etc.) leak in.

    This test seeds a material with one real inflow (quantity 10, which posts
    a matching movement) and one orphan material_receipts row (quantity 999,
    no movement). Inventory must read 10, not 1009 -- the orphan is
    structurally invisible to stock derivation."""
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement", bags_id)

    orphan_receipt_id = uuid.uuid4()
    async with test_engine.connect() as conn:
        org_id = (
            await conn.execute(
                sa.text("SELECT organization_id FROM users WHERE id = :id"),
                {"id": admin_ctx["user_id"]},
            )
        ).scalar_one()
    async with test_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO material_receipts "
                "(id, organization_id, project_id, site_id, material_name, quantity, unit, "
                "unit_id, material_id, occurred_date, occurred_date_source, source, "
                "movement_reason, created_by) "
                "VALUES (:id, :org_id, :project_id, :site_id, 'Cement', 999, 'bags', "
                ":unit_id, :material_id, :occurred_date, 'reported', 'manual', 'RECEIVED', :user_id)"
            ),
            {
                "id": orphan_receipt_id,
                "org_id": org_id,
                "project_id": admin_ctx["project_id"],
                "site_id": admin_ctx["site_id"],
                "unit_id": bags_id,
                "material_id": material_id,
                "occurred_date": datetime.date.today(),
                "user_id": admin_ctx["user_id"],
            },
        )

    real_body = {
        "project_id": str(admin_ctx["project_id"]),
        "site_id": str(admin_ctx["site_id"]),
        "material_id": material_id,
        "unit_id": bags_id,
        "quantity": "10",
        "movement_reason": "RECEIVED",
        "occurred_date": str(datetime.date.today()),
    }
    resp = await client.post("/materials/inflows", json=real_body, headers=_auth(admin_ctx["token"]))
    assert resp.status_code == 201

    resp = await client.get(
        "/materials/inventory",
        params={"project_id": str(admin_ctx["project_id"])},
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 200
    rows = resp.json()
    cement_row = next(r for r in rows if r["material_name"] == "Cement")
    assert cement_row["current_stock"] == "10.00", (
        "stock must be derived from material_movements only; the orphan receipt row "
        "(quantity 999, no matching movement) must be invisible to get_stock_levels"
    )

    async with test_engine.connect() as conn:
        orphan_movement_count = (
            await conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM material_movements WHERE source_id = :id"
                ),
                {"id": orphan_receipt_id},
            )
        ).scalar_one()
        assert orphan_movement_count == 0, (
            "the orphan receipt must have no movement -- this test's premise"
        )


async def test_reversal_produces_opposite_movement_and_net_zero_stock(
    client, test_engine: AsyncEngine, admin_ctx
):
    """The insert-only/reversal convention (0270 + 0300 + posting.py:11-15)
    says corrections never edit or delete a movement -- they post an opposite-
    direction movement with reversal_of_movement_id set. So a receipt of 10
    followed by its reversal must leave the ledger summing to exactly 0. The
    existing test_reversal_creates_offsetting_movement_and_preserves_original
    proves the original row survives and a new offsetting row appears; this
    test asserts the load-bearing net-zero stock invariant that follows."""
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement", bags_id)

    inflow_body = {
        "project_id": str(admin_ctx["project_id"]),
        "site_id": str(admin_ctx["site_id"]),
        "material_id": material_id,
        "unit_id": bags_id,
        "quantity": "10",
        "movement_reason": "RECEIVED",
        "occurred_date": str(datetime.date.today()),
    }
    resp = await client.post(
        "/materials/inflows", json=inflow_body, headers=_auth(admin_ctx["token"])
    )
    assert resp.status_code == 201
    receipt_id = resp.json()["id"]

    resp = await client.post(
        f"/materials/inflows/{receipt_id}/reverse",
        json={},
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 201

    resp = await client.get(
        "/materials/inventory",
        params={"project_id": str(admin_ctx["project_id"])},
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 200
    rows = resp.json()
    cement_row = next(r for r in rows if r["material_name"] == "Cement")
    assert cement_row["current_stock"] == "0.00", (
        "a receipt reversed by its opposite-direction ISSUE must net to zero"
    )
    assert cement_row["stock_state"] == "OUT_OF_STOCK"

    async with test_engine.connect() as conn:
        original_movement = (
            await conn.execute(
                sa.text(
                    "SELECT id FROM material_movements "
                    "WHERE source_type = 'material_receipt' AND source_id = :id "
                    "AND reversal_of_movement_id IS NULL"
                ),
                {"id": receipt_id},
            )
        ).scalar_one()

        reversal_movement = (
            (
                await conn.execute(
                    sa.text(
                        "SELECT movement_type, reversal_of_movement_id "
                        "FROM material_movements "
                        "WHERE reversal_of_movement_id = :orig_id"
                    ),
                    {"orig_id": original_movement},
                )
            )
            .mappings()
            .one()
        )
        assert reversal_movement["movement_type"] == "ISSUE", (
            "reversing a RECEIPT must post an ISSUE, not another RECEIPT"
        )
        assert reversal_movement["reversal_of_movement_id"] == original_movement


# ---------------------------------------------------------------------------
# Phase A -- integrity guards (migration 0459)
# ---------------------------------------------------------------------------
async def _receive(client, ctx, material_id, unit_id, qty):
    resp = await client.post(
        "/materials/inflows",
        json={
            "project_id": str(ctx["project_id"]),
            "site_id": str(ctx["site_id"]),
            "material_id": material_id,
            "unit_id": unit_id,
            "quantity": str(qty),
            "movement_reason": "RECEIVED",
            "occurred_date": str(datetime.date.today()),
        },
        headers=_auth(ctx["token"]),
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _stock(client, ctx, material_id) -> Decimal:
    resp = await client.get(
        "/materials/inventory",
        params={"project_id": str(ctx["project_id"]), "material_id": material_id},
        headers=_auth(ctx["token"]),
    )
    rows = resp.json()
    return Decimal(rows[0]["current_stock"]) if rows else Decimal("0")


async def test_a_movement_cannot_be_corrected_twice(client, admin_ctx):
    """The headline Phase A defect: correcting twice does not undo twice. It
    posts a second offsetting movement, so a 100-bag receipt reversed twice
    leaves stock 200 light -- permanently, because the ledger is append-only.
    """
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement DR", bags_id)
    receipt_id = await _receive(client, admin_ctx, material_id, bags_id, 100)

    first = await client.post(
        f"/materials/inflows/{receipt_id}/reverse",
        json={"reason_note": "wrong quantity"},
        headers=_auth(admin_ctx["token"]),
    )
    assert first.status_code == 201

    second = await client.post(
        f"/materials/inflows/{receipt_id}/reverse",
        json={"reason_note": "oops, again"},
        headers=_auth(admin_ctx["token"]),
    )
    assert second.status_code == 409
    assert "already corrected" in str(second.json()["detail"])

    # One correction applied: 100 in, 100 out, net zero -- not -100.
    assert await _stock(client, admin_ctx, material_id) == Decimal("0")


async def test_detail_endpoint_reports_already_reversed(client, admin_ctx):
    """So the dashboard can hide Correct instead of offering an action that 409s."""
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement AR", bags_id)
    receipt_id = await _receive(client, admin_ctx, material_id, bags_id, 20)

    before = await client.get(
        f"/materials/inflows/{receipt_id}", headers=_auth(admin_ctx["token"])
    )
    assert before.json()["already_reversed"] is False

    await client.post(
        f"/materials/inflows/{receipt_id}/reverse", json={}, headers=_auth(admin_ctx["token"])
    )
    after = await client.get(
        f"/materials/inflows/{receipt_id}", headers=_auth(admin_ctx["token"])
    )
    assert after.json()["already_reversed"] is True


async def test_material_names_are_case_and_whitespace_insensitive(client, admin_ctx):
    """One stockpile, one catalog row. Allowing "cement" beside "Cement" splits
    stock in two, and the WhatsApp resolver (already lower()-based) then picks
    between them arbitrarily."""
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    await _make_material(client, admin_ctx["token"], "Cement CI", bags_id)

    for variant in ("cement ci", "  Cement CI  ", "CEMENT CI"):
        resp = await client.post(
            "/materials",
            json={"name": variant, "default_unit_id": bags_id},
            headers=_auth(admin_ctx["token"]),
        )
        assert resp.status_code == 409, f"{variant!r} should collide"
        assert "already exists" in str(resp.json()["detail"])


async def test_idempotency_key_makes_a_retried_inflow_safe(client, admin_ctx):
    """A double tap, or a client retrying after a timeout on site wifi, must not
    become two deliveries nobody can tell apart."""
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement IDEM", bags_id)
    body = {
        "project_id": str(admin_ctx["project_id"]),
        "site_id": str(admin_ctx["site_id"]),
        "material_id": material_id,
        "unit_id": bags_id,
        "quantity": "40",
        "movement_reason": "RECEIVED",
        "occurred_date": str(datetime.date.today()),
    }
    headers = {**_auth(admin_ctx["token"]), "Idempotency-Key": f"test-{uuid.uuid4()}"}

    first = await client.post("/materials/inflows", json=body, headers=headers)
    second = await client.post("/materials/inflows", json=body, headers=headers)

    assert first.status_code == 201
    assert second.json()["status"] == "replayed"
    assert second.json()["id"] == first.json()["id"]
    assert await _stock(client, admin_ctx, material_id) == Decimal("40")


async def test_outflow_beyond_stock_is_refused_unless_explicitly_allowed(client, admin_ctx):
    """Typing 500 instead of 50 must not silently become permanent."""
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement NEG", bags_id)
    await _receive(client, admin_ctx, material_id, bags_id, 20)

    outflow = {
        "project_id": str(admin_ctx["project_id"]),
        "site_id": str(admin_ctx["site_id"]),
        "material_id": material_id,
        "unit_id": bags_id,
        "quantity": "500",
        "movement_reason": "CONSUMED",
        "occurred_date": str(datetime.date.today()),
        "allow_negative": False,
    }
    refused = await client.post(
        "/materials/outflows", json=outflow, headers=_auth(admin_ctx["token"])
    )
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert Decimal(detail["available"]) == Decimal("20")
    assert Decimal(detail["requested"]) == Decimal("500")

    # Negative stock is a real situation (deliveries recorded late), so this is
    # a confirmation, never a prohibition.
    allowed = await client.post(
        "/materials/outflows",
        json={**outflow, "allow_negative": True},
        headers=_auth(admin_ctx["token"]),
    )
    assert allowed.status_code == 201


async def test_stock_check_reports_the_balance_the_guard_uses(client, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement SC", bags_id)
    await _receive(client, admin_ctx, material_id, bags_id, 75)

    resp = await client.get(
        "/materials/stock-check",
        params={"material_id": material_id, "site_id": str(admin_ctx["site_id"])},
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 200
    assert Decimal(resp.json()["available"]) == Decimal("75")


async def test_concurrent_outflows_cannot_both_pass_the_same_stock(client, admin_ctx):
    """Without the advisory lock the guard is theatre: two issues of 8 against
    10 both read 10, both pass, both insert, and each user is told it was fine.
    """
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement RACE", bags_id)
    await _receive(client, admin_ctx, material_id, bags_id, 10)

    outflow = {
        "project_id": str(admin_ctx["project_id"]),
        "site_id": str(admin_ctx["site_id"]),
        "material_id": material_id,
        "unit_id": bags_id,
        "quantity": "8",
        "movement_reason": "CONSUMED",
        "occurred_date": str(datetime.date.today()),
        "allow_negative": False,
    }
    first, second = await asyncio.gather(
        client.post("/materials/outflows", json=outflow, headers=_auth(admin_ctx["token"])),
        client.post("/materials/outflows", json=outflow, headers=_auth(admin_ctx["token"])),
    )

    assert sorted([first.status_code, second.status_code]) == [201, 409]
    assert await _stock(client, admin_ctx, material_id) >= Decimal("0")


async def test_allow_negative_default_leaves_other_write_paths_unchanged(client, admin_ctx):
    """WhatsApp and mobile do not send the flag; they must keep working exactly
    as before this phase, so the default has to stay permissive."""
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement DEF", bags_id)

    resp = await client.post(
        "/materials/outflows",
        json={
            "project_id": str(admin_ctx["project_id"]),
            "site_id": str(admin_ctx["site_id"]),
            "material_id": material_id,
            "unit_id": bags_id,
            "quantity": "5",
            "movement_reason": "CONSUMED",
            "occurred_date": str(datetime.date.today()),
        },
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 201
    assert await _stock(client, admin_ctx, material_id) == Decimal("-5")


# ---------------------------------------------------------------------------
# Phase B -- purchase cost capture
# ---------------------------------------------------------------------------
async def test_purchase_cost_is_stored_and_returned(client, admin_ctx):
    """Until this phase the inflow API silently dropped any price sent to it,
    so Purchase History's cost column could never fill."""
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement COST", bags_id)

    created = await client.post(
        "/materials/inflows",
        json={
            "project_id": str(admin_ctx["project_id"]),
            "site_id": str(admin_ctx["site_id"]),
            "material_id": material_id,
            "unit_id": bags_id,
            "quantity": "200",
            "movement_reason": "RECEIVED",
            "occurred_date": str(datetime.date.today()),
            "unit_cost": "312.50",
        },
        headers=_auth(admin_ctx["token"]),
    )
    assert created.status_code == 201

    detail = await client.get(
        f"/materials/inflows/{created.json()['id']}", headers=_auth(admin_ctx["token"])
    )
    body = detail.json()
    assert Decimal(body["unit_cost"]) == Decimal("312.50")
    assert Decimal(body["total_cost"]) == Decimal("62500.00")


async def test_a_purchase_without_a_price_stores_null_not_zero(client, admin_ctx):
    """Zero would claim the delivery was free and drag every total downward."""
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement NOCOST", bags_id)
    receipt_id = await _receive(client, admin_ctx, material_id, bags_id, 10)

    body = (
        await client.get(f"/materials/inflows/{receipt_id}", headers=_auth(admin_ctx["token"]))
    ).json()
    assert body["unit_cost"] is None
    assert body["total_cost"] is None


async def test_last_purchase_reports_the_most_recent_recorded_rate(client, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement LAST", bags_id)

    for rate in ("300", "325"):
        await client.post(
            "/materials/inflows",
            json={
                "project_id": str(admin_ctx["project_id"]),
                "site_id": str(admin_ctx["site_id"]),
                "material_id": material_id,
                "unit_id": bags_id,
                "quantity": "10",
                "movement_reason": "RECEIVED",
                "occurred_date": str(datetime.date.today()),
                "unit_cost": rate,
            },
            headers=_auth(admin_ctx["token"]),
        )

    resp = await client.get(
        "/materials/last-purchase",
        params={"material_id": material_id},
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 200
    assert Decimal(resp.json()["unit_cost"]) == Decimal("325")


async def test_last_purchase_is_empty_not_404_when_never_priced(client, admin_ctx):
    """The entry form treats this as a hint; a missing hint is not an error."""
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement UNPRICED", bags_id)

    resp = await client.get(
        "/materials/last-purchase",
        params={"material_id": material_id},
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["unit_cost"] is None


async def test_a_corrected_purchase_is_flagged_so_spend_totals_can_exclude_it(
    client, admin_ctx
):
    """A reversed purchase was not money spent. Counting its cost would
    overstate what the company actually paid."""
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement REVCOST", bags_id)
    created = await client.post(
        "/materials/inflows",
        json={
            "project_id": str(admin_ctx["project_id"]),
            "site_id": str(admin_ctx["site_id"]),
            "material_id": material_id,
            "unit_id": bags_id,
            "quantity": "100",
            "movement_reason": "RECEIVED",
            "occurred_date": str(datetime.date.today()),
            "unit_cost": "312.50",
        },
        headers=_auth(admin_ctx["token"]),
    )
    receipt_id = created.json()["id"]

    listed = await client.get(
        "/materials/inflows",
        params={"project_id": str(admin_ctx["project_id"]), "material_id": material_id},
        headers=_auth(admin_ctx["token"]),
    )
    assert listed.json()["items"][0]["is_reversed"] is False

    await client.post(
        f"/materials/inflows/{receipt_id}/reverse",
        json={"reason_note": "wrong delivery"},
        headers=_auth(admin_ctx["token"]),
    )

    listed = await client.get(
        "/materials/inflows",
        params={"project_id": str(admin_ctx["project_id"]), "material_id": material_id},
        headers=_auth(admin_ctx["token"]),
    )
    original = next(i for i in listed.json()["items"] if i["id"] == receipt_id)
    assert original["is_reversed"] is True
    # The cost stays on the row -- the purchase did happen. It is the spend
    # total that must leave it out, which is what the flag enables.
    assert Decimal(original["total_cost"]) == Decimal("31250.00")  # 100 x 312.50


# ---------------------------------------------------------------------------
# BE-12: opening stock, and usage beyond known stock flagged in the DPR
# ---------------------------------------------------------------------------


def _opening_body(ctx: dict, material_id: str, unit_id: str, quantity: str = "40") -> dict:
    return {
        "project_id": str(ctx["project_id"]),
        "site_id": str(ctx["site_id"]),
        "material_id": material_id,
        "unit_id": unit_id,
        "quantity": quantity,
        "movement_reason": "OPENING_STOCK",
        "occurred_date": str(datetime.date.today()),
    }


async def test_opening_stock_counts_into_stock(client, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement", bags_id)
    resp = await client.post(
        "/materials/inflows",
        json=_opening_body(admin_ctx, material_id, bags_id),
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.status_code == 201, resp.text

    resp = await client.get(
        "/materials/inventory",
        params={"project_id": str(admin_ctx["project_id"])},
        headers=_auth(admin_ctx["token"]),
    )
    assert resp.json()[0]["current_stock"] == "40.00"


async def test_opening_stock_entered_once_per_site_and_material(client, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement", bags_id)
    body = _opening_body(admin_ctx, material_id, bags_id)
    first = await client.post("/materials/inflows", json=body, headers=_auth(admin_ctx["token"]))
    assert first.status_code == 201

    second = await client.post("/materials/inflows", json=body, headers=_auth(admin_ctx["token"]))
    assert second.status_code == 409
    assert "already entered" in second.json()["detail"]

    # Another material at the same site is its own opening figure.
    steel_id = await _make_material(client, admin_ctx["token"], "Steel", bags_id)
    other = await client.post(
        "/materials/inflows",
        json=_opening_body(admin_ctx, steel_id, bags_id),
        headers=_auth(admin_ctx["token"]),
    )
    assert other.status_code == 201


async def test_corrected_opening_stock_can_be_entered_again(client, admin_ctx):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement", bags_id)
    body = _opening_body(admin_ctx, material_id, bags_id)
    first = await client.post("/materials/inflows", json=body, headers=_auth(admin_ctx["token"]))
    reverse = await client.post(
        f"/materials/inflows/{first.json()['id']}/reverse",
        json={"reason_note": "counted wrong"},
        headers=_auth(admin_ctx["token"]),
    )
    assert reverse.status_code == 201

    again = await client.post(
        "/materials/inflows",
        json={**body, "quantity": "35"},
        headers=_auth(admin_ctx["token"]),
    )
    assert again.status_code == 201


async def test_opening_stock_forbidden_for_non_elevated_role(
    client, test_engine, test_org, admin_ctx
):
    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement", bags_id)
    site_engineer = await _make_user(test_engine, test_org, "site_engineer")
    token = _token(site_engineer, test_org, "site_engineer")
    resp = await client.post(
        "/materials/inflows",
        json=_opening_body(admin_ctx, material_id, bags_id),
        headers=_auth(token),
    )
    assert resp.status_code == 403


async def test_dpr_flags_usage_beyond_known_stock(client, test_engine, test_org, admin_ctx):
    from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

    bags_id = await _bags_unit_id(client, admin_ctx["token"])
    material_id = await _make_material(client, admin_ctx["token"], "Cement", bags_id)
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    base = {
        "project_id": str(admin_ctx["project_id"]),
        "site_id": str(admin_ctx["site_id"]),
        "material_id": material_id,
        "unit_id": bags_id,
    }
    headers = _auth(admin_ctx["token"])
    # Yesterday: 20 delivered. Today: opening stock 5 entered, 10 delivered,
    # 50 used -- 15 more than the site is known to hold.
    for path, quantity, reason, day in (
        ("/materials/inflows", "20", "RECEIVED", yesterday),
        ("/materials/inflows", "5", "OPENING_STOCK", today),
        ("/materials/inflows", "10", "RECEIVED", today),
        ("/materials/outflows", "50", "CONSUMED", today),
    ):
        resp = await client.post(
            path,
            json={**base, "quantity": quantity, "movement_reason": reason, "occurred_date": str(day)},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text

    async with test_engine.connect() as conn:
        payload = await PostgresDprRepository(conn).assemble_site_report_payload(
            organization_id=test_org,
            project_id=admin_ctx["project_id"],
            site_id=admin_ctx["site_id"],
            report_date=today,
        )

    [cement] = payload["materials"]
    assert Decimal(cement["opening"]) == Decimal("20")
    assert Decimal(cement["received"]) == Decimal("10")  # opening stock is not a delivery
    assert Decimal(cement["adjusted"]) == Decimal("5")
    assert Decimal(cement["used"]) == Decimal("50")
    assert Decimal(cement["closing"]) == Decimal("-15")
    assert cement["beyond_stock"] is True
    assert payload["stock_flags"] == 1
