"""WA [103]: the WhatsApp save of a site-to-site transfer and of opening stock
runs the same writes as the web (``domains/materials/transfers``), through the
M8 Handler, against a live database."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mesiri.application.materials.handlers import ExecuteConfirmedMaterialActionHandler
from mesiri.application.materials.resolution import PostgresMaterialResolver
from mesiri.bootstrap.settings import Settings
from mesiri.domains.materials.router import reverse_transfer_record
from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri.infrastructure.postgres.repositories.material_execution import (
    PostgresMaterialExecutionRepository,
)
from mesiri.infrastructure.postgres.repositories.materials import PostgresMaterialReadRepository
from mesiri_contracts.application.results.execution_result import ExecutionStatus
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine():
    eng = create_async_engine(Settings().postgres.dsn(), echo=False)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db():
    database = PostgresDatabase(Settings().postgres)
    await database.connect()
    yield database
    await database.disconnect()


@pytest.fixture
async def world(engine: AsyncEngine):
    """An organisation with one project, two sites, a user and bag-counted cement."""
    ids = {k: uuid.uuid4() for k in ("org", "user", "project", "site_a", "site_b", "material")}
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
                "VALUES (:id, 'Transfer Org', 'local', 'default', 'active', now(), now())"
            ),
            {"id": ids["org"]},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, created_at, updated_at) "
                "VALUES (:id, :org, :email, 'x', 'Tester', 'admin', now(), now())"
            ),
            {"id": ids["user"], "org": ids["org"], "email": f"{ids['user']}@example.com"},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                "VALUES (:id, :org, 'P', now(), now())"
            ),
            {"id": ids["project"], "org": ids["org"]},
        )
        for key, name in (("site_a", "Green Villa"), ("site_b", "Site B")):
            await conn.execute(
                sa.text(
                    "INSERT INTO sites (id, organization_id, project_id, name, created_at, updated_at) "
                    "VALUES (:id, :org, :project, :name, now(), now())"
                ),
                {"id": ids[key], "org": ids["org"], "project": ids["project"], "name": name},
            )
        unit_id = (
            await conn.execute(sa.text("SELECT id FROM units_of_measure WHERE code = 'bags'"))
        ).scalar_one()
        ids["unit"] = unit_id
        await conn.execute(
            sa.text(
                "INSERT INTO materials_catalog (id, organization_id, name, default_unit_id, is_active, created_by) "
                "VALUES (:id, :org, 'Cement', :unit, true, :user)"
            ),
            {"id": ids["material"], "org": ids["org"], "unit": unit_id, "user": ids["user"]},
        )
    yield ids
    async with engine.begin() as conn:
        for table in ("material_receipts", "material_usage"):
            await conn.execute(sa.text(f"UPDATE {table} SET reverses_movement_id = NULL WHERE organization_id = :o"), {"o": ids["org"]})  # noqa: S608
        for table in ("material_movements", "material_receipts", "material_usage"):
            await conn.execute(sa.text(f"DELETE FROM {table} WHERE organization_id = :o"), {"o": ids["org"]})  # noqa: S608
        await conn.execute(sa.text("DELETE FROM outbox_events WHERE aggregate_id IS NOT NULL AND payload->>'material_name' = 'Cement'"))
        await conn.execute(
            sa.text("DELETE FROM idempotency_keys WHERE command_type LIKE 'record_material_%' AND created_at > now() - interval '5 minutes'")
        )
        await conn.execute(sa.text("DELETE FROM materials_catalog WHERE organization_id = :o"), {"o": ids["org"]})
        await conn.execute(sa.text("DELETE FROM sites WHERE organization_id = :o"), {"o": ids["org"]})
        await conn.execute(sa.text("DELETE FROM projects WHERE organization_id = :o"), {"o": ids["org"]})
        await conn.execute(sa.text("DELETE FROM users WHERE organization_id = :o"), {"o": ids["org"]})
        await conn.execute(sa.text("DELETE FROM organizations WHERE id = :o"), {"o": ids["org"]})


def _confirmed(world: dict, action: DraftActionType, fields: dict, *, site: str = "site_a") -> ConfirmedActionV2:
    instance = str(uuid.uuid4())
    draft = DraftActionV2(
        draft_id="d1",
        correlation_id="cor-t",
        workflow_instance_id=instance,
        action_type=action,
        organization_id=str(world["org"]),
        user_id=str(world["user"]),
        project_id=str(world["project"]),
        site_id=str(world[site]),
        fields={"material_name": "Cement", "material_id": str(world["material"]), "unit": "bags", **fields},
    )
    return ConfirmedActionV2(
        confirmed_action_id="c1",
        workflow_instance_id=instance,
        correlation_id="cor-t",
        draft_action=draft,
        confirmed_by_user_id=str(world["user"]),
    )


def _handler(db: PostgresDatabase) -> ExecuteConfirmedMaterialActionHandler:
    return ExecuteConfirmedMaterialActionHandler(
        db=db, repo=PostgresMaterialExecutionRepository(), resolver=PostgresMaterialResolver()
    )


async def _stock(engine: AsyncEngine, world: dict, site: str) -> Decimal:
    async with engine.connect() as conn:
        return await PostgresMaterialReadRepository(conn).get_available_stock(
            world["org"], world[site], world["material"]
        )


async def test_opening_stock_is_entered_once_per_site_and_material(engine, db, world):
    first = _confirmed(
        world, DraftActionType.RECORD_MATERIAL_RECEIPT, {"quantity": 50, "movement_reason": "OPENING_STOCK"}
    )
    result = await _handler(db).handle(first)
    assert result.status is ExecutionStatus.SUCCEEDED
    assert await _stock(engine, world, "site_a") == Decimal("50")
    async with engine.connect() as conn:
        reason = (
            await conn.execute(
                sa.text("SELECT movement_reason FROM material_receipts WHERE id = :id"),
                {"id": uuid.UUID(result.material_row_id)},
            )
        ).scalar_one()
    assert reason == "OPENING_STOCK"

    second = _confirmed(
        world, DraftActionType.RECORD_MATERIAL_RECEIPT, {"quantity": 20, "movement_reason": "OPENING_STOCK"}
    )
    again = await _handler(db).handle(second)
    assert again.status is ExecutionStatus.REJECTED
    assert "already entered" in " ".join(again.rejection_reasons)
    assert await _stock(engine, world, "site_a") == Decimal("50")


async def test_plain_receipt_is_still_received(engine, db, world):
    result = await _handler(db).handle(_confirmed(world, DraftActionType.RECORD_MATERIAL_RECEIPT, {"quantity": 5}))
    assert result.status is ExecutionStatus.SUCCEEDED
    async with engine.connect() as conn:
        reason = (
            await conn.execute(
                sa.text("SELECT movement_reason FROM material_receipts WHERE id = :id"),
                {"id": uuid.UUID(result.material_row_id)},
            )
        ).scalar_one()
    assert reason == "RECEIVED"


async def test_transfer_moves_stock_and_reverses_as_one(engine, db, world):
    await _handler(db).handle(_confirmed(world, DraftActionType.RECORD_MATERIAL_RECEIPT, {"quantity": 30}))

    transfer = _confirmed(
        world,
        DraftActionType.TRANSFER_MATERIAL,
        {"quantity": 10, "to_site_id": str(world["site_b"]), "to_project_id": str(world["project"])},
    )
    result = await _handler(db).handle(transfer)
    assert result.status is ExecutionStatus.SUCCEEDED
    assert await _stock(engine, world, "site_a") == Decimal("20")
    assert await _stock(engine, world, "site_b") == Decimal("10")

    async with engine.connect() as conn:
        out = (
            await conn.execute(
                sa.text("SELECT movement_reason, transfer_id, source FROM material_usage WHERE id = :id"),
                {"id": uuid.UUID(result.material_row_id)},
            )
        ).one()
    assert (out[0], out[2]) == ("TRANSFER_OUT", "whatsapp")

    async with db.transaction() as conn:
        await reverse_transfer_record(
            conn,
            transfer_id=out[1],
            organization_id=world["org"],
            user_id=world["user"],
            reason_note="cancelled on WhatsApp",
        )
    assert await _stock(engine, world, "site_a") == Decimal("30")
    assert await _stock(engine, world, "site_b") == Decimal("0")


async def test_transfer_to_the_same_site_is_rejected(engine, db, world):
    same = _confirmed(
        world,
        DraftActionType.TRANSFER_MATERIAL,
        {"quantity": 1, "to_site_id": str(world["site_a"]), "to_project_id": str(world["project"])},
    )
    result = await _handler(db).handle(same)
    assert result.status is ExecutionStatus.REJECTED


async def test_transfer_to_another_companys_site_is_rejected(engine, db, world):
    other_site = uuid.uuid4()
    other_org = uuid.uuid4()
    other_project = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at, updated_at) "
                "VALUES (:id, 'Other', 'local', 'default', 'active', now(), now())"
            ),
            {"id": other_org},
        )
        await conn.execute(
            sa.text("INSERT INTO projects (id, organization_id, name, created_at, updated_at) VALUES (:id, :o, 'X', now(), now())"),
            {"id": other_project, "o": other_org},
        )
        await conn.execute(
            sa.text("INSERT INTO sites (id, organization_id, project_id, name, created_at, updated_at) VALUES (:id, :o, :p, 'Theirs', now(), now())"),
            {"id": other_site, "o": other_org, "p": other_project},
        )
    try:
        result = await _handler(db).handle(
            _confirmed(
                world,
                DraftActionType.TRANSFER_MATERIAL,
                {"quantity": 1, "to_site_id": str(other_site), "to_project_id": str(other_project)},
            )
        )
        assert result.status is ExecutionStatus.REJECTED
    finally:
        async with engine.begin() as conn:
            await conn.execute(sa.text("DELETE FROM sites WHERE id = :s"), {"s": other_site})
            await conn.execute(sa.text("DELETE FROM projects WHERE id = :p"), {"p": other_project})
            await conn.execute(sa.text("DELETE FROM organizations WHERE id = :o"), {"o": other_org})
