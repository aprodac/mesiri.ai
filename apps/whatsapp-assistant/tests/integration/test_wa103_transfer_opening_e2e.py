"""[103] against a real database and the real workflow graph: a transfer between
two sites and opening stock, from the agent's entry through save-first to the
stock figures, then taken back by Cancel."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

from interactions import InteractionHandler
from mesiri.application.materials.dispatcher import MaterialExecutionDispatcher
from mesiri.application.materials.handlers import ExecuteConfirmedMaterialActionHandler
from mesiri.application.materials.resolution import PostgresMaterialResolver
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri.infrastructure.postgres.repositories.material_execution import (
    PostgresMaterialExecutionRepository,
)
from mesiri.infrastructure.postgres.repositories.materials import PostgresMaterialReadRepository
from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.enums import SemanticType
from mesiri_contracts.common.result import Result
from runtime.agent.material_entry import MaterialEntry, Ready, Say
from runtime.inventory_query import MaterialInventoryQueryService
from runtime.material_catalog_query import MaterialCatalogQueryService
from runtime.save_first import SaveFirstService
from workflows import WorkflowRuntime
from workflows.fakes import FakeWorkflowInstanceRepository
from workflows.registry import WorkflowRegistry

pytestmark = pytest.mark.integration

MESSAGE = SimpleNamespace(correlation_id="cor_103", message_id="wamid.103", modality=None)


class _Understanding:
    def __init__(self, candidate):
        self.candidates = [candidate]

    def model_copy(self, *, update):
        return _Understanding(update["candidates"][0])


@pytest.fixture
async def world():
    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    async with db.transaction() as conn:
        created = await create_company(
            conn,
            NewCompany(
                name=f"WA103 E2E {uuid.uuid4().hex[:6]}",
                owner_name="Owner",
                owner_phone=f"9197{uuid.uuid4().int % 10**8:08d}",
                project_name="Green Villa",
                site_names=("Green Villa", "Site B"),
            ),
            now=dt.datetime(2026, 10, 24, 6, tzinfo=dt.UTC),
        )
        # The company starts with a catalogue; cement is counted in bags.
        material_id = (
            await conn.execute(
                text("SELECT id FROM materials_catalog WHERE organization_id = :o AND name = 'Cement'"),
                {"o": created.organization_id},
            )
        ).scalar_one()
    org, user = str(created.organization_id), str(created.owner_user_id)
    project = str(created.project_id)
    sites = [SimpleNamespace(id=str(s.site_id), name=s.name, project_id=project) for s in created.sites]
    actor = SimpleNamespace(
        role="ADMIN", user_id=user, organization_id=org,
        projects=[SimpleNamespace(id=project, name="Green Villa")], sites=sites,
    )
    ctx = SimpleNamespace(
        organization_id=org, user_id=user, project_id=project, site_id=sites[0].id, conversation_id=None,
        permissions=[], timezone="Asia/Kolkata", context_organization_id=org, context_user_id=user,
        context_project_id=project, context_site_id=sites[0].id,
    )

    class _Context:
        async def resolve(self, message, understanding):
            return Result.ok(ctx)

    entry = MaterialEntry(
        context_resolver=_Context(),
        catalog_query=MaterialCatalogQueryService(db),
        inventory_query=MaterialInventoryQueryService(db),
        org_settings_query=None,
        actor=actor,
    )
    runtime = WorkflowRuntime(registry=WorkflowRegistry(), repo=FakeWorkflowInstanceRepository())
    handler = InteractionHandler(
        runtime,
        dispatcher=MaterialExecutionDispatcher(
            ExecuteConfirmedMaterialActionHandler(
                db=db, repo=PostgresMaterialExecutionRepository(), resolver=PostgresMaterialResolver()
            )
        ),
        save_first=SaveFirstService(db),
    )
    yield SimpleNamespace(
        db=db, entry=entry, runtime=runtime, handler=handler, org=created.organization_id,
        user=user, sites=sites, material=material_id,
    )
    async with db.transaction() as conn:
        o = created.organization_id
        for table in ("material_receipts", "material_usage"):
            await conn.execute(text(f"UPDATE {table} SET reverses_movement_id = NULL WHERE organization_id = :o"), {"o": o})  # noqa: S608
        await conn.execute(text("DELETE FROM fact_reviews WHERE organization_id = :o"), {"o": o})
        for table in ("material_movements", "material_receipts", "material_usage"):
            await conn.execute(text(f"DELETE FROM {table} WHERE organization_id = :o"), {"o": o})  # noqa: S608
        await conn.execute(text("DELETE FROM material_invoices WHERE organization_id = :o"), {"o": o})
        await conn.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": o})
    await db.disconnect()


async def _send(world, **fields: Any):
    base = {"material_name": "cement", "quantity": 10, "unit": "bags"}
    candidate = Candidate(semantic_type=SemanticType.MATERIAL_UPDATE, fields={**base, **fields})
    prepared = await world.entry.prepare(MESSAGE, _Understanding(candidate), candidate)
    assert isinstance(prepared, Ready), prepared
    run = await world.runtime.start(prepared.decision, prepared.event)
    assert run.workflow_key is prepared.decision.workflow_key
    return await world.handler.save_now(world.user)


async def _stock(world, site_index: int) -> float:
    async with world.db.transaction() as conn:
        return float(
            await PostgresMaterialReadRepository(conn).get_available_stock(
                world.org, uuid.UUID(world.sites[site_index].id), world.material
            )
        )


async def test_opening_stock_once_then_a_transfer_then_cancel_takes_back_both_halves(world):
    opening = await _send(world, direction="opening_stock", quantity=50)
    assert opening is not None and opening.saved_draft
    assert await _stock(world, 0) == 50

    # A second opening entry for the same site and material is refused with a reason.
    again = await _send(world, direction="opening_stock", quantity=20)
    assert again is not None and not again.saved_draft
    assert "already entered" in again.reply_text
    assert await _stock(world, 0) == 50

    moved = await _send(world, direction="transfer", to_site_name="Site B", quantity=10)
    assert moved is not None and moved.saved_draft, moved and moved.reply_text
    assert "Transfer: Cement 10 bags · Green Villa → Site B" in moved.reply_text
    assert (await _stock(world, 0), await _stock(world, 1)) == (40, 10)

    outflow = moved.execution_result.material_row_id
    undone = await SaveFirstService(world.db).undo_facts(
        organization_id=str(world.org), actor_user_id=world.user, facts=[("material_usage", uuid.UUID(outflow))]
    )
    assert undone.done and not undone.refused
    assert (await _stock(world, 0), await _stock(world, 1)) == (50, 0)


async def test_an_unknown_destination_asks_with_their_sites(world):
    candidate = Candidate(
        semantic_type=SemanticType.MATERIAL_UPDATE,
        fields={"material_name": "cement", "quantity": 1, "unit": "bags", "direction": "transfer", "to_site_name": "Nowhere"},
    )
    said = await world.entry.prepare(MESSAGE, _Understanding(candidate), candidate)
    assert isinstance(said, Say) and said.options == ("Site B",)
