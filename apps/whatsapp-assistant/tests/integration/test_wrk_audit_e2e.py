"""Work done (audit 04) against a real database and the real workflow graph:
the agent's entry -> save-first / confirm -> activities and progress updates
-> the day's DPR assembly. WRK-01 (day 1 / day 2) and WRK-02 (the units)."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

from interactions import InteractionHandler
from interactions.execution_router import ActionTypeRoutingDispatcher
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.progress.dispatcher import (
    AddProgressUpdateExecutionDispatcher,
    CreateActivityExecutionDispatcher,
)
from mesiri.application.progress.handlers import (
    ExecuteConfirmedAddProgressUpdateHandler,
    ExecuteConfirmedCreateActivityHandler,
)
from mesiri.application.progress.resolution import PostgresProgressUnitResolver
from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository
from mesiri.infrastructure.postgres.repositories.progress_execution import (
    PostgresProgressExecutionRepository,
)
from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.enums import SemanticType
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.common.result import Result
from runtime.activity_query import ActivityQueryService
from runtime.agent.entry_base import Ready, Say
from runtime.agent.site_entry import SiteEntry
from runtime.material_catalog_query import MaterialCatalogQueryService
from runtime.save_first import SaveFirstService
from workflows import WorkflowRuntime
from workflows.fakes import FakeWorkflowInstanceRepository
from workflows.registry import WorkflowRegistry

pytestmark = pytest.mark.integration

# A progress update is stamped with the moment it is sent, so day two is today.
DAY2 = dt.datetime.now(dt.UTC).date()
DAY1 = DAY2 - dt.timedelta(days=1)


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
                name=f"WRK E2E {uuid.uuid4().hex[:6]}", owner_name="Owner",
                owner_phone=f"9197{uuid.uuid4().int % 10**8:08d}",
                project_name="Green Villa", site_names=("Green Villa",),
            ),
            now=dt.datetime(2026, 10, 21, 6, tzinfo=dt.UTC),
        )
    org, user, project = str(created.organization_id), str(created.owner_user_id), str(created.project_id)
    site = str(created.sites[0].site_id)
    actor = SimpleNamespace(
        role="ADMIN", user_id=user, organization_id=org,
        projects=[SimpleNamespace(id=project, name="Green Villa")],
        sites=[SimpleNamespace(id=site, name="Green Villa", project_id=project)],
    )
    ctx = SimpleNamespace(
        organization_id=org, user_id=user, project_id=project, site_id=site, conversation_id=None,
        permissions=[], timezone="Asia/Kolkata", context_organization_id=org, context_user_id=user,
        context_project_id=project, context_site_id=site, role="ADMIN",
    )

    class _Context:
        async def resolve(self, message, understanding):
            return Result.ok(ctx)

    entry = SiteEntry(
        context_resolver=_Context(), org_settings_query=None, actor=actor,
        activity_query=ActivityQueryService(db), catalog_query=MaterialCatalogQueryService(db),
    )
    repo, resolver = PostgresProgressExecutionRepository(), PostgresProgressUnitResolver()
    runtime = WorkflowRuntime(registry=WorkflowRegistry(), repo=FakeWorkflowInstanceRepository())
    handler = InteractionHandler(
        runtime,
        dispatcher=ActionTypeRoutingDispatcher({
            DraftActionType.CREATE_ACTIVITY: CreateActivityExecutionDispatcher(
                ExecuteConfirmedCreateActivityHandler(db=db, repo=repo, resolver=resolver)),
            DraftActionType.ADD_PROGRESS_UPDATE: AddProgressUpdateExecutionDispatcher(
                ExecuteConfirmedAddProgressUpdateHandler(db=db, repo=repo, resolver=resolver)),
        }),
        save_first=SaveFirstService(db),
    )
    yield SimpleNamespace(db=db, entry=entry, runtime=runtime, handler=handler, org=created.organization_id,
                          user=user, project=created.project_id, site=created.sites[0].site_id)
    async with db.transaction() as conn:
        o = created.organization_id
        for sql in (
            "DELETE FROM fact_reviews WHERE organization_id = :o",
            "DELETE FROM progress_updates WHERE activity_id IN (SELECT id FROM activities WHERE organization_id = :o)",
            "DELETE FROM activity_quantities WHERE activity_id IN (SELECT id FROM activities WHERE organization_id = :o)",
            "DELETE FROM activity_links WHERE activity_id IN (SELECT id FROM activities WHERE organization_id = :o)",
            "DELETE FROM activities WHERE organization_id = :o",
            "DELETE FROM organizations WHERE id = :o",
        ):
            await conn.execute(text(sql), {"o": o})
    await db.disconnect()


async def _send(world, message_id: str, **fields: Any):
    message = SimpleNamespace(correlation_id=f"cor_{message_id}", message_id=message_id, modality=None, text="", metadata={})
    candidate = Candidate(semantic_type=SemanticType.GENERAL_SITE_UPDATE, fields=fields)
    prepared = await world.entry.prepare(message, _Understanding(candidate), candidate)
    if isinstance(prepared, Say):
        return prepared
    assert isinstance(prepared, Ready), prepared
    await world.runtime.start(prepared.decision, prepared.event)
    handled = await world.handler.save_now(world.user)
    if handled is None:  # confirm-first (a progress update on open work): the sender says yes
        handled = await world.handler.handle_fast_path(world.user, SimpleNamespace(text="yes", message_id=message_id))
    return handled


async def _day(world, day):
    async with world.db.transaction() as conn:
        return await PostgresDprRepository(conn).assemble_site_day(
            organization_id=world.org, project_id=world.project, site_id=world.site, report_date=day
        )


async def test_wrk01_work_started_on_day_one_is_on_day_twos_report_with_its_update(world):
    first = await _send(world, "w1", narrative="started brickwork ground floor", work_type="brickwork",
                        occurred_on=DAY1.isoformat())
    assert first is not None and first.execution_result is not None, first
    second = await _send(world, "w2", narrative="brickwork 60% done", work_type="brickwork",
                         progress_percent=60, occurred_on=DAY2.isoformat(), continues="brickwork")
    assert second is not None and second.execution_result is not None, second
    done = await _send(world, "w3", narrative="brickwork finished", work_type="brickwork",
                       status="completed", occurred_on=DAY2.isoformat(), continues="brickwork")
    assert done is not None and done.execution_result is not None, done

    payload, _ = await _day(world, DAY2)
    names = [(a["work_type"], a["continued"], a["status"]) for a in payload["activities"]]
    assert names == [("brickwork", True, "COMPLETED")], payload["activities"]


@pytest.mark.parametrize(
    "work,quantity,unit,code",
    [
        ("wiring", 50, "meter", "m"),
        ("skirting", 120, "rft", "rft"),
        ("tiling", 200, "sq ft", "sqft"),
        ("concreting", 20, "m3", "cum"),
        ("plastering", 50, "sq ft", "sqft"),
        ("paint", 80, "sq.m", "sqm"),
    ],
)
async def test_wrk02_the_units_people_type_are_saved(world, work, quantity, unit, code):
    handled = await _send(world, f"u-{work}", narrative=f"{quantity} {unit} {work} done", work_type=work,
                          quantities=[{"work_type": work, "quantity": quantity, "unit": unit}],
                          occurred_on=DAY2.isoformat())
    assert handled is not None and handled.execution_result is not None, handled
    assert handled.execution_result.status.value.lower() == "succeeded", handled.reply_text
    async with world.db.transaction() as conn:
        saved = (await conn.execute(text(
            "SELECT u.code FROM activity_quantities q JOIN units_of_measure u ON u.id = q.unit_id"
            " JOIN activities a ON a.id = q.activity_id WHERE a.organization_id = :o"), {"o": world.org})).scalars().all()
    assert saved == [code]


async def test_wrk02_an_unknown_unit_asks_with_unit_buttons_and_saves_nothing(world):
    said = await _send(world, "u-bad", narrative="5 furlongs wall", work_type="wall",
                       quantities=[{"work_type": "wall", "quantity": 5, "unit": "furlongs"}])
    assert isinstance(said, Say) and said.awaiting == "unit" and "sq ft" in said.options
    async with world.db.transaction() as conn:
        n = (await conn.execute(text("SELECT count(*) FROM activities WHERE organization_id = :o"), {"o": world.org})).scalar_one()
    assert n == 0
