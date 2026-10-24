"""Application dependency wiring for the WhatsApp assistant runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import Request
from pydantic_settings import BaseSettings, SettingsConfigDict

from ingress.deduplication import DeduplicationStore, InMemoryDeduplicationStore
from ingress.media_ingestion import MetaMediaDownloader
from ingress.receiver import InMemoryNormalizedMessageStore, WhatsAppReceiver
from runtime.logging_ports import MessageLogger, TraceLogger

if TYPE_CHECKING:
    from backend.ports import ActorReader
    from channel.receipt import ReceiptRenderer
    from context.resolver import ContextResolver
    from interactions import InteractionHandler
    from mesiri.infrastructure.postgres.database import PostgresDatabase
    from mesiri_contracts.common.storage import ObjectStoragePort
    from runtime.expense_category_query import ExpenseCategoryQueryService
    from runtime.inventory_query import MaterialInventoryQueryService
    from runtime.material_catalog_query import MaterialCatalogQueryService
    from runtime.org_settings_query import OrganizationSettingsQueryService
    from runtime.queue import MessageEnqueuer
    from understanding.pipeline import UnderstandingPipeline
    from workflows import WorkflowRuntime


class Settings(BaseSettings):
    """Environment-backed configuration for WhatsApp ingress."""

    verify_token: str
    app_secret: str
    access_token: str
    phone_number_id: str = ""
    api_version: str = "v21.0"
    graph_base_url: str = "https://graph.facebook.com"
    dedup_ttl_hours: int = 24
    context_debug: bool = False
    # WA-12: comma-separated names of templates Meta has approved; see
    # channel/whatsapp/templates.py. Empty = never send a template.
    approved_templates: str = ""

    model_config = SettingsConfigDict(
        env_prefix="WHATSAPP_",
        env_file=".env",
        extra="ignore",
    )


@dataclass(slots=True)
class AppContainer:
    """Process-scoped dependency container."""

    settings: Settings
    http_client: httpx.AsyncClient
    deduplication_store: DeduplicationStore
    message_store: InMemoryNormalizedMessageStore
    receiver: WhatsAppReceiver
    # Durable ingress queue handle (see runtime/queue.py). None when running
    # against FakeRedis (dev/test) -- WhatsAppReceiver falls back to
    # asyncio.create_task in that case. connect()/disconnect() are called by
    # the lifespan handler, same lifecycle pattern as redis_client.
    message_enqueuer: MessageEnqueuer | None
    context_resolver: ContextResolver
    # The understanding pipeline (STT/vision/extraction). Held on the container
    # so out-of-band callers (e.g. the control-plane test harness in
    # admin/system_graph_router.py) can run process_inbound_message without
    # re-wiring providers; the webhook path uses the same instance.
    pipeline: UnderstandingPipeline
    workflow_runtime: WorkflowRuntime
    interaction_handler: InteractionHandler
    # Identity gate reader (M4). Exposed for the same reason as `pipeline` --
    # the control-plane test harness (admin/system_graph_router.py) replays
    # the exact same pre-pipeline fast-path order as _on_normalized below,
    # which starts with resolve_sender(actor_reader, wa_id).
    actor_reader: ActorReader
    # Read-only inventory lookups for the material.inventory_query workflow.
    # Exposed for the same reason as pipeline/actor_reader above.
    inventory_query: MaterialInventoryQueryService
    # Read-only catalog/units-of-measure lookups for the material/unit
    # resolution gate. Exposed for the same reason as inventory_query above.
    catalog_query: MaterialCatalogQueryService
    # Per-org tunable rules (e.g. which roles may add a material to the
    # catalog from WhatsApp). Exposed for the same reason as catalog_query.
    org_settings_query: OrganizationSettingsQueryService
    # Read-only expense category names for the extraction call's AI-side
    # category selection. Exposed for the same reason as catalog_query above.
    expense_category_query: ExpenseCategoryQueryService
    # Resolves receipt/attachment object keys into presigned URLs for the
    # dashboard's expense-attachment endpoints (backend/src/mesiri/
    # infrastructure/objectstorage/dependency.py's get_object_storage falls
    # back to `request.app.state.container.object_storage`, since this is
    # the actual production app -- see runtime/lifecycle.py -- not
    # backend/src/mesiri/http/app.py). Was already built here (used for
    # build_pipeline/WhatsAppReceiver below) but never exposed on the
    # container itself, so every attachment fetch 500'd with AttributeError.
    object_storage: ObjectStoragePort
    # Owns the one headless-Chromium instance used to render post-confirmation
    # receipt images (see channel/receipt/). close() is called by the
    # lifespan handler, same lifecycle pattern as material_db/redis_client.
    receipt_renderer: ReceiptRenderer
    # redis_client is either a real RedisClient (when MESIRI_REDIS__HOST is set)
    # or FakeRedis for local/test.  Both expose connect() / disconnect() so the
    # lifespan handler can manage the lifecycle without special-casing.
    redis_client: Any
    message_logger: MessageLogger
    trace_logger: TraceLogger
    # M8: owns the one transaction Material command execution runs in. connect()/
    # disconnect() are called by the lifespan handler, same as redis_client.
    material_db: PostgresDatabase
    # BE-18: writes the AI summary of a frozen DPR before its PDF is sent;
    # handed to the scheduler (runtime/automation_runner.py). None = no
    # summaries, DPRs go out as before.
    dpr_summary_writer: Any = None
    #: ``(sender) -> on_normalized``: the message handler with another sender
    #: (the control panel's test message). None in tests that build their own.
    simulate_handler: Any = None
    # SA-11: error alerts to the super admins on WhatsApp. Installed on the
    # root logger by the app and the worker (runtime/ops_alerts.py).
    ops_alerts: Any = None


def build_container(settings: Settings, http_client: httpx.AsyncClient) -> AppContainer:
    """Construct the application dependency container."""
    message_store = InMemoryNormalizedMessageStore()
    media_downloader = MetaMediaDownloader(
        client=http_client,
        access_token=settings.access_token,
        api_version=settings.api_version,
        graph_base_url=settings.graph_base_url,
    )

    # M4 identity gate, then M2 -> M3 -> M4 Context resolver -> reply.
    import logging as _logging

    from backend.postgres.actor import PostgresActorReader
    from backend.postgres.message_logger import PostgresMessageLogger
    from backend.postgres.trace_logger import PostgresTraceLogger
    from backend.postgres.workflow_instance import PostgresWorkflowInstanceRepository
    from channel.whatsapp.outbound import WhatsAppSender
    from context.runtime import build_context_resolver
    from interactions import build_interaction_handler
    from interactions.category_hint import CategoryHintStore
    from mesiri.application.materials.dispatcher import MaterialExecutionDispatcher
    from mesiri.application.materials.handlers import ExecuteConfirmedMaterialActionHandler
    from mesiri.application.materials.resolution import PostgresMaterialResolver
    from mesiri.bootstrap.settings import get_settings as _get_backend_settings
    from mesiri.infrastructure.objectstorage import build_object_storage

    # Object storage: FakeObjectStorage locally, R2 when
    # MESIRI_OBJECT_STORAGE__PROVIDER=r2 is set.
    #
    # Wrapped so a photo isn't fetched back out of R2 immediately after being
    # written to it: ingress downloads the bytes from Meta, uploads them, and
    # then understanding/pipeline.py's _read_media reads the very same key
    # again to hand to the vision/speech provider. The decorator answers that
    # one read from memory and drops the entry; every other call, and any
    # later read (e.g. the admin replay path), goes straight through to the
    # real adapter. See recent_writes_cache.py.
    from mesiri.infrastructure.objectstorage.recent_writes_cache import (
        RecentWritesCachingObjectStorage,
    )
    from mesiri.infrastructure.postgres.database import PostgresDatabase
    from mesiri.infrastructure.postgres.repositories.material_execution import (
        PostgresMaterialExecutionRepository,
    )
    from understanding.runtime import build_pipeline
    from workflows import WorkflowRegistry, WorkflowRuntime

    _backend_settings = _get_backend_settings()

    # The backend refuses to start on the fake adapter in production
    # (Settings.validate_runtime); the assistant historically did not, so it
    # would accept photos into an in-memory store that cannot outlive the
    # process and hands back memory:// URLs the dashboard shows as "Photo
    # unavailable". That reads as a broken feature and is a missing
    # environment variable.
    #
    # Logged rather than raised on purpose: refusing to boot would take
    # WhatsApp down entirely over photos, and attendance capture -- the part
    # that actually matters -- works fine without object storage. Loud in the
    # log, and visible on /health, without holding the rest hostage.
    from mesiri.bootstrap.settings import ObjectStorageProvider as _StorageProvider

    if (
        _backend_settings.environment.is_production_like
        and _backend_settings.object_storage.provider is _StorageProvider.FAKE
    ):
        _logging.getLogger("mesiri.startup").error(
            "object storage is the FAKE adapter in a %s environment -- every photo "
            "will be written to memory, lost on restart, and undisplayable in the "
            "dashboard. Set MESIRI_OBJECT_STORAGE__PROVIDER=local (with "
            "PUBLIC_BASE_URL and SIGNING_SECRET) or r2 with its endpoint and credentials.",
            _backend_settings.environment.value,
        )

    object_storage = RecentWritesCachingObjectStorage(build_object_storage(_backend_settings))

    # Redis for the active context store.  Use a real RedisClient when
    # MESIRI_REDIS__HOST is explicitly configured; fall back to FakeRedis.
    _real_redis_configured = bool(os.environ.get("MESIRI_REDIS__HOST"))
    if _real_redis_configured:
        from mesiri.infrastructure.redis.client import RedisClient

        redis_client = RedisClient(_backend_settings.redis)
    else:
        from mesiri.infrastructure.redis.client import FakeRedis

        redis_client = FakeRedis()

    # Message idempotency claims. RedisDeduplicationStore survives a restart
    # and works across the (multiple, per infra/mesiri.service) uvicorn
    # processes; InMemoryDeduplicationStore below loses every claim on
    # restart and is process-local, per its own docstring in
    # ingress/deduplication.py. Built here (after redis_client, not before
    # it) specifically so it can share the same real-vs-fake decision above
    # instead of always defaulting to the in-memory store regardless of
    # whether Redis is actually configured.
    if _real_redis_configured:
        from ingress.deduplication import RedisDeduplicationStore

        deduplication_store: DeduplicationStore = RedisDeduplicationStore(
            redis_client, ttl=timedelta(hours=settings.dedup_ttl_hours)
        )
    else:
        deduplication_store = InMemoryDeduplicationStore(
            ttl=timedelta(hours=settings.dedup_ttl_hours)
        )

    # Durable ingress queue (see runtime/queue.py): only wired up against a
    # real Redis, for the same reason RedisDeduplicationStore is -- FakeRedis
    # has no persistent backing store, so there is nothing for ARQ to
    # durably queue against. None in dev/test, and WhatsAppReceiver falls
    # back to its previous asyncio.create_task behaviour when `enqueue` is
    # None (see ingress/receiver.py). connect()/disconnect() happen in the
    # lifespan handler -- build_container itself is synchronous and can't
    # await opening the pool -- same lifecycle pattern as redis_client.
    message_enqueuer = None
    if _real_redis_configured:
        from runtime.queue import MessageEnqueuer

        message_enqueuer = MessageEnqueuer(_backend_settings.redis)

    # Ephemeral category-tap hint (see interactions/category_hint.py) -- same
    # redis_client as the active context store, never authoritative.
    category_hint_store = CategoryHintStore(redis_client)
    # The shared Plan store (ENTITY_RESOLUTION_PLAN.md / COMPOSITE_REQUEST_
    # PLAN_LAYER.md) -- one plan per user, same redis_client, same
    # never-authoritative principle. This layer's only current producer is
    # start_member_create_plan (the CREATE_USER -> ADD_PROJECT_MEMBER chain);
    # the composite-request plan layer's Phase 4 is a second producer into
    # this same store, not a second store.
    from planning.plan_store import PlanStore

    plan_store = PlanStore(redis_client)
    # A second handle onto the same recent-turns keys build_conversation_
    # memory's own RecentTurnsStore writes (below) -- RecentTurnsStore holds
    # no state of its own beyond the redis client, so two instances against
    # the same redis_client read/write the identical rows through Redis
    # itself, not through Python object identity. Needed here, standalone,
    # because build_conversation_memory only returns the loader/coordinator
    # pair, and start_member_create_plan's phone-number recall (see
    # runtime/inbound_journey/resume.py) is a third, independent reader.
    from memory.recent_turns import RecentTurnsStore

    recent_turns_store = RecentTurnsStore(redis_client)
    # Holds a genuinely new image awaiting "what is this photo for?" (see
    # interactions/pending_media.py and interactions/image_purpose.py) --
    # same redis_client, same never-authoritative principle.
    from interactions.pending_media import PendingMediaStore

    pending_media_store = PendingMediaStore(redis_client)

    # M8: the one transaction Material command execution runs in. connect()/
    # disconnect() happen in the lifespan handler (runtime/lifecycle.py), same
    # lifecycle pattern as redis_client.
    material_db = PostgresDatabase(_backend_settings.postgres)

    # BE-25: price every AI call and WhatsApp message, per company.
    from channel.whatsapp import usage as message_usage
    from mesiri.application.organizations.trial_usage import TrialUsageGuard
    from mesiri.application.usage.recorder import install_usage_recorder

    message_usage.set_sink(install_usage_recorder(material_db))

    pipeline = build_pipeline(object_storage, material_db, redis_client)
    context_resolver = build_context_resolver(redis=redis_client)
    from runtime.agent.cards import CardStore
    from runtime.agent.later import LaterStore
    from runtime.agent.work_site import WorkSite
    # WorkflowRegistry compiles each graph once and caches it — constructed
    # once here, never per message.
    workflow_registry = WorkflowRegistry()
    workflow_runtime = WorkflowRuntime(
        registry=workflow_registry, repo=PostgresWorkflowInstanceRepository()
    )
    material_execution_handler = ExecuteConfirmedMaterialActionHandler(
        db=material_db,
        repo=PostgresMaterialExecutionRepository(),
        resolver=PostgresMaterialResolver(),
    )
    material_dispatcher = MaterialExecutionDispatcher(material_execution_handler)
    # Expense capture (M9): same in-process capability-boundary wiring as
    # Materials above, reusing the same material_db transaction pool. The
    # resolver turns the free-text `category` collected in conversation into
    # an expense_categories.id at confirmation time (defense-in-depth,
    # mirrors PostgresMaterialResolver).
    from mesiri.application.expenses.dispatcher import ExpenseExecutionDispatcher
    from mesiri.application.expenses.handlers import RecordExpenseHandler
    from mesiri.application.expenses.resolution import PostgresExpenseCategoryResolver
    from mesiri.application.vendors.resolution import PostgresVendorResolver
    from mesiri.infrastructure.postgres.repositories.expense_execution import (
        PostgresExpenseExecutionRepository,
    )

    expense_execution_handler = RecordExpenseHandler(
        PostgresExpenseExecutionRepository(),
        db=material_db,
        resolver=PostgresExpenseCategoryResolver(),
        vendor_resolver=PostgresVendorResolver(),
    )
    expense_dispatcher = ExpenseExecutionDispatcher(expense_execution_handler)
    # Account admin (Finance Module Slice 6, account-admin scope): same
    # in-process capability-boundary wiring as Expenses above. The resolver
    # finds the existing account by name for rename/deactivate, or checks
    # for a name collision on create.
    from mesiri.application.finance.dispatcher import AccountAdminExecutionDispatcher
    from mesiri.application.finance.handlers import ManageMoneyAccountHandler
    from mesiri.application.finance.resolution import PostgresAccountLookupResolver
    from mesiri.infrastructure.postgres.repositories.account_admin_execution import (
        PostgresAccountAdminExecutionRepository,
    )

    account_admin_execution_handler = ManageMoneyAccountHandler(
        PostgresAccountAdminExecutionRepository(),
        db=material_db,
        resolver=PostgresAccountLookupResolver(),
    )
    account_admin_dispatcher = AccountAdminExecutionDispatcher(account_admin_execution_handler)
    # Transfers (Finance Module Slice 3): same in-process capability-boundary
    # wiring as account admin above. The resolver re-verifies both accounts
    # are still active at confirm time -- the WhatsApp workflow already
    # resolved from/to to real account ids during slot-fill, so this is
    # defense-in-depth, not name resolution.
    from mesiri.application.finance.transfer_dispatcher import TransferExecutionDispatcher
    from mesiri.application.finance.transfer_handler import TransferMoneyHandler
    from mesiri.application.finance.transfer_resolution import PostgresTransferAccountResolver
    from mesiri.infrastructure.postgres.repositories.transfer_execution import (
        PostgresTransferExecutionRepository,
    )

    transfer_execution_handler = TransferMoneyHandler(
        PostgresTransferExecutionRepository(),
        db=material_db,
        resolver=PostgresTransferAccountResolver(),
    )
    transfer_dispatcher = TransferExecutionDispatcher(transfer_execution_handler)
    # Reversal (Finance Module Slice 7): same in-process capability-boundary
    # wiring as transfer above. The resolver re-verifies the target still
    # exists and hasn't already been reversed/voided at confirm time -- the
    # WhatsApp workflow already resolved "the most recent expense/transfer"
    # into a concrete id during seeding (runtime/inbound_journey.py), so this
    # is defense-in-depth, not name resolution.
    from mesiri.application.finance.reverse_dispatcher import ReverseExecutionDispatcher
    from mesiri.application.finance.reverse_handler import ReverseTransactionHandler
    from mesiri.application.finance.reverse_resolution import PostgresReverseTargetResolver
    from mesiri.infrastructure.postgres.repositories.reverse_execution import (
        PostgresReverseExecutionRepository,
    )

    reverse_execution_handler = ReverseTransactionHandler(
        PostgresReverseExecutionRepository(),
        db=material_db,
        resolver=PostgresReverseTargetResolver(),
    )
    reverse_dispatcher = ReverseExecutionDispatcher(reverse_execution_handler)
    # Routes a confirmed action to the dispatcher registered for its
    # action_type -- InteractionHandler only ever holds one ExecutionDispatcher.
    from interactions.execution_router import ActionTypeRoutingDispatcher

    # Labour attendance (Phase 5): same in-process capability-boundary wiring
    # as Materials above, reusing the same material_db transaction pool. No
    # resolver, unlike Materials -- worker matching already happened in the
    # workflow before confirmation (see application/labour/handlers.py).
    from mesiri.application.labour.dispatcher import LabourExecutionDispatcher
    from mesiri.application.labour.handlers import ExecuteConfirmedLabourAttendanceHandler
    from mesiri.infrastructure.postgres.repositories.labour_execution import (
        PostgresLabourExecutionRepository,
    )
    from mesiri_contracts.assistant.draft_action import DraftActionType

    labour_execution_handler = ExecuteConfirmedLabourAttendanceHandler(
        db=material_db,
        repo=PostgresLabourExecutionRepository(),
    )
    labour_dispatcher = LabourExecutionDispatcher(labour_execution_handler)

    # Activity creation (Daily Reporting, Phase 3): same in-process
    # capability-boundary wiring as Materials/Labour above, reusing the same
    # material_db transaction pool. The resolver re-verifies each stated
    # quantity's unit against units_of_measure at confirm time (defense-in-
    # depth, mirrors PostgresMaterialResolver) -- location/work-package
    # resolution is a separate gate (plan §1B.2) that hasn't been built yet,
    # so those fields simply stay null when unresolved (P4).
    from mesiri.application.progress.dispatcher import (
        AddProgressUpdateExecutionDispatcher,
        CloseSiteIssueExecutionDispatcher,
        CorrectActivityQuantityExecutionDispatcher,
        CreateActivityExecutionDispatcher,
        ReportSiteIssueExecutionDispatcher,
    )
    from mesiri.application.progress.handlers import (
        ExecuteConfirmedAddProgressUpdateHandler,
        ExecuteConfirmedCloseSiteIssueHandler,
        ExecuteConfirmedCorrectActivityQuantityHandler,
        ExecuteConfirmedCreateActivityHandler,
        ExecuteConfirmedReportSiteIssueHandler,
    )
    from mesiri.application.progress.resolution import PostgresProgressUnitResolver
    from mesiri.infrastructure.postgres.repositories.progress_execution import (
        PostgresProgressExecutionRepository,
    )

    progress_execution_repo = PostgresProgressExecutionRepository()
    progress_unit_resolver = PostgresProgressUnitResolver()
    create_activity_handler = ExecuteConfirmedCreateActivityHandler(
        db=material_db,
        repo=progress_execution_repo,
        resolver=progress_unit_resolver,
    )
    create_activity_dispatcher = CreateActivityExecutionDispatcher(create_activity_handler)
    # Activity Continuation (Daily Reporting): same repo/resolver as Activity
    # creation above -- both commands persist to the same tables via
    # PostgresProgressExecutionRepository, so there is exactly one instance
    # of each, shared by both handlers, same as Material's receipt/usage
    # commands share one dispatcher.
    add_progress_update_handler = ExecuteConfirmedAddProgressUpdateHandler(
        db=material_db,
        repo=progress_execution_repo,
        resolver=progress_unit_resolver,
    )
    add_progress_update_dispatcher = AddProgressUpdateExecutionDispatcher(
        add_progress_update_handler
    )
    # Activity Quantity Correction (ADR-D14): same repo/resolver as Activity
    # creation/continuation above -- correct_activity_quantity_success
    # composes PostgresProgressReadRepository.correct_progress_update (a
    # different repository, the dashboard-facing one) for the actual write,
    # same cross-repository reasoning reverse_execution.py's activity
    # branch already uses; this repo/resolver only own the idempotency
    # claim, outbox event, and workflow transition around that call.
    correct_activity_quantity_handler = ExecuteConfirmedCorrectActivityQuantityHandler(
        db=material_db,
        repo=progress_execution_repo,
        resolver=progress_unit_resolver,
    )
    correct_activity_quantity_dispatcher = CorrectActivityQuantityExecutionDispatcher(
        correct_activity_quantity_handler
    )
    # Site Issue Report: same repo as Activity creation/continuation above --
    # all three commands persist to tables PostgresProgressExecutionRepository
    # owns, so this is the same shared instance, not a new one. No resolver
    # (issue_type/severity are closed enums, nothing to resolve).
    report_site_issue_handler = ExecuteConfirmedReportSiteIssueHandler(
        db=material_db,
        repo=progress_execution_repo,
    )
    report_site_issue_dispatcher = ReportSiteIssueExecutionDispatcher(report_site_issue_handler)
    # Site Issue Close-out (acknowledge/resolve/wont_fix/cancel/reopen): same repo as the
    # three Progress handlers above -- no resolver here either (the
    # CURRENT-status re-check is inlined in persist_close_site_issue_success
    # itself, since it's a single self-contained row check, not a
    # cross-repository lookup like Reversal's).
    close_site_issue_handler = ExecuteConfirmedCloseSiteIssueHandler(
        db=material_db,
        repo=progress_execution_repo,
    )
    close_site_issue_dispatcher = CloseSiteIssueExecutionDispatcher(close_site_issue_handler)
    # Project creation: same in-process capability-boundary wiring as the
    # Progress handlers above, reusing the same material_db transaction
    # pool. No resolver -- there is nothing to look up (create is the only
    # action, unlike account admin's rename/deactivate).
    from mesiri.application.projects.create_dispatcher import CreateProjectExecutionDispatcher
    from mesiri.application.projects.create_site_dispatcher import CreateSiteExecutionDispatcher
    from mesiri.application.projects.handlers import CreateProjectHandler, CreateSiteHandler
    from mesiri.infrastructure.postgres.repositories.project_execution import (
        PostgresCreateProjectExecutionRepository,
    )
    from mesiri.infrastructure.postgres.repositories.site_execution import (
        PostgresCreateSiteExecutionRepository,
    )

    create_project_handler = CreateProjectHandler(
        PostgresCreateProjectExecutionRepository(),
        db=material_db,
    )
    create_project_dispatcher = CreateProjectExecutionDispatcher(create_project_handler)
    # Site creation (under an existing project resolved by context): same
    # in-process capability-boundary wiring as Project creation above.
    create_site_handler = CreateSiteHandler(
        PostgresCreateSiteExecutionRepository(),
        db=material_db,
    )
    create_site_dispatcher = CreateSiteExecutionDispatcher(create_site_handler)
    # Automation setup: same in-process capability-boundary wiring as
    # Project/Site creation above. name_resolver turns audience_names into
    # audience_user_ids right
    # before persist (see application/automations/handlers.py).
    from mesiri.application.automations.create_dispatcher import (
        CreateAutomationExecutionDispatcher,
    )
    from mesiri.application.automations.handlers import CreateAutomationHandler
    from mesiri.application.automations.name_resolution import PostgresAudienceNameResolver
    from mesiri.infrastructure.postgres.repositories.automation_execution import (
        PostgresCreateAutomationExecutionRepository,
    )

    create_automation_handler = CreateAutomationHandler(
        PostgresCreateAutomationExecutionRepository(),
        PostgresAudienceNameResolver(),
        db=material_db,
    )
    create_automation_dispatcher = CreateAutomationExecutionDispatcher(create_automation_handler)

    # Add project member: same in-process capability-boundary wiring as
    # Project/Site creation above.
    from mesiri.application.projects.add_member_dispatcher import (
        AddProjectMemberExecutionDispatcher,
    )
    from mesiri.application.projects.handlers import AddProjectMemberHandler
    from mesiri.application.projects.name_resolution import PostgresMemberNameResolver
    from mesiri.infrastructure.postgres.repositories.add_project_member_execution import (
        PostgresAddProjectMemberExecutionRepository,
    )

    add_project_member_handler = AddProjectMemberHandler(
        PostgresAddProjectMemberExecutionRepository(),
        PostgresMemberNameResolver(),
        db=material_db,
    )
    add_project_member_dispatcher = AddProjectMemberExecutionDispatcher(
        add_project_member_handler
    )

    # Create user: same in-process capability-boundary wiring as
    # Project/Site creation above.
    from mesiri.application.identity.create_user_dispatcher import CreateUserExecutionDispatcher
    from mesiri.application.identity.handlers import CreateUserHandler
    from mesiri.infrastructure.postgres.repositories.create_user_execution import (
        PostgresCreateUserExecutionRepository,
    )

    create_user_handler = CreateUserHandler(
        PostgresCreateUserExecutionRepository(),
        db=material_db,
    )
    create_user_dispatcher = CreateUserExecutionDispatcher(create_user_handler)

    execution_dispatcher = ActionTypeRoutingDispatcher(
        {
            DraftActionType.RECORD_MATERIAL_RECEIPT: material_dispatcher,
            DraftActionType.RECORD_MATERIAL_USAGE: material_dispatcher,
            DraftActionType.TRANSFER_MATERIAL: material_dispatcher,
            DraftActionType.RECORD_EXPENSE: expense_dispatcher,
            DraftActionType.MANAGE_MONEY_ACCOUNT: account_admin_dispatcher,
            DraftActionType.TRANSFER_MONEY: transfer_dispatcher,
            DraftActionType.REVERSE_TRANSACTION: reverse_dispatcher,
            DraftActionType.RECORD_LABOUR_ATTENDANCE: labour_dispatcher,
            DraftActionType.CREATE_ACTIVITY: create_activity_dispatcher,
            DraftActionType.ADD_PROGRESS_UPDATE: add_progress_update_dispatcher,
            DraftActionType.CORRECT_ACTIVITY_QUANTITY: correct_activity_quantity_dispatcher,
            DraftActionType.RECORD_SITE_ISSUE: report_site_issue_dispatcher,
            DraftActionType.CLOSE_SITE_ISSUE: close_site_issue_dispatcher,
            DraftActionType.CREATE_PROJECT: create_project_dispatcher,
            DraftActionType.CREATE_SITE: create_site_dispatcher,
            DraftActionType.CREATE_AUTOMATION: create_automation_dispatcher,
            DraftActionType.ADD_PROJECT_MEMBER: add_project_member_dispatcher,
            DraftActionType.CREATE_USER: create_user_dispatcher,
        }
    )
    # Read-only inventory lookups for the material.inventory_query workflow --
    # reuses the same material_db connection pool, never opens a write
    # transaction. See runtime/inventory_query.py.
    from runtime.inventory_query import MaterialInventoryQueryService

    inventory_query = MaterialInventoryQueryService(material_db)
    # Read-only catalog/units-of-measure lookups for the material/unit
    # resolution gate -- same reasoning and same material_db as
    # inventory_query above. See runtime/material_catalog_query.py.
    from runtime.material_catalog_query import MaterialCatalogQueryService

    catalog_query = MaterialCatalogQueryService(material_db)
    # Per-org settings (which roles may add a material from WhatsApp, etc) --
    # same reasoning and same material_db as catalog_query above. See
    # runtime/org_settings_query.py.
    from runtime.org_settings_query import OrganizationSettingsQueryService
    from runtime.save_first import SaveFirstService

    org_settings_query = OrganizationSettingsQueryService(material_db)
    # Read-only expense category names, fed into the extraction call so the
    # AI can pick from the org's real categories -- same reasoning and same
    # material_db as catalog_query above. See runtime/expense_category_query.py.
    from runtime.expense_category_query import ExpenseCategoryQueryService

    expense_category_query = ExpenseCategoryQueryService(material_db, redis=redis_client)
    # Read-only money-account lookups + lazy default-account bootstrap, fed
    # into expense_capture's "which account?" slot (Finance Module Slice 1)
    # -- same reasoning and same material_db as catalog_query above. See
    # runtime/money_account_query.py.
    from runtime.money_account_query import MoneyAccountQueryService

    money_account_query = MoneyAccountQueryService(material_db)
    # Resolves a petty cash recipient's name into their employee-advance
    # Resolves "the most recent expense/transfer" for the reverse workflow's
    # target (Finance Module Slice 7) -- same reasoning and same material_db
    # as catalog_query above. See runtime/reversal_query.py.
    from runtime.reversal_query import ReversalTargetQueryService

    reversal_query = ReversalTargetQueryService(material_db)
    # Flags a likely-duplicate expense before expense_capture's graph runs
    # (Finance Module Slice 8) -- same reasoning and same material_db as
    # catalog_query above. See runtime/duplicate_expense_query.py.
    from runtime.duplicate_expense_query import DuplicateExpenseQueryService

    duplicate_expense_query = DuplicateExpenseQueryService(material_db)
    # Workforce register reads for the Labour attendance workflow. Now the
    # real reader (2026-07-27): workforce_workers exists, has dashboard CRUD,
    # and labour_attendance_lines gives genuine "worked here before" signals.
    # Until this line changed, a worker added on the dashboard was invisible
    # to WhatsApp matching -- the register was real but nothing read it.
    from runtime.workforce_query import PostgresWorkforceQueryService

    workforce_query = PostgresWorkforceQueryService(material_db)
    # Open-activity lookup for the Activity Continuation workflow (Daily
    # Reporting) -- resolves which Activity "finished plastering" continues,
    # before the graph runs. Reuses the same pool; never opens a write
    # transaction. See runtime/activity_query.py.
    from runtime.activity_query import ActivityQueryService

    activity_query = ActivityQueryService(material_db)
    # Direct evidence attach for #2 Batch Media's "Site Update" photo
    # purpose -- never a workflow (see AttachEvidenceCommand's docstring).
    # Reuses the same pool; opens its own write transaction only when
    # attach_photos is actually called. See runtime/evidence_query.py.
    from runtime.evidence_query import EvidenceAttachService

    evidence_query = EvidenceAttachService(material_db)
    # Answers "has this number ever messaged us before?", the one thing the
    # long-dead is_first_message flag needed. See first_message_query.py.
    from runtime.first_message_query import FirstMessageQueryService

    first_message_query = FirstMessageQueryService(material_db)
    # "add Ravi to the project": the name against the org's active users before
    # a draft (ENTITY_RESOLUTION_PLAN.md ADR-E1), for the agent's add_member.
    from runtime.entity_resolution.member_resolution import MemberNameResolutionService

    member_resolver = MemberNameResolutionService(material_db)
    # "the JCB is fixed": the latest site issue an action may change, for the
    # agent's update_issue.
    from runtime.site_issue_query import SiteIssueTargetQueryService

    site_issue_query = SiteIssueTargetQueryService(material_db)
    # #25 AI Follow-up: remembers which Activity a proactive "want to
    # attach a completion photo?" offer was about, so the next photo skips
    # the normal purpose picker. See interactions/completion_photo_hint.py.
    from interactions.completion_photo_hint import CompletionPhotoHintStore

    completion_photo_hint_store = CompletionPhotoHintStore(redis_client)

    # Remembers which attendance report the next photo belongs to, after
    # Mesiri offers a team photo. Same pop-once contract, same reasoning --
    # see interactions/team_photo_hint.py.
    from interactions.team_photo_hint import TeamPhotoHintStore

    team_photo_hint_store = TeamPhotoHintStore(redis_client)

    # The choices on the last reply, so a typed "undo" / "photo" / number
    # works like the tap (request [45]).
    from interactions.offered_choices import OfferedChoicesStore

    offered_choices_store = OfferedChoicesStore(redis_client)

    # Chained project/site setup offer: remembers which project a tap on
    # "Add a Site now" / "Add a Teammate now" is about, between the offer
    # message and the button tap. See interactions/project_setup_offer.py.
    from interactions.project_setup_offer import ProjectSetupOfferStore

    project_setup_offer_store = ProjectSetupOfferStore(redis_client)
    # M19 conversation memory -- current project/site (existing
    # RedisActiveContextStore), current activity/date (new), and a capped
    # recent-turns history, composed behind one loader/coordinator pair. See
    # memory/requirements.py for the full scope list and why each is a HINT,
    # never authoritative. Requires workflow_runtime (built below) for its
    # pending-confirmation check, so this line must stay after that build.
    from memory import build_conversation_memory

    memory_loader, memory_coordinator = build_conversation_memory(redis_client, workflow_runtime)
    # Read-only attendance lookups for the labour.query workflow ("how many
    # workers today?"). Reuses the same pool; never opens a write
    # transaction. See runtime/labour_query_service.py.
    from runtime.labour_query_service import LabourQueryService

    labour_query_service = LabourQueryService(material_db)
    # Read-only progress/activity + open-issue lookups for the activity.query
    # workflow (#17 Search / Ask Mesiri -- "what did I log today?"). Reuses
    # the same pool; never opens a write transaction. See
    # runtime/activity_search_service.py.
    from runtime.activity_search_service import ActivitySearchService

    activity_search_service = ActivitySearchService(material_db)
    # Status lookup for the dpr.request workflow ("send me today's DPR" --
    # #16 Daily Report Generation). Reuses the same pool; never opens a
    # write transaction. See runtime/dpr_request_query.py.
    from runtime.dpr_request_query import DprRequestQueryService

    dpr_request_query = DprRequestQueryService(material_db)
    # Project team-size lookup for the project.detail_query workflow ("give
    # me all details of this project/site"). Reuses the same pool; never
    # opens a write transaction. See runtime/project_detail_query.py.
    from runtime.project_detail_query import ProjectDetailQueryService

    project_detail_query = ProjectDetailQueryService(material_db)
    # Flags a vendor name that doesn't match any existing active vendor, fed
    # into expense_capture's "create this vendor?" slot -- same reasoning and
    # same material_db as catalog_query above. See runtime/vendor_query.py.
    from runtime.vendor_query import VendorQueryService

    vendor_query = VendorQueryService(material_db)
    # Read-only expense list/sum lookups for the expense-query workflow
    # (Finance Module Slice 2) -- same reasoning and same material_db as
    # money_account_query above. See runtime/expense_query_service.py.
    from runtime.expense_query_service import ExpenseQueryService

    expense_query_service = ExpenseQueryService(material_db)
    from mesiri_ai.resolver import DynamicAIProviderResolver

    trace_logger: TraceLogger = PostgresTraceLogger()

    ai_resolver = DynamicAIProviderResolver(material_db, redis_client, _backend_settings)
    # WA-11: conversational replies in the sender's language, using the same
    # resolver; the language each sender speaks is remembered in Redis.
    from runtime.reply_language import ReplyComposer, UserLanguageStore

    reply_composer = ReplyComposer(ai_resolver)
    # BE-18: the DPR summary uses the same resolver (generate_json).
    from runtime.dpr_summary import DprSummaryWriter

    dpr_summary_writer = DprSummaryWriter(ai_resolver)
    user_language_store = UserLanguageStore(redis_client)
    # Resolves a picker reply the deterministic matcher (workflows/slots.py's
    # match_slot_answer) couldn't -- e.g. "New cause it's 3rd floor" instead
    # of a bare number or "This is new work". Same resolver as above:
    # generate_json already always routes to Gemini (see resolver.py), so
    # this needs no new provider config. Only consulted after
    # provide_input()'s first, free deterministic pass re-asks -- see
    # interactions/handler.py's handle_slot_answer.
    from interactions.llm_slot_classifier import AdapterSlotAnswerClassifier

    slot_answer_classifier = AdapterSlotAnswerClassifier(ai_resolver, trace_logger=trace_logger)
    # Post-confirmation receipt image (see AGENTS.md's Module Placement Log
    # and channel/receipt/). One long-lived headless-Chromium instance for
    # the whole process -- ReceiptRenderer launches it lazily on first
    # render, not here, so container construction never needs a browser
    # installed. Closed in runtime/lifecycle.py's shutdown handler.
    from channel.receipt import ReceiptRenderer, RecordReceiptBuilder

    receipt_renderer = ReceiptRenderer()
    async def _localize_card(texts, actor):  # type: ignore[no-untyped-def]
        """The card's free text in the sender's language when they write it in
        its own script (request 57, B4); English letters / English: unchanged."""
        from runtime.reply_language import normalize_language

        language, script = await user_language_store.get_profile(user_id=actor.user_id)
        if normalize_language(language) is None or script == "latin":
            return {}
        unique = list(dict.fromkeys(texts))
        composed = await reply_composer.compose("\n".join(unique), language=language, script=script)
        lines = composed.split("\n")
        return dict(zip(unique, lines, strict=True)) if len(lines) == len(unique) else {}

    record_receipt_builder = RecordReceiptBuilder(receipt_renderer, localize=_localize_card)
    # M7: resolves a confirmation reply into the pending workflow, or None
    # (fall through to the normal understanding journey). M8: when a CONFIRM
    # resolves to CONFIRMED, the dispatcher executes the domain write
    # synchronously in the same request and the reply reflects the real outcome.
    interaction_handler = build_interaction_handler(
        workflow_runtime,
        dispatcher=execution_dispatcher,
        receipt_builder=record_receipt_builder,
        memory_coordinator=memory_coordinator,
        completion_photo_hint_store=completion_photo_hint_store,
        slot_answer_classifier=slot_answer_classifier,
        # WA-01: capture updates are saved straight away as drafts unless the
        # company's capture_mode is switched back to confirm_first.
        save_first=SaveFirstService(material_db, org_settings_query),
    )
    # WA-02: replies to a forwarded batch are held back for one summary.
    from runtime.forward_batch import BatchingSender, ForwardBatcher

    whatsapp_sender = WhatsAppSender(
        client=http_client,
        access_token=settings.access_token,
        phone_number_id=settings.phone_number_id,
        api_version=settings.api_version,
        graph_base_url=settings.graph_base_url,
    )
    sender = BatchingSender(whatsapp_sender)
    forward_window = float(os.environ.get("MESIRI_FORWARD_BATCH_SECONDS", "10") or 0)
    forward_batcher = (
        ForwardBatcher(redis=redis_client, sender=whatsapp_sender, window_seconds=forward_window)
        if forward_window > 0
        else None
    )

    # Backend capability boundary: create once, reuse the connection pool.
    # message_logger/trace_logger build their engine lazily on first use (see
    # their _get_engine()) so importing/constructing the container never
    # requires a live DB driver import — building it eagerly here broke that
    # and made container construction fail wherever asyncpg couldn't import.
    actor_reader = PostgresActorReader()
    message_logger: MessageLogger = PostgresMessageLogger()

    # SS-04: unknown numbers can start a free trial when self-serve signup is
    # switched on (platform setting, off by default).
    from interactions.signup_state import SignupStateStore
    from runtime.signup_journey import SignupJourney

    signup_journey = SignupJourney(
        sender=sender,
        store=SignupStateStore(redis_client),
        db=material_db,
        renderer=receipt_renderer,
    )

    # WA-09: an outside DPR contact's YES / STOP to the opt-in invite.
    from runtime.opt_in_journey import OptInJourney

    opt_in_journey = OptInJourney(db=material_db)

    # SS-13: a shared contact card adds that person to the team, through the
    # same CREATE_USER / ADD_PROJECT_MEMBER workflows as a typed request.
    from runtime.contact_share_journey import ContactShareJourney

    contact_share = ContactShareJourney(
        redis=redis_client,
        db=material_db,
        plan_store=plan_store,
        workflow_runtime=workflow_runtime,
        send_text=sender.send_text,
        send_image=sender.send_image,
        card_renderer=receipt_renderer,
    )

    # SS-05: "JOIN ACME-4821" from a new number asks the company's admins;
    # Approve goes on through the contact-share steps above.
    from channel.whatsapp.templates import approved_template_names
    from runtime.join_journey import JoinJourney
    from runtime.notification_query import NotificationSendQueueService

    join_journey = JoinJourney(
        sender=sender,
        db=material_db,
        redis=redis_client,
        contact_share=contact_share,
        # SS-12: an admin outside the 24 h window gets the join-request
        # template, once approved. The same last-message lookup the
        # notification sender uses.
        approved_templates=approved_template_names(settings.approved_templates),
        last_inbound_at=NotificationSendQueueService(material_db, actor_reader).last_inbound_at,
    )

    # SS-14: one setup question a day for a new company's owner; letterhead
    # and logo photos go to the Mesiri team's WhatsApp group.
    from runtime.inbound_journey import start_project_setup_followup
    from runtime.logo_from_whatsapp import LogoFromWhatsApp
    from runtime.setup_questions import SetupQuestions
    from runtime.team_notify import TeamNotifier

    team_notifier = TeamNotifier()

    # SA-11: errors to the super admins on WhatsApp; same 24 h window rule
    # and last-message lookup as the join request above.
    from runtime.ops_alerts import OpsAlerts

    ops_alerts = OpsAlerts(
        sender=sender,
        db=material_db,
        redis=redis_client,
        team_notifier=team_notifier,
        approved_templates=approved_template_names(settings.approved_templates),
        last_inbound_at=NotificationSendQueueService(material_db, actor_reader).last_inbound_at,
        live=_real_redis_configured,
    )

    # AI provider failures: one alert per hour (runtime/ai_failure_alert.py).
    from runtime.ai_failure_alert import install_ai_failure_alerts

    install_ai_failure_alerts(team_notifier, ops_alerts)
    setup_questions = SetupQuestions(
        db=material_db,
        redis=redis_client,
        storage=object_storage,
        notifier=team_notifier,
        workflow_runtime=workflow_runtime,
        start_site_followup=start_project_setup_followup,
    )

    # SS-17: the setup-progress card (card 3 of the onboarding cards).
    from runtime.onboarding_progress import OnboardingProgress

    onboarding_progress = OnboardingProgress(
        db=material_db,
        redis=redis_client,
        renderer=receipt_renderer,
        setup_questions=setup_questions,
        language_store=user_language_store,
    )

    # WA-04: taps on the evening message about a site's day.
    from runtime.site_day_review import SiteDayReview

    site_day_review = SiteDayReview(db=material_db)

    # SS-08: expired-trial replies and "CONTINUE" from a trial owner.
    from runtime.trial_journey import TrialJourney

    trial_journey = TrialJourney(db=material_db, notifier=team_notifier)

    from runtime.message_journey import build_message_handlers

    handler_deps: dict[str, Any] = dict(
        settings=settings,
        actor_reader=actor_reader,
        pipeline=pipeline,
        context_resolver=context_resolver,
        workflow_runtime=workflow_runtime,
        interaction_handler=interaction_handler,
        object_storage=object_storage,
        message_logger=message_logger,
        trace_logger=trace_logger,
        inventory_query=inventory_query,
        catalog_query=catalog_query,
        org_settings_query=org_settings_query,
        money_account_query=money_account_query,
        reversal_query=reversal_query,
        duplicate_expense_query=duplicate_expense_query,
        workforce_query=workforce_query,
        activity_query=activity_query,
        evidence_query=evidence_query,
        reply_composer=reply_composer,
        user_language_store=user_language_store,
        first_message_query=first_message_query,
        plan_store=plan_store,
        member_resolver=member_resolver,
        site_issue_query=site_issue_query,
        # Request [40]: the same resolver carries tool calling (routed by the
        # "agent" capability); every message goes to it.
        agent_provider=ai_resolver,
        recent_turns_store=recent_turns_store,
        labour_query_service=labour_query_service,
        activity_search_service=activity_search_service,
        dpr_request_query=dpr_request_query,
        project_detail_query=project_detail_query,
        vendor_query=vendor_query,
        expense_query_service=expense_query_service,
        pending_media_store=pending_media_store,
        category_hint_store=category_hint_store,
        completion_photo_hint_store=completion_photo_hint_store,
        team_photo_hint_store=team_photo_hint_store,
        offered_choices_store=offered_choices_store,
        # WA-45: today's site, on the resolver's own active-context slot.
        work_site=WorkSite(active_context=context_resolver.active_context, redis=redis_client),
        # Request 88: the latest card per sender, for undo and editing.
        cards=CardStore(redis_client),
        # WA-57: the parts of a message still to do, per sender.
        later=LaterStore(redis_client),
        # Request 91: the Stock card is drawn by the receipt's Chromium.
        card_renderer=receipt_renderer,
        project_setup_offer_store=project_setup_offer_store,
        memory_loader=memory_loader,
        memory_coordinator=memory_coordinator,
        signup_journey=signup_journey,
        opt_in_journey=opt_in_journey,
        forward_batcher=forward_batcher,
        contact_share=contact_share,
        join_journey=join_journey,
        setup_questions=setup_questions,
        onboarding_progress=onboarding_progress,
        # WA-13: logos sent on WhatsApp.
        logo_from_whatsapp=LogoFromWhatsApp(db=material_db, storage=object_storage),
        site_day_review=site_day_review,
        trial_journey=trial_journey,
        # SS-09: pause a trial company that runs past today's usage caps.
        trial_usage_guard=TrialUsageGuard(material_db),
        ops_alerts=ops_alerts,
    )
    _on_normalized, _mark_read_on_claim = build_message_handlers(sender=sender, **handler_deps)

    def simulate_handler(capturing_sender: Any) -> Any:
        """The control panel's test message (admin/system_graph_router.py):
        the very same handler, with a sender that captures the replies."""
        return build_message_handlers(sender=capturing_sender, **handler_deps)[0]

    receiver = WhatsAppReceiver(
        deduplication_store=deduplication_store,
        media_downloader=media_downloader,
        message_store=message_store,
        object_storage=object_storage,
        on_normalized=_on_normalized,
        on_message_claimed=_mark_read_on_claim,
        trace_logger=trace_logger,
        enqueue=message_enqueuer,
    )
    return AppContainer(
        settings=settings,
        http_client=http_client,
        deduplication_store=deduplication_store,
        message_store=message_store,
        receiver=receiver,
        message_enqueuer=message_enqueuer,
        context_resolver=context_resolver,
        pipeline=pipeline,
        actor_reader=actor_reader,
        inventory_query=inventory_query,
        catalog_query=catalog_query,
        org_settings_query=org_settings_query,
        expense_category_query=expense_category_query,
        object_storage=object_storage,
        receipt_renderer=receipt_renderer,
        workflow_runtime=workflow_runtime,
        interaction_handler=interaction_handler,
        redis_client=redis_client,
        message_logger=message_logger,
        trace_logger=trace_logger,
        material_db=material_db,
        dpr_summary_writer=dpr_summary_writer,
        simulate_handler=simulate_handler,
        ops_alerts=ops_alerts,
    )


def get_settings(request: Request) -> Settings:
    """Resolve application settings from the dependency container."""
    return get_container(request).settings


def get_container(request: Request) -> AppContainer:
    """Resolve the dependency container from the FastAPI application state."""
    return request.app.state.container


def get_receiver(request: Request) -> WhatsAppReceiver:
    """Resolve the WhatsApp ingress receiver."""
    return get_container(request).receiver
