"""Request 124, P1: the Save tap against a real database and the real services.

A draft holds what was said; nothing is written before the tap; the tap writes
every ready item through the existing workflow, save-first and the module's own
handler, in ONE transaction -- so a failure leaves no half of it -- and what it
writes is what the same message wrote before drafts (labour included).

Run with a live database:
    pytest apps/whatsapp-assistant/tests/integration/test_draft_save_postgres.py -m integration
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

from interactions import InteractionHandler
from interactions.execution_router import ActionTypeRoutingDispatcher
from mesiri.application.labour.dispatcher import LabourExecutionDispatcher
from mesiri.application.labour.handlers import ExecuteConfirmedLabourAttendanceHandler
from mesiri.application.materials.dispatcher import MaterialExecutionDispatcher
from mesiri.application.materials.handlers import ExecuteConfirmedMaterialActionHandler
from mesiri.application.materials.resolution import PostgresMaterialResolver
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.progress.dispatcher import (
    AddProgressUpdateExecutionDispatcher,
    CreateActivityExecutionDispatcher,
    ReportSiteIssueExecutionDispatcher,
)
from mesiri.application.progress.handlers import (
    ExecuteConfirmedAddProgressUpdateHandler,
    ExecuteConfirmedCreateActivityHandler,
    ExecuteConfirmedReportSiteIssueHandler,
)
from mesiri.application.progress.resolution import PostgresProgressUnitResolver
from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri.infrastructure.postgres.repositories.labour_execution import (
    PostgresLabourExecutionRepository,
)
from mesiri.infrastructure.postgres.repositories.material_execution import (
    PostgresMaterialExecutionRepository,
)
from mesiri.infrastructure.postgres.repositories.progress_execution import (
    PostgresProgressExecutionRepository,
)
from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from mesiri_contracts.common.result import Result
from runtime.activity_query import ActivityQueryService
from runtime.agent import draft as dr
from runtime.agent.draft_store import PostgresDraftStore
from runtime.agent.journal import PostgresJournalStore
from runtime.agent.journey_gateway import JourneyGateway
from runtime.agent.labour_entry import LabourEntry
from runtime.agent.material_entry import MaterialEntry
from runtime.agent.site_entry import SiteEntry
from runtime.agent.tools import (
    REPORT_ISSUE,
    SAVE_LABOUR,
    SAVE_MATERIAL_RECEIPT,
    SAVE_MATERIAL_USAGE,
    SAVE_WORK_DONE,
    ScopeLookup,
    to_candidate,
)
from runtime.inventory_query import MaterialInventoryQueryService
from runtime.material_catalog_query import MaterialCatalogQueryService
from runtime.save_first import SaveFirstService
from runtime.workforce_query import PostgresWorkforceQueryService
from workflows import WorkflowRuntime
from workflows.fakes import FakeWorkflowInstanceRepository
from workflows.registry import WorkflowRegistry

pytestmark = pytest.mark.integration


def _message(text_: str = "the message") -> NormalizedMessage:
    return NormalizedMessage(
        message_id="wamid.124",
        correlation_id="cor_124",
        sender=SenderInfo(wa_id="919800000124", profile_name="Owner"),
        timestamp=dt.datetime(2026, 10, 27, 6, tzinfo=dt.UTC),
        modality=InputModality.TEXT,
        text=text_,
    )


class _Context:
    def __init__(self, ctx) -> None:
        self._ctx = ctx

    async def resolve(self, message, understanding):  # noqa: ANN001, ANN202
        return Result.ok(self._ctx)


class _FailsOn:
    """A dispatcher whose n-th write is refused."""

    def __init__(self, inner, n: int) -> None:
        self.inner, self.n, self.seen = inner, n, 0

    async def dispatch(self, confirmed):  # noqa: ANN001, ANN202
        self.seen += 1
        if self.seen == self.n:
            return ExecutionResult(status=ExecutionStatus.FAILED, idempotency_key=f"x{self.seen}")
        return await self.inner.dispatch(confirmed)


@pytest.fixture
async def world():
    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    async with db.transaction() as conn:
        created = await create_company(
            conn,
            NewCompany(
                name=f"Draft E2E {uuid.uuid4().hex[:6]}",
                owner_name="Owner",
                owner_phone=f"9197{uuid.uuid4().int % 10**8:08d}",
                project_name="Green Villa",
                site_names=("Green Villa",),
            ),
            now=dt.datetime(2026, 10, 27, 6, tzinfo=dt.UTC),
        )
    org, user, project = str(created.organization_id), str(created.owner_user_id), str(created.project_id)
    sites = [SimpleNamespace(id=str(s.site_id), name=s.name, project_id=project) for s in created.sites]
    actor = SimpleNamespace(
        role="ADMIN", user_id=user, organization_id=org, timezone="Asia/Kolkata", sites=sites,
        projects=[SimpleNamespace(id=project, name="Green Villa")],
    )
    ctx = SimpleNamespace(
        organization_id=org, user_id=user, project_id=project, site_id=sites[0].id, conversation_id=None,
        permissions=[], timezone="Asia/Kolkata", context_organization_id=org, context_user_id=user,
        context_project_id=project, context_site_id=sites[0].id,
    )
    router = ActionTypeRoutingDispatcher(
        {
            DraftActionType.RECORD_MATERIAL_RECEIPT: (
                material := MaterialExecutionDispatcher(
                    ExecuteConfirmedMaterialActionHandler(
                        db=db, repo=PostgresMaterialExecutionRepository(), resolver=PostgresMaterialResolver()
                    )
                )
            ),
            DraftActionType.RECORD_MATERIAL_USAGE: material,
            DraftActionType.RECORD_LABOUR_ATTENDANCE: LabourExecutionDispatcher(
                ExecuteConfirmedLabourAttendanceHandler(db=db, repo=PostgresLabourExecutionRepository())
            ),
        }
    )
    progress_repo, units = PostgresProgressExecutionRepository(), PostgresProgressUnitResolver()
    router._dispatchers[DraftActionType.CREATE_ACTIVITY] = CreateActivityExecutionDispatcher(
        ExecuteConfirmedCreateActivityHandler(db=db, repo=progress_repo, resolver=units)
    )
    router._dispatchers[DraftActionType.ADD_PROGRESS_UPDATE] = AddProgressUpdateExecutionDispatcher(
        ExecuteConfirmedAddProgressUpdateHandler(db=db, repo=progress_repo, resolver=units)
    )
    router._dispatchers[DraftActionType.RECORD_SITE_ISSUE] = ReportSiteIssueExecutionDispatcher(
        ExecuteConfirmedReportSiteIssueHandler(db=db, repo=progress_repo)
    )
    runtime = WorkflowRuntime(registry=WorkflowRegistry(), repo=FakeWorkflowInstanceRepository())
    save_first = SaveFirstService(db)
    handler = InteractionHandler(runtime, dispatcher=router, save_first=save_first)
    state = SimpleNamespace(
        db=db, org=created.organization_id, user=user, actor=actor, sites=sites, runtime=runtime, handler=handler,
        save_first=save_first, drafts=PostgresDraftStore(db), router=router, ctx=ctx,
        material_entry=MaterialEntry(
            context_resolver=_Context(ctx), catalog_query=MaterialCatalogQueryService(db),
            inventory_query=MaterialInventoryQueryService(db), org_settings_query=None, actor=actor,
        ),
        labour_entry=LabourEntry(
            context_resolver=_Context(ctx), org_settings_query=None, actor=actor,
            workforce_query=PostgresWorkforceQueryService(db),
        ),
        site_entry=SiteEntry(
            context_resolver=_Context(ctx), org_settings_query=None, actor=actor,
            activity_query=ActivityQueryService(db), catalog_query=MaterialCatalogQueryService(db),
        ),
    )
    yield state
    async with db.transaction() as conn:
        o = created.organization_id
        await conn.execute(text("DELETE FROM message_drafts WHERE organization_id = :o"), {"o": o})
        await conn.execute(text("DELETE FROM fact_reviews WHERE organization_id = :o"), {"o": o})
        await conn.execute(
            text("UPDATE material_receipts SET reverses_movement_id = NULL WHERE organization_id = :o"), {"o": o}
        )
        await conn.execute(
            text("UPDATE material_usage SET reverses_movement_id = NULL WHERE organization_id = :o"), {"o": o}
        )
        for table in ("material_movements", "material_receipts", "material_usage"):
            await conn.execute(text(f"DELETE FROM {table} WHERE organization_id = :o"), {"o": o})  # noqa: S608
        await conn.execute(text("DELETE FROM material_invoices WHERE organization_id = :o"), {"o": o})
        await conn.execute(
            text("DELETE FROM labour_attendance_lines WHERE report_id IN "
                 "(SELECT id FROM labour_attendance_reports WHERE organization_id = :o)"), {"o": o}
        )
        await conn.execute(text("DELETE FROM labour_attendance_reports WHERE organization_id = :o"), {"o": o})
        await conn.execute(
            text("DELETE FROM activity_corrections WHERE activity_id IN "
                 "(SELECT id FROM activities WHERE organization_id = :o)"), {"o": o}
        )
        for table in ("progress_updates", "activity_quantities"):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE activity_id IN (SELECT id FROM activities WHERE organization_id = :o)"),  # noqa: S608
                {"o": o},
            )
        await conn.execute(text("DELETE FROM activities WHERE organization_id = :o"), {"o": o})
        await conn.execute(text("DELETE FROM site_issues WHERE organization_id = :o"), {"o": o})
        await conn.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": o})
    await db.disconnect()


def _gateway(w, *, draft: bool, dispatcher=None) -> JourneyGateway:
    if dispatcher is not None:
        w.handler._dispatcher = dispatcher
    return JourneyGateway(
        message=_message(),
        save_now=lambda: w.handler.save_now(w.user, actor=w.actor),
        undo=lambda: None,
        followups=lambda handled: None,
        held_prompt=lambda journey: None,
        material_entry=w.material_entry,
        labour_entry=w.labour_entry,
        site_entry=w.site_entry,
        start_workflow=w.runtime.start,
        actor=w.actor,
        draft_v2=draft,
        drafts=w.drafts if draft else None,
        journal=PostgresJournalStore(w.db) if draft else None,
        undo_facts=lambda facts: w.handler.undo_facts(organization_id=str(w.org), user_id=w.user, facts=facts),
        confirm_now=lambda: w.handler.confirm_now(w.user, actor=w.actor),
        settle_facts=lambda facts: w.handler.settle_drafts(
            organization_id=str(w.org), user_id=w.user, facts=facts, keep=True
        ),
        transaction=w.db.shared_transaction,
    )


def _scope(w) -> ScopeLookup:
    return ScopeLookup(
        projects=tuple((p.id, p.name) for p in w.actor.projects), sites=tuple((s.id, s.name, s.project_id) for s in w.sites)
    )


async def _call(w, gateway: JourneyGateway, tool: str, args: dict[str, Any]):
    gateway.current_call = (tool, args)
    return await gateway.run(to_candidate(tool, args, _scope(w)), text="the message")


async def _count(w, table: str) -> int:
    async with w.db.transaction() as conn:
        return (
            await conn.execute(text(f"SELECT count(*) FROM {table} WHERE organization_id = :o"), {"o": w.org})  # noqa: S608
        ).scalar_one()


RECEIPT = (SAVE_MATERIAL_RECEIPT, {"material": "cement", "quantity": 50, "unit": "bags", "supplier": "Sharma Traders"})
USAGE = (SAVE_MATERIAL_USAGE, {"material": "cement", "quantity": 5, "unit": "bags"})
LABOUR = (SAVE_LABOUR, {"workers": [{"trade": "mason", "headcount": 3}, {"trade": "helper", "headcount": 12}]})


async def _open(w) -> dr.MessageDraft:
    draft = await w.drafts.open_for(w.org, w.user)
    assert draft is not None
    return draft


async def test_nothing_is_written_until_save_then_everything_is_one_commit(world):
    gateway = _gateway(world, draft=True)
    for tool, args in (LABOUR, RECEIPT, USAGE):
        step = await _call(world, gateway, tool, args)
        assert step.status == "drafted", step
    assert [await _count(world, t) for t in ("labour_attendance_reports", "material_receipts", "material_usage")] == [0, 0, 0]
    draft = await _open(world)
    assert [i.kind for i in draft.items] == ["labour", "material_in", "material_out"]

    reply = await _gateway(world, draft=True).save_draft(draft)

    assert reply.text.startswith("✅ Saved · ") or reply.text.startswith("✅ Saved: "), reply.text
    assert [await _count(world, t) for t in ("labour_attendance_reports", "material_receipts", "material_usage")] == [1, 1, 1]
    async with world.db.transaction() as conn:
        states = (
            await conn.execute(
                text("SELECT DISTINCT ON (fact_type, fact_id) fact_type, state FROM fact_reviews "
                     "WHERE organization_id = :o ORDER BY fact_type, fact_id, created_at DESC"), {"o": world.org}
            )
        ).all()
        status = (await conn.execute(text("SELECT status FROM message_drafts WHERE id = :i"), {"i": uuid.UUID(draft.id)})).scalar_one()
    assert sorted(states) == [("labour_report", "confirmed"), ("material_receipt", "confirmed"), ("material_usage", "confirmed")]
    assert status == "saved"
    # A second tap writes nothing more.
    again = await _gateway(world, draft=True).save_draft(draft)
    assert again.text == dr.ALREADY_DONE
    assert await _count(world, "labour_attendance_reports") == 1


async def test_a_save_writes_one_journal_entry_and_an_undo_removes_exactly_what_it_names(world):
    """Request 142 (B): the entry is written in the Save's transaction; "undo" asks first and
    removes the named fact through the module's own undo."""
    gateway = _gateway(world, draft=True)
    for tool, args in (LABOUR, RECEIPT):
        await _call(world, gateway, tool, args)
    draft = await _open(world)
    await _gateway(world, draft=True).save_draft(draft)

    journal = PostgresJournalStore(world.db)
    (entry,) = await journal.recent(world.org, world.user)
    assert entry.draft_id == draft.id and {f.tool for f in entry.facts} == {SAVE_LABOUR, SAVE_MATERIAL_RECEIPT}
    assert all(uuid.UUID(f.fact_id) for f in entry.facts)

    step = await _gateway(world, draft=True).change_or_undo("the cement")
    assert step.awaiting == "confirm_undo" and "Remove this?" in step.reply.text
    assert await _count(world, "material_receipts") == 1  # asking removed nothing
    from runtime.agent import journal as jr

    action, entry_id, numbers = jr.parse_tap(step.reply.buttons[0].id)
    reply = await _gateway(world, draft=True).journal_tap(action, entry_id, numbers)
    assert reply.text.startswith("✅ Removed:"), reply.text
    again = await journal.get(entry.id, world.org, world.user)
    assert [f.undone for f in again.facts if f.tool == SAVE_MATERIAL_RECEIPT] == [True]
    assert [f.undone for f in again.facts if f.tool == SAVE_LABOUR] == [False]
    async with world.db.transaction() as conn:
        states = dict(
            (await conn.execute(
                text("SELECT DISTINCT ON (fact_type, fact_id) fact_type, state FROM fact_reviews "
                     "WHERE organization_id = :o ORDER BY fact_type, fact_id, created_at DESC"), {"o": world.org}
            )).all()
        )
    assert states["material_receipt"] != "confirmed" and states["labour_report"] == "confirmed"


async def test_a_failure_part_way_leaves_nothing_written_and_the_card_open(world):
    gateway = _gateway(world, draft=True)
    for tool, args in (LABOUR, RECEIPT, USAGE):
        await _call(world, gateway, tool, args)
    draft = await _open(world)

    failing = _gateway(world, draft=True, dispatcher=_FailsOn(world.router, 3))  # the usage write is refused
    reply = await failing.save_draft(draft)

    assert reply.text.startswith("Nothing was saved. Couldn't save"), reply.text
    assert [await _count(world, t) for t in ("labour_attendance_reports", "material_receipts", "material_usage")] == [0, 0, 0]
    async with world.db.transaction() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM fact_reviews WHERE organization_id = :o"), {"o": world.org})).scalar_one() == 0
    assert await PostgresJournalStore(world.db).recent(world.org, world.user) == []  # ...and so was the journal
    still = await _open(world)  # the claim was rolled back with the rest
    assert still.id == draft.id and [i.state for i in still.items] == [dr.OK, dr.OK, dr.UNREADABLE]

    # The rest can be saved once the refused item is out of the way (the dispatcher works again).
    world.handler._dispatcher = world.router
    done = await _gateway(world, draft=True).save_draft(still)
    assert done.text.startswith("✅ Saved")
    assert [await _count(world, t) for t in ("labour_attendance_reports", "material_receipts", "material_usage")] == [1, 1, 0]


async def test_cancel_discards_the_draft_and_no_row_ever_existed(world):
    gateway = _gateway(world, draft=True)
    await _call(world, gateway, *LABOUR)
    draft = await _open(world)
    reply = await _gateway(world, draft=True).cancel_draft(draft)
    assert reply.text == dr.CANCELLED
    assert await world.drafts.open_for(world.org, world.user) is None
    assert await _count(world, "labour_attendance_reports") == 0


async def _labour_rows(w) -> list[tuple[Any, ...]]:
    async with w.db.transaction() as conn:
        report = (
            await conn.execute(
                text("SELECT project_id, site_id, occurred_date, recorded_via, created_by FROM labour_attendance_reports "
                     "WHERE organization_id = :o ORDER BY created_at"), {"o": w.org}
            )
        ).all()
        lines = (
            await conn.execute(
                text("SELECT l.trade, l.headcount, l.worker_name, l.contractor FROM labour_attendance_lines l "
                     "JOIN labour_attendance_reports r ON r.id = l.report_id WHERE r.organization_id = :o "
                     "ORDER BY l.trade, l.headcount"), {"o": w.org}
            )
        ).all()
    return [*map(tuple, report), *map(tuple, lines)]


async def test_the_same_labour_saved_by_tap_writes_the_rows_todays_flow_writes(world):
    # Today's flow: the message writes it as a draft, the Save tap confirms it.
    legacy = _gateway(world, draft=False)
    await _call(world, legacy, *LABOUR)
    await world.handler.settle_drafts(
        organization_id=str(world.org), user_id=world.user, keep=True,
        facts=[(f[0], f[1]) for f in [__import__("runtime.agent.save_button", fromlist=["fact_of"]).fact_of(h) for h in legacy.handled] if f],
    )
    today = await _labour_rows(world)
    assert today, "today's flow wrote nothing?"
    async with world.db.transaction() as conn:  # start over
        await conn.execute(text("DELETE FROM fact_reviews WHERE organization_id = :o"), {"o": world.org})
        await conn.execute(
            text("DELETE FROM labour_attendance_lines WHERE report_id IN "
                 "(SELECT id FROM labour_attendance_reports WHERE organization_id = :o)"), {"o": world.org}
        )
        await conn.execute(text("DELETE FROM labour_attendance_reports WHERE organization_id = :o"), {"o": world.org})

    drafted = _gateway(world, draft=True)
    await _call(world, drafted, *LABOUR)
    assert await _labour_rows(world) == []  # nothing before the tap
    await _gateway(world, draft=True).save_draft(await _open(world))

    assert await _labour_rows(world) == today


WORK = (SAVE_WORK_DONE, {"narrative": "plastering 50 sq ft done", "work_type": "plastering", "update_kind": "completed",
                         "quantities": [{"work_type": "plastering", "quantity": 50, "unit": "sq ft"}]})
ISSUE = (REPORT_ISSUE, {"issue_type": "WEATHER", "narrative": "rain stopped work", "delay_duration_minutes": 120})


async def test_work_and_an_issue_join_the_same_transaction_and_roll_back_with_it(world):
    gateway = _gateway(world, draft=True)
    for tool, args in (LABOUR, WORK, ISSUE):
        step = await _call(world, gateway, tool, args)
        assert step.status == "drafted", step
    assert [await _count(world, t) for t in ("labour_attendance_reports", "activities", "site_issues")] == [0, 0, 0]
    draft = await _open(world)

    failing = _gateway(world, draft=True, dispatcher=_FailsOn(world.router, 3))  # the issue write is refused
    reply = await failing.save_draft(draft)
    assert reply.text.startswith("Nothing was saved. Couldn't save"), reply.text
    assert [await _count(world, t) for t in ("labour_attendance_reports", "activities", "site_issues")] == [0, 0, 0]

    world.handler._dispatcher = world.router
    done = await _gateway(world, draft=True).save_draft(await _open(world))
    assert done.text.startswith("✅ Saved"), done.text
    assert [await _count(world, t) for t in ("labour_attendance_reports", "activities", "site_issues")] == [1, 1, 0]


async def test_the_one_reminder_is_queued_once_in_the_window_before_the_cutoff(world):
    from runtime.draft_reminder import RULE_PREFIX, queue_draft_reminders

    async with world.db.transaction() as conn:
        await conn.execute(
            text("UPDATE projects SET auto_generate_dpr = true, reporting_timezone = 'Asia/Kolkata', "
                 "reporting_cutoff_time = '18:00' WHERE id = :p"), {"p": uuid.UUID(world.actor.projects[0].id)}
        )
    gateway = _gateway(world, draft=True)
    await _call(world, gateway, *RECEIPT)
    draft = await _open(world)
    def at(hour: int, minute: int = 0) -> dt.datetime:  # an IST wall-clock time today, as UTC
        from zoneinfo import ZoneInfo

        today = dt.datetime.now(ZoneInfo("Asia/Kolkata")).date()
        return dt.datetime.combine(today, dt.time(hour, minute), ZoneInfo("Asia/Kolkata")).astimezone(dt.UTC)

    async with world.db.transaction() as conn:  # the card was last touched at 17:10 IST
        await conn.execute(
            text("UPDATE message_drafts SET updated_at = :at WHERE id = :i"), {"at": at(17, 10), "i": uuid.UUID(draft.id)}
        )

    async with world.db.transaction() as conn:
        assert await queue_draft_reminders(conn, now_utc=at(17, 20)) == 0  # outside the window and still being built
        assert await queue_draft_reminders(conn, now_utc=at(17, 40)) == 1  # 20 minutes before the cutoff, idle for half an hour
        assert await queue_draft_reminders(conn, now_utc=at(17, 50)) == 0  # one reminder, never a nag
        row = (
            await conn.execute(
                text("SELECT rule_key, recipient_user_id, payload FROM notifications WHERE organization_id = :o"),
                {"o": world.org},
            )
        ).mappings().one()
        reminded = (
            await conn.execute(text("SELECT reminded_at FROM message_drafts WHERE id = :i"), {"i": uuid.UUID(draft.id)})
        ).scalar_one()
    assert row["rule_key"] == f"{RULE_PREFIX}{draft.id}" and str(row["recipient_user_id"]) == world.user
    payload = row["payload"] if isinstance(row["payload"], dict) else __import__("json").loads(row["payload"])
    assert payload["message"].startswith("You have 1 card not saved: tap Save or Cancel.")
    assert [b["title"] for b in payload["buttons"]] == ["✅ Save", "❌ Cancel"]
    assert reminded is not None
    async with world.db.transaction() as conn:
        await conn.execute(text("DELETE FROM notifications WHERE organization_id = :o"), {"o": world.org})
