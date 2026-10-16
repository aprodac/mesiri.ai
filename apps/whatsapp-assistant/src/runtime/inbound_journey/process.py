"""The orchestrator: `_plan_and_run` (shared by every resume_pending_report_
with_* function) and `process_inbound_message`, the entry point for a
freshly-received inbound message."""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

from backend.ports import ActorIdentity
from canonicalization import build_canonical_events, log_canonical_event
from channel.replies import ListRow, ReplySpec
from context.resolver import ContextResolver
from context.runtime import log_resolved_context
from interactions.category_hint import CategoryHintStore
from interactions.handler import InteractionHandler
from interactions.pending_report import PendingReportStore
from memory.context_loader import ConversationMemoryLoader
from memory.context_pack import ContextPack
from memory.coordinator import ConversationMemoryCoordinator
from mesiri_ai.ports.decomposition import DecompositionProvider
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.canonical_event import IntentCompleteness as _IntentCompleteness
from mesiri_contracts.assistant.normalized_message import NormalizedMessage
from mesiri_contracts.assistant.planner_decision import PlannerDecisionType, WorkflowKey
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from mesiri_contracts.assistant.v2.resolved_context import ResolvedContextV2
from mesiri_contracts.common.ids import new_id
from mesiri_contracts.common.storage import ObjectStoragePort
from planner import Planner, log_planner_decision
from planner.ambiguity import AmbiguityAction, caveat_text, decide_ambiguity
from planning.decomposition import build_plan_from_segments
from planning.plan import PlanOrigin
from planning.plan_store import PlanStore
from runtime.activity_query import ActivityQueryService
from runtime.activity_search_service import ActivitySearchService
from runtime.capability_help import CapabilityHelpService
from runtime.dpr_request_query import DprRequestQueryService
from runtime.duplicate_expense_query import DuplicateExpenseQueryService
from runtime.entity_resolution.member_resolution import MemberNameResolutionService
from runtime.escalation_query import EscalationCreateService
from runtime.expense_category_query import ExpenseCategoryQueryService
from runtime.expense_query_service import ExpenseQueryService
from runtime.first_message_query import FirstMessageQueryService
from runtime.inbound_journey._shared import _log
from runtime.inbound_journey.decomposed_plan import try_start_decomposed_plan
from runtime.inbound_journey.pending_decomposition import PendingDecompositionStore
from runtime.inbound_journey.reply import JourneyResult, _render_reply, _safe
from runtime.inbound_journey.seeding import (
    _MATERIAL_EVENT_TYPES,
    _build_query_pdf,
    _inject_inventory_context,
    _run_audience_name_gate,
    _run_material_unit_gates,
    _run_member_name_gate,
    _run_petty_cash_recipient_gate,
    _run_project_gate,
    _run_site_gate,
    _run_stock_gate,
    _seed_account_admin_role,
    _seed_account_candidates,
    _seed_activity_search,
    _seed_automation_setup_role,
    _seed_correction_target,
    _seed_dpr_request,
    _seed_duplicate_check,
    _seed_existing_attendance,
    _seed_finance_query_context,
    _seed_labour_query,
    _seed_open_activity,
    _seed_petty_cash_recipient,
    _seed_project_create_role,
    _seed_project_detail_query,
    _seed_reversal_target,
    _seed_site_issue_close_target,
    _seed_vendor_check,
    _seed_worker_candidates,
)
from runtime.inventory_query import MaterialInventoryQueryService
from runtime.labour_query_service import LabourQueryService
from runtime.logging_ports import MessageLogger, TraceLogger
from runtime.material_catalog_query import MaterialCatalogQueryService
from runtime.money_account_query import MoneyAccountQueryService
from runtime.noop_loggers import NoopMessageLogger, NoopTraceLogger
from runtime.org_settings_query import OrganizationSettingsQueryService
from runtime.petty_cash_query import PettyCashRecipientQueryService
from runtime.plan_executor import _progress_prefix
from runtime.project_detail_query import ProjectDetailQueryService
from runtime.reply_dispatch import send_reply_spec
from runtime.reply_language import ReplyComposer, UserLanguageStore
from runtime.reversal_query import ReversalTargetQueryService
from runtime.site_issue_query import SiteIssueTargetQueryService
from runtime.vendor_query import VendorQueryService
from runtime.workforce_query import WorkforceQueryService
from understanding.pipeline import UnderstandingPipeline
from workflows import (
    WorkflowResumeResult,
    WorkflowRunResult,
    WorkflowRunStatus,
    WorkflowRuntime,
    log_workflow_run,
)
from workflows import registry as workflow_registry


async def _company_modules(
    org_settings_query: OrganizationSettingsQueryService | None,
    actor: ActorIdentity | None,
) -> list[str] | None:
    """The sender's company's switched-on modules (WA-07), or None when there
    is no company to ask about. Never raises: the settings service already
    degrades to the default on a lookup failure."""
    if org_settings_query is None or actor is None or not actor.organization_id:
        return None
    return await org_settings_query.enabled_modules(organization_id=str(actor.organization_id))

# Matches runtime/account_admin_journey.py's _ACCOUNT_ADMIN_ROLES exactly --
# that module gates the deterministic-parser fast path; this gates the
# AI-understood path (SemanticType.ACCOUNT_ADMIN) so a disallowed role is
# refused the same way regardless of which path a message takes. Kept as a
# second literal (not imported) since the two modules are independent entry
# points by design (see account_admin_journey.py's docstring) -- if this
# ever drifts from that one, tests/unit/test_inbound_journey_account_admin_role.py
# and tests/unit/test_account_admin_journey.py both cover the same role set.
_ACCOUNT_ADMIN_ROLES = frozenset({"ADMIN", "FINANCE"})
_ACCOUNT_ADMIN_DENIED_REPLY = "⛔ Only an admin or finance user can manage accounts."

# Matches apps/whatsapp-assistant/src/projects/router.py's _CREATE_ROLES and
# application/projects/create_validation.py's _PROJECT_CREATE_ROLES exactly --
# same "should not even be an option" reasoning as _ACCOUNT_ADMIN_ROLES above,
# gating WorkflowKey.PROJECT_CREATE before a draft is ever built. Also gates
# WorkflowKey.SITE_CREATE -- create_site_validation.py's _SITE_CREATE_ROLES
# is the identical set, since the REST endpoint that creates a site under a
# project shares the same _CREATE_ROLES check as the one that creates the
# project itself. Also gates WorkflowKey.ADD_PROJECT_MEMBER --
# add_member_validation.py's role set is the same, mirroring
# projects/router.py's add_project_member REST endpoint (ADMIN-only there is
# stricter; this WhatsApp path additionally allows PROJECT_MANAGER, matching
# PROJECT_CREATE/SITE_CREATE's own precedent). Also gates
# WorkflowKey.CREATE_USER -- provisioning a brand new person's WhatsApp
# access is a bigger blast radius than any of the three above, but the same
# role set was the explicit call here (not ADMIN-only): see
# application/identity/create_user_validation.py.
_PROJECT_CREATE_ROLES = frozenset({"ADMIN", "PROJECT_MANAGER"})
_PROJECT_CREATE_DENIED_REPLY = "⛔ Only an admin or project manager can create a project."
_SITE_CREATE_DENIED_REPLY = "⛔ Only an admin or project manager can create a site."
_ADD_PROJECT_MEMBER_DENIED_REPLY = "⛔ Only an admin or project manager can add a project member."
_CREATE_USER_DENIED_REPLY = "⛔ Only an admin or project manager can add a new user."

# Matches domains/automations/router.py's _TARGET_OTHERS_ROLES and
# application/automations/create_validation.py's _TARGET_OTHERS_ROLES
# exactly. Unlike PROJECT_CREATE/SITE_CREATE above, this gate is
# conditional: a SELF digest ("send me the DPR") is open to anyone, so the
# check below only fires when the AI-extracted `audience` is anything other
# than SELF (a named person, a role, or "whoever hasn't reported").
_AUTOMATION_TARGET_OTHERS_ROLES = frozenset({"ADMIN", "PROJECT_MANAGER"})
_AUTOMATION_SETUP_DENIED_REPLY = (
    "⛔ Only an admin or project manager can set up an automation that messages someone else."
)


async def _plan_and_run(
    event: CanonicalEventV2,
    *,
    planner: Planner,
    workflow_runtime: WorkflowRuntime,
    inventory_query: MaterialInventoryQueryService | None = None,
    pending_report_store: PendingReportStore | None = None,
    actor_user_id: str | None = None,
) -> ReplySpec | None:
    """Run the planner and, if it starts a workflow, the workflow -- shared by
    every resume_pending_report_with_* function, so a resumed report goes
    through the exact same decision path a first-pass ACTIONABLE report
    would (see _inject_inventory_context for why inventory context is
    injected here rather than at canonicalization time).

    Also re-runs the stock sufficiency gate (_run_stock_gate) right after
    inventory context is injected, same as the first-pass journey -- a
    material-picker or unit-mismatch tap can be the leg that first makes a
    usage report ACTIONABLE, so the over-stock check can't only live before
    those gates. With no settings here the company counts as saving first,
    so the check doesn't ask (WA-03)."""
    await _inject_inventory_context(event, inventory_query)
    if pending_report_store is not None and actor_user_id is not None:
        stock_reply = await _run_stock_gate(
            event, pending_report_store=pending_report_store, actor_user_id=actor_user_id
        )
        if stock_reply is not None:
            return stock_reply
    decision = planner.decide(event)
    workflow_run: WorkflowRunResult | None = None
    if decision.decision_type is PlannerDecisionType.START_WORKFLOW:
        workflow_run = await workflow_runtime.start(decision, event)
    return _render_reply(workflow_run, None, decision, None)


async def process_inbound_message(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pipeline: UnderstandingPipeline,
    context_resolver: ContextResolver,
    planner: Planner,
    workflow_runtime: WorkflowRuntime,
    interaction_handler: InteractionHandler,
    send_text: Callable[[str, str], Awaitable[Any]],
    send_list: Callable[[str, str, str, tuple[ListRow, ...]], Awaitable[Any]] | None = None,
    send_button: Callable[[str, str, tuple[ListRow, ...]], Awaitable[Any]] | None = None,
    send_image: Callable[[str, bytes], Awaitable[Any]] | None = None,
    send_document: Callable[..., Awaitable[Any]] | None = None,
    object_storage: ObjectStoragePort | None = None,
    context_debug: bool = False,
    message_logger: MessageLogger | None = None,
    trace_logger: TraceLogger | None = None,
    actor: ActorIdentity | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    catalog_query: MaterialCatalogQueryService | None = None,
    org_settings_query: OrganizationSettingsQueryService | None = None,
    expense_category_query: ExpenseCategoryQueryService | None = None,
    money_account_query: MoneyAccountQueryService | None = None,
    petty_cash_query: PettyCashRecipientQueryService | None = None,
    reversal_query: ReversalTargetQueryService | None = None,
    site_issue_query: SiteIssueTargetQueryService | None = None,
    duplicate_expense_query: DuplicateExpenseQueryService | None = None,
    workforce_query: WorkforceQueryService | None = None,
    labour_query_service: LabourQueryService | None = None,
    vendor_query: VendorQueryService | None = None,
    expense_query_service: ExpenseQueryService | None = None,
    activity_query: ActivityQueryService | None = None,
    activity_search_service: ActivitySearchService | None = None,
    dpr_request_query: DprRequestQueryService | None = None,
    project_detail_query: ProjectDetailQueryService | None = None,
    semantic_hint: str | None = None,
    direction_hint: str | None = None,
    pending_report_store: PendingReportStore | None = None,
    category_hint_store: CategoryHintStore | None = None,
    memory_loader: ConversationMemoryLoader | None = None,
    memory_coordinator: ConversationMemoryCoordinator | None = None,
    escalation_query: EscalationCreateService | None = None,
    capability_help: CapabilityHelpService | None = None,
    first_message_query: FirstMessageQueryService | None = None,
    member_resolver: MemberNameResolutionService | None = None,
    decomposition: DecompositionProvider | None = None,
    plan_store: PlanStore | None = None,
    pending_decomposition_store: PendingDecompositionStore | None = None,
    reply_composer: ReplyComposer | None = None,
    user_language_store: UserLanguageStore | None = None,
) -> JourneyResult:
    mlog: MessageLogger = message_logger or NoopMessageLogger()
    # WA-11, set once understanding has run (see below).
    reply_language: str | None = None
    reply_user_message: str | None = message.text
    tlog: TraceLogger = trace_logger or NoopTraceLogger()
    correlation_id = message.correlation_id

    # WA-07: set for EVERY message (None when unknown), so one company's
    # modules can never carry over to the next message handled in this task.
    # Every menu, help reply and the module gate below read it.
    workflow_registry.set_enabled_modules(await _company_modules(org_settings_query, actor))

    # M19 conversation memory: loaded concurrently with understanding below
    # (independent reads -- see memory/context_loader.py's own docstring for
    # why this mirrors context/resolver.py's gather pattern). None whenever
    # the container didn't wire it (tests, or memory_loader not yet built) --
    # every consumer below already treats a None pack as "no opinion".
    memory_pack: ContextPack | None = None
    memory_pack_task: asyncio.Task[ContextPack] | None = None
    if memory_loader is not None and actor is not None and actor.organization_id:
        memory_pack_task = asyncio.ensure_future(
            memory_loader.load(organization_id=actor.organization_id, user_id=actor_user_id)
        )

    # --- Understanding stage ---
    t0 = time.perf_counter()
    try:
        expense_categories: list[str] | None = None
        if expense_category_query is not None and actor is not None and actor.organization_id:
            expense_categories = await expense_category_query.list_active_category_names(
                organization_id=actor.organization_id, created_by=actor.user_id
            )
        # Recorded separately from the AI work below: a traced image message
        # showed a 10.2s `understanding` stage whose provider calls only
        # accounted for ~7.1s, and this category lookup is the one database
        # round trip hiding inside the same measurement.
        categories_ms = int((time.perf_counter() - t0) * 1000)
        understanding = await pipeline.understand(
            message, semantic_hint=semantic_hint, expense_categories=expense_categories
        )
        # WA-11: remember the language this sender speaks, for every reply
        # (including the instant "hi" answer that never reaches the AI), and
        # keep what they said for answering small talk below.
        reply_language = understanding.detected_language
        reply_user_message = understanding.transcript or understanding.normalized_text or message.text
        if user_language_store is not None and understanding.detected_language:
            await user_language_store.remember(
                user_id=actor_user_id, detected_language=understanding.detected_language
            )
        await _safe(
            tlog.log_stage(
                correlation_id=correlation_id,
                stage="understanding",
                stage_payload={
                    **understanding.model_dump(mode="json"),
                    "expense_categories_ms": categories_ms,
                },
                duration_ms=int((time.perf_counter() - t0) * 1000),
                succeeded=True,
            )
        )
        if understanding.transcript:
            await _safe(
                mlog.update_body_text(
                    correlation_id=correlation_id, body_text=understanding.transcript
                )
            )
        for execution in understanding.provider_executions:
            await _safe(
                tlog.log_provider_execution(
                    correlation_id=correlation_id,
                    stage="understanding",
                    provider=execution.provider,
                    operation=execution.operation,
                    model=execution.model,
                    latency_ms=execution.latency_ms,
                    succeeded=execution.succeeded,
                    error_code=execution.error_code,
                )
            )

        # Low-confidence routing (#7) -- classified here, off understanding
        # alone, deliberately outside canonicalization (see
        # planner/ambiguity.py's module docstring for why). PROCEED is the
        # overwhelming common case and costs one pure-function call; the
        # caveat (if any) is applied later, only onto a confirmation prompt
        # the user is already about to read (see the reply-assembly step
        # near the end of this function). ESCALATE has no receiving domain
        # in this slice yet (#10 Human Review) -- logged as the documented
        # extension point rather than silently dropped.
        ambiguity_decision = decide_ambiguity(understanding)
        if ambiguity_decision.action is AmbiguityAction.ESCALATE:
            _log.warning(
                "ambiguity.escalate correlation_id=%s reason=%s",
                correlation_id,
                ambiguity_decision.reason,
            )
            # #10 Human Review: a durable review record, not a re-triggerable
            # draft -- there is no workflow, no context resolution, and
            # often no organization_id yet at this point (ESCALATE fires
            # right off understanding, before context resolution runs
            # below), so the snapshot captures what understanding itself
            # saw. Fire-and-forget: creating the review record must never
            # delay or fail the reply the user still gets this turn.
            if escalation_query is not None and actor is not None and actor.organization_id:
                asyncio.ensure_future(
                    escalation_query.create(
                        organization_id=actor.organization_id,
                        correlation_id=correlation_id,
                        reason=ambiguity_decision.reason,
                        snapshot={
                            "modality": understanding.input_modality.value,
                            "semantic_type": understanding.semantic_type.value,
                            "transcript": understanding.transcript,
                            "normalized_text": understanding.normalized_text,
                            "translated_text": understanding.translated_text,
                            "overall_confidence": understanding.overall_confidence.value,
                            "missing_fields": understanding.missing_fields,
                            "warnings": understanding.warnings,
                        },
                    )
                )
    except Exception as exc:
        await _safe(
            tlog.log_stage(
                correlation_id=correlation_id,
                stage="understanding",
                stage_payload=None,
                duration_ms=int((time.perf_counter() - t0) * 1000),
                succeeded=False,
                error_code=type(exc).__name__,
                error_message=str(exc),
            )
        )
        await _safe(mlog.mark_failed(correlation_id=correlation_id, error_code=type(exc).__name__))
        raise

    # --- Deterministic identity-lookup fast path (voice + defense-in-depth
    # for text) --- Text is normally already caught by interactions/handler.py's
    # pre-pipeline handle_whoami_trigger, before Understanding even runs (zero
    # AI cost). Voice can't be checked that early -- there's no text until
    # Sarvam transcribes and translates it ("njaan aara" -> "who am I" happens
    # in that same call) -- so this is the first point voice can be recognized.
    # Purely informational and never touches WorkflowRuntime, so it's safe to
    # answer even with a confirmation pending; actor is None only when the
    # caller didn't wire one in (e.g. some tests), in which case this simply
    # doesn't fire.
    #
    # "which text field do I check" is exactly what caused a real bug (the
    # duplicate here checked transcript, the original-language text, instead
    # of normalized_text, the translation); reading Understanding's own
    # answer makes that whole bug class structurally impossible, not just
    # fixed for today.
    # Note: WHOAMI_QUESTION fast-path has been removed to allow a full
    # LangGraph workflow to process identity lookups with AI-generated replies.

    # --- Slow-path interaction dispatch (correction / confirm / reject from classifier) ---
    workflow_resume: WorkflowResumeResult | None = None
    workflow_run: WorkflowRunResult | None = None

    original_text = understanding.transcript or understanding.normalized_text
    translated_text = understanding.translated_text
    if original_text:
        handled = await interaction_handler.handle_slow_path(
            actor_user_id, message, original_text, translated_text, actor=actor
        )
        if handled:
            # Phase 4: send confirmation text FIRST so the user sees it
            # immediately, then render the receipt PNG and send the image.
            await send_text(message.sender.wa_id, handled.reply_text)
            if handled.receipt_coro is not None and send_image is not None:
                try:
                    image_bytes = await handled.receipt_coro
                except Exception:  # noqa: BLE001 -- receipt failure must never drop the message
                    image_bytes = None
                if image_bytes is not None:
                    await send_image(message.sender.wa_id, image_bytes, caption=None)
            # Worker promotion is NOT hooked here. A confirmation reply is
            # resolved by handle_fast_path in runtime/dependencies.py, which
            # returns before this journey ever runs, and the answer to the
            # promotion offer arrives there too, via handle_slot_answer. Both
            # hooks live at those two call sites; placing them here looked
            # right and fired for nobody.
            await _safe(mlog.log_reply(correlation_id=correlation_id, reply=handled.reply_text))
            if handled.result.workflow_instance_id:
                await _safe(
                    mlog.link_workflow_instance(
                        correlation_id=correlation_id,
                        workflow_instance_id=handled.result.workflow_instance_id,
                    )
                )

            if isinstance(handled.result, WorkflowRunResult):
                workflow_run = handled.result
            else:
                workflow_resume = handled.result

            if not handled.unrelated_text:
                await _safe(
                    mlog.update_context(
                        correlation_id=correlation_id,
                        project_id=handled.project_id,
                        site_id=handled.site_id,
                    )
                )
                await _safe(mlog.mark_completed(correlation_id=correlation_id))
                return JourneyResult(
                    understanding=understanding,
                    resolved_context=None,
                    canonical_event=None,
                    planner_decision=None,
                    workflow_run=workflow_run,
                    workflow_resume=workflow_resume,
                )

            # The message contained both a workflow interaction AND an unrelated new request.
            # We rewrite the understanding output so the context resolver sees only the new intent.
            understanding.normalized_text = handled.unrelated_text
            understanding.transcript = handled.unrelated_text
            understanding.translated_text = handled.unrelated_text

    # --- Context resolution stage ---
    t0 = time.perf_counter()
    result = await context_resolver.resolve(message, understanding)
    resolved: ResolvedContextV2 | None = None
    canonical_event: CanonicalEventV2 | None = None
    planner_decision: PlannerDecisionV2 | None = None
    held_reply: ReplySpec | None = None

    if result.is_ok:
        resolved = result.unwrap()
        if context_debug:
            log_resolved_context(resolved)
        await _safe(
            tlog.log_stage(
                correlation_id=correlation_id,
                stage="context",
                stage_payload=resolved.model_dump(mode="json"),
                duration_ms=int((time.perf_counter() - t0) * 1000),
                succeeded=True,
            )
        )
        if message_logger:
            await _safe(
                message_logger.update_context(
                    correlation_id=correlation_id,
                    organization_id=resolved.organization_id,
                    project_id=resolved.project_id,
                    site_id=resolved.site_id,
                )
            )

        # --- Canonicalization stage ---
        t0 = time.perf_counter()
        try:
            # #1 Multi-Activity / #13 Cross-Module Trigger: build_canonical_events
            # (plural) may return more than one segment for a single message
            # (see canonicalization/builder.py's docstring for exactly which
            # cases, and which it does not yet cover). canonical_event stays
            # bound to events[0] for every line below, completely unchanged
            # from before this existed -- extra_segments (planned as part of
            # a Plan once the primary workflow starts, see the workflow stage
            # below -- Phase A2 of docs/execution/
            # UNIFIED_UNDERSTANDING_PIPELINE.md) is the only new state this
            # introduces into the first-pass journey.
            canonical_events = build_canonical_events(
                understanding,
                resolved,
                direction_hint=direction_hint,
                # Meta's forwarding markers, recorded at ingress. Read from
                # metadata rather than re-derived: normalization is the only
                # layer that sees Meta's raw `context` object.
                forwarded=bool(message.metadata.get("forwarded")),
                frequently_forwarded=bool(message.metadata.get("frequently_forwarded")),
            )
            canonical_event = canonical_events[0]
            extra_segments = canonical_events[1:]

            # Inject the loaded actor profile into the canonical event so the
            # WHO_AM_I workflow has the data it needs to generate a reply
            # without breaking the rule against workflows querying the database.
            if (
                canonical_event.event_type is CanonicalEventType.IDENTITY_LOOKUP_REQUESTED
                and actor is not None
            ):
                canonical_event.fields["actor_profile"] = {
                    "full_name": actor.full_name,
                    "role": actor.role,
                    "org_name": actor.org_name,
                    "projects": [asdict(p) for p in actor.projects] if actor.projects else [],
                    "sites": [asdict(s) for s in actor.sites] if actor.sites else [],
                    "query_text": understanding.translated_text or understanding.normalized_text,
                }

            # inventory_levels (for INVENTORY_QUERY_ASKED) and available_stock
            # (for MATERIAL_USAGE_REQUESTED's low-stock warning) are injected
            # in _plan_and_run instead of here -- project_id/site_id can still
            # change after this point (material/unit/project/site gates below
            # all run after canonicalization), so computing them this early
            # used to bake in whatever scope was resolved *before* any gate
            # asked a clarifying question, silently answering for the wrong
            # project/site once the user picked one. _plan_and_run runs after
            # every gate has settled, on both the first pass and every
            # resume_pending_report_with_* path, so it's the one place
            # guaranteed to see the final project_id/site_id.

            if context_debug:
                log_canonical_event(canonical_event)
            await _safe(
                tlog.log_stage(
                    correlation_id=correlation_id,
                    stage="canonicalization",
                    stage_payload=canonical_event.model_dump(mode="json"),
                    duration_ms=int((time.perf_counter() - t0) * 1000),
                    succeeded=True,
                )
            )
            # Self-tag: this message IS the origin of whatever interaction
            # follows (a material/unit/project gate hold, or a workflow start
            # further down). _complete_resume_leg re-reads this same
            # canonical_event.correlation_id on every later gate-resume leg,
            # so tagging it here is what lets a multi-turn report (voice note
            # -> material pick -> unit confirm -> project pick -> workflow
            # confirm) resolve to one interaction in the logs viewer.
            await _safe(
                mlog.set_interaction_group(
                    correlation_id=correlation_id, group_id=canonical_event.correlation_id
                )
            )
        except Exception as exc:
            await _safe(
                tlog.log_stage(
                    correlation_id=correlation_id,
                    stage="canonicalization",
                    stage_payload=None,
                    duration_ms=int((time.perf_counter() - t0) * 1000),
                    succeeded=False,
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                )
            )
            await _safe(
                mlog.mark_failed(correlation_id=correlation_id, error_code=type(exc).__name__)
            )
            raise

        # --- Composite-request decomposition (§9) ---
        # UNRECOGNIZED + semantic_type UNKNOWN is the exact signature a
        # multi-intent message produces (docs/execution/
        # COMPOSITE_REQUEST_PLAN_LAYER.md §9's real trace evidence: three
        # requests in one voice note came back "unknown" at high confidence,
        # because a single semantic_type field cannot represent three
        # intents -- "unknown" was the honest, correct single-intent answer).
        # Give it one chance to turn into a multi-step Plan before falling
        # through to the ordinary "I didn't understand" reply below.
        # try_start_decomposed_plan degrades to None on every failure mode
        # (not multi-intent, no decomposition provider wired, a provider
        # outage, nothing plannable) -- this is set as `held_reply` the same
        # way every other gate below is, so the planner/workflow stage is
        # skipped exactly when a gate already produced the full reply, with
        # no new branch of its own. Persists the plan and returns the §8
        # preview only -- nothing starts until the user taps Yes (see
        # resume_pending_plan_confirmation), so no WorkflowRuntime is passed.
        if held_reply is None and canonical_event.event_type is CanonicalEventType.UNRECOGNIZED:
            held_reply = await try_start_decomposed_plan(
                message_modality=message.modality,
                understanding=understanding,
                resolved=resolved,
                pipeline=pipeline,
                decomposition=decomposition,
                plan_store=plan_store,
                expense_categories=expense_categories,
                correlation_id=correlation_id,
                actor=actor,
                actor_user_id=actor_user_id,
                pending_decomposition_store=pending_decomposition_store,
                catalog_query=catalog_query,
                inventory_query=inventory_query,
                org_settings_query=org_settings_query,
            )

        # --- Member-name resolution gate ---
        # ADD_PROJECT_MEMBER's member_name is still free text at this point
        # -- resolve it against the org's real active users before the
        # planner or a confirmation prompt ever sees it, so an unmatched or
        # near-miss name (the live Hysam/Hisham bug, ENTITY_RESOLUTION_PLAN.md
        # §1) is caught here instead of as a late "couldn't find an active
        # user" after the user already tapped Yes. See _run_member_name_gate.
        if (
            held_reply is None
            and canonical_event.event_type is CanonicalEventType.ADD_PROJECT_MEMBER_REQUESTED
            and member_resolver is not None
            and pending_report_store is not None
        ):
            held_reply = await _run_member_name_gate(
                canonical_event,
                member_resolver=member_resolver,
                pending_report_store=pending_report_store,
                actor_user_id=actor_user_id,
                actor_role=actor.role if actor is not None else None,
            )

        # --- Automation audience gate ---
        # An automation's audience_names used to travel untouched to the
        # Handler, which resolved them at persist time and rejected the whole
        # command listing any it missed -- after the user had confirmed. Same
        # ADR-E1 move as the gates around it, asking one unknown name at a
        # time so the request survives instead of needing a retype.
        if (
            held_reply is None
            and member_resolver is not None
            and pending_report_store is not None
        ):
            held_reply = await _run_audience_name_gate(
                canonical_event,
                member_resolver=member_resolver,
                pending_report_store=pending_report_store,
                actor_user_id=actor_user_id,
            )

        # --- Petty-cash recipient gate ---
        # Same ADR-E1 move as the member gate above, for the one workflow
        # where the doomed confirmation moves money: an unmatched recipient
        # used to leave recipient_account_id unset, build the draft anyway,
        # and let transfer_validation reject it after the user tapped Yes.
        if (
            held_reply is None
            and member_resolver is not None
            and pending_report_store is not None
        ):
            held_reply = await _run_petty_cash_recipient_gate(
                canonical_event,
                member_resolver=member_resolver,
                pending_report_store=pending_report_store,
                actor_user_id=actor_user_id,
            )

        # --- Material/unit resolution gate ---
        # A material report can be otherwise complete (material_name/quantity/
        # unit all present -> ACTIONABLE) but the reported material/unit text
        # is still free text at this point -- resolve it against the catalog/
        # units_of_measure before the project gate or planner ever see it, so
        # an ambiguous ("cement" -> OPC/PPC) or Stock-Unit-mismatched report
        # is caught here, not as a late domain-validation failure after the
        # user already tapped Yes. See _run_material_unit_gates above.
        if (
            canonical_event.completeness is _IntentCompleteness.ACTIONABLE
            and canonical_event.event_type in _MATERIAL_EVENT_TYPES
            and catalog_query is not None
            and pending_report_store is not None
        ):
            held_reply = await _run_material_unit_gates(
                canonical_event,
                catalog_query=catalog_query,
                pending_report_store=pending_report_store,
                actor_user_id=actor_user_id,
                actor_role=actor.role if actor is not None else None,
                org_settings_query=org_settings_query,
            )

        # --- Project-selection gate ---
        # A report can be otherwise complete (material_name/quantity/unit all
        # present -> ACTIONABLE) but still have no project attached -- the
        # sender has access to more than one project and none is active/
        # default (see context/resolver.py's single-project convenience,
        # which only auto-picks when there's exactly one). Recording it
        # anyway would silently attach it to the wrong project, or fail late
        # at domain validation after the user already tapped Yes (the
        # original bug report this fixes). Ask which project instead, and
        # hold the report so the tap can resume it with project_id filled in.
        if held_reply is None and pending_report_store is not None:
            held_reply = await _run_project_gate(
                canonical_event,
                actor=actor,
                actor_user_id=actor_user_id,
                pending_report_store=pending_report_store,
            )

        # --- Site-selection gate ---
        # Once project is settled, a report/query can still be ambiguous
        # across the project's sites. Inventory queries offer "All Sites
        # Combined" (allow_combined=True); a material report being recorded
        # always has to land on one real site, so recording never offers
        # that option. See _run_site_gate for the single/zero-site shortcuts.
        if held_reply is None and pending_report_store is not None:
            held_reply = await _run_site_gate(
                canonical_event,
                actor=actor,
                actor_user_id=actor_user_id,
                pending_report_store=pending_report_store,
                allow_combined=canonical_event.event_type
                is CanonicalEventType.INVENTORY_QUERY_ASKED,
            )

        if held_reply is None:
            await _inject_inventory_context(canonical_event, inventory_query)

            # --- Stock sufficiency gate ---
            # Usage quantity vs available stock can only be checked once
            # available_stock is injected above -- block instead of letting
            # an over-limit usage through to the old cosmetic-only warning
            # (see _run_stock_gate).
            if pending_report_store is not None:
                held_reply = await _run_stock_gate(
                    canonical_event,
                    pending_report_store=pending_report_store,
                    actor_user_id=actor_user_id,
                    org_settings_query=org_settings_query,
                )

        if held_reply is None:
            # --- Planner stage ---
            t0 = time.perf_counter()
            try:
                planner_decision = planner.decide(canonical_event)
                if context_debug:
                    log_planner_decision(planner_decision)
                await _safe(
                    tlog.log_stage(
                        correlation_id=correlation_id,
                        stage="planner",
                        stage_payload=planner_decision.model_dump(mode="json"),
                        duration_ms=int((time.perf_counter() - t0) * 1000),
                        succeeded=True,
                    )
                )
            except Exception as exc:
                await _safe(
                    tlog.log_stage(
                        correlation_id=correlation_id,
                        stage="planner",
                        stage_payload=None,
                        duration_ms=int((time.perf_counter() - t0) * 1000),
                        succeeded=False,
                        error_code=type(exc).__name__,
                        error_message=str(exc),
                    )
                )
                await _safe(
                    mlog.mark_failed(correlation_id=correlation_id, error_code=type(exc).__name__)
                )
                raise

            # --- Capability help ---
            # A "how do I ...?" question reaches the planner as a
            # DIRECT_REPLY on GENERAL_QUESTION_ASKED, which until now
            # answered every one of them with a single hardcoded sentence
            # ("I can record what arrives on site and what gets used").
            # Match the question against the registry and hand the result to
            # the renderer on decision metadata -- the same injection shape
            # WHO_AM_I's actor_profile uses, and for the same reason: the
            # renderer is pure and the planner is deterministic, so neither
            # may make this call itself.
            if (
                capability_help is not None
                and planner_decision.reason is CanonicalEventType.GENERAL_QUESTION_ASKED
            ):
                question = understanding.translated_text or understanding.normalized_text
                matches = await capability_help.match(
                    question,
                    role=actor.role if actor is not None else None,
                    correlation_id=correlation_id,
                )
                planner_decision.metadata["capability_matches"] = [k.value for k in matches]
                if actor is not None and actor.role:
                    planner_decision.metadata["actor_role"] = actor.role

            if planner_decision.decision_type is PlannerDecisionType.START_WORKFLOW:
                # --- Workflow stage ---
                t0 = time.perf_counter()
                try:
                    if memory_pack_task is not None:
                        try:
                            memory_pack = await memory_pack_task
                        except Exception:  # noqa: BLE001 -- memory is a hint, never load-bearing
                            _log.warning(
                                "memory.pack_load_failed correlation_id=%s",
                                correlation_id,
                                exc_info=True,
                            )
                    # Run all 11 seed functions in parallel — each targets a
                    # different table and is fully independent of the others.
                    timezone_name = resolved.timezone if resolved else None
                    await asyncio.gather(
                        _seed_account_candidates(
                            canonical_event, planner_decision, money_account_query, actor
                        ),
                        _seed_petty_cash_recipient(
                            canonical_event, planner_decision, petty_cash_query, actor
                        ),
                        _seed_reversal_target(
                            canonical_event,
                            planner_decision,
                            reversal_query,
                            actor,
                            remembered_activity_id=(
                                memory_pack.current_activity_id if memory_pack else None
                            ),
                        ),
                        _seed_site_issue_close_target(
                            canonical_event, planner_decision, site_issue_query, actor
                        ),
                        _seed_worker_candidates(
                            canonical_event, planner_decision, workforce_query, actor
                        ),
                        _seed_existing_attendance(
                            canonical_event, planner_decision, workforce_query, actor
                        ),
                        _seed_duplicate_check(
                            canonical_event, planner_decision, duplicate_expense_query, actor
                        ),
                        _seed_vendor_check(
                            canonical_event, planner_decision, vendor_query, actor
                        ),
                        _seed_finance_query_context(
                            canonical_event,
                            planner_decision,
                            money_account_query,
                            expense_query_service,
                            actor,
                        ),
                        _seed_open_activity(
                            canonical_event,
                            planner_decision,
                            activity_query,
                            actor,
                            remembered_activity_id=(
                                memory_pack.current_activity_id if memory_pack else None
                            ),
                            org_settings_query=org_settings_query,
                        ),
                        _seed_correction_target(
                            canonical_event,
                            planner_decision,
                            activity_query,
                            actor,
                            remembered_activity_id=(
                                memory_pack.current_activity_id if memory_pack else None
                            ),
                        ),
                        # LABOUR_QUERY was defined but never wired into this
                        # gather -- every attendance question silently
                        # answered "no attendance recorded" regardless of
                        # what was actually logged, since generate_labour_
                        # query_reply reads collected_fields['labour_results']
                        # and nothing ever populated it. Fixed alongside #17
                        # Search/Ask Mesiri, which follows this exact
                        # seed-before-graph pattern and would have inherited
                        # the same silent-no-op bug if copied uncorrected.
                        _seed_labour_query(
                            canonical_event,
                            planner_decision,
                            labour_query_service,
                            actor,
                            timezone_name,
                        ),
                        _seed_activity_search(
                            canonical_event,
                            planner_decision,
                            activity_search_service,
                            actor,
                            timezone_name,
                        ),
                        _seed_dpr_request(
                            canonical_event,
                            planner_decision,
                            dpr_request_query,
                            actor,
                            timezone_name,
                        ),
                        _seed_project_detail_query(
                            canonical_event,
                            planner_decision,
                            activity_search_service,
                            labour_query_service,
                            expense_query_service,
                            inventory_query,
                            project_detail_query,
                            actor,
                            timezone_name,
                        ),
                    )
                    # Synchronous — not a coroutine, runs after the gather.
                    _seed_account_admin_role(canonical_event, planner_decision, actor)
                    _seed_project_create_role(canonical_event, planner_decision, actor)
                    _seed_automation_setup_role(canonical_event, planner_decision, actor)

                    # Module gate (WA-07): a request for a module this
                    # company hasn't switched on is refused before the
                    # workflow starts, with a reply that says so and lists
                    # what is available. REVERSE is judged by what it would
                    # undo. The API's MODULE_DISABLED check (BE-06) is the
                    # backstop if a path ever gets past this.
                    required_module = workflow_registry.module_for_event(
                        planner_decision.workflow_key, canonical_event.fields
                    )
                    if not workflow_registry.module_is_enabled(required_module):
                        from channel.replies import render_module_disabled_reply

                        disabled_reply = render_module_disabled_reply(str(required_module))
                        await send_text(message.sender.wa_id, disabled_reply)
                        await _safe(
                            mlog.log_reply(correlation_id=correlation_id, reply=disabled_reply)
                        )
                        await _safe(mlog.mark_completed(correlation_id=correlation_id))
                        return JourneyResult(
                            understanding=understanding,
                            resolved_context=resolved,
                            canonical_event=canonical_event,
                            planner_decision=planner_decision,
                            workflow_run=None,
                        )

                    # Account-admin role gate: refused before the workflow
                    # even starts (no draft, no confirmation prompt) --
                    # "should not even be an option" for a disallowed role,
                    # not merely rejected after they complete a confirm
                    # flow (unlike TRANSFER, which only gates at confirm
                    # time -- see transfer_validation.py's docstring for why
                    # that's an accepted tradeoff there but not here).
                    # application/finance/validation.py's role check (fed by
                    # _seed_account_admin_role above) is the defense-in-depth
                    # backstop if this is ever bypassed.
                    if (
                        planner_decision.workflow_key is WorkflowKey.ACCOUNT_ADMIN
                        and str(getattr(actor, "role", None) or "").strip().upper()
                        not in _ACCOUNT_ADMIN_ROLES
                    ):
                        await send_text(message.sender.wa_id, _ACCOUNT_ADMIN_DENIED_REPLY)
                        await _safe(
                            mlog.log_reply(
                                correlation_id=correlation_id, reply=_ACCOUNT_ADMIN_DENIED_REPLY
                            )
                        )
                        await _safe(mlog.mark_completed(correlation_id=correlation_id))
                        return JourneyResult(
                            understanding=understanding,
                            resolved_context=resolved,
                            canonical_event=canonical_event,
                            planner_decision=planner_decision,
                            workflow_run=None,
                        )

                    # Project/Site-create role gate: same "should not even be
                    # an option" reasoning as the account-admin gate
                    # immediately above. application/projects/
                    # create_validation.py's and create_site_validation.py's
                    # role checks (fed by _seed_project_create_role above)
                    # are the defense-in-depth backstop if this is ever
                    # bypassed.
                    _project_create_denied_replies = {
                        WorkflowKey.PROJECT_CREATE: _PROJECT_CREATE_DENIED_REPLY,
                        WorkflowKey.SITE_CREATE: _SITE_CREATE_DENIED_REPLY,
                        WorkflowKey.ADD_PROJECT_MEMBER: _ADD_PROJECT_MEMBER_DENIED_REPLY,
                        WorkflowKey.CREATE_USER: _CREATE_USER_DENIED_REPLY,
                    }
                    if planner_decision.workflow_key in _project_create_denied_replies and str(
                        getattr(actor, "role", None) or ""
                    ).strip().upper() not in _PROJECT_CREATE_ROLES:
                        denied_reply = _project_create_denied_replies[planner_decision.workflow_key]
                        await send_text(message.sender.wa_id, denied_reply)
                        await _safe(
                            mlog.log_reply(correlation_id=correlation_id, reply=denied_reply)
                        )
                        await _safe(mlog.mark_completed(correlation_id=correlation_id))
                        return JourneyResult(
                            understanding=understanding,
                            resolved_context=resolved,
                            canonical_event=canonical_event,
                            planner_decision=planner_decision,
                            workflow_run=None,
                        )

                    # Automation-setup role gate: same "should not even be an
                    # option" reasoning as the two gates above, but
                    # conditional on audience -- a SELF digest never targets
                    # anyone else, so it needs no role check at all.
                    # application/automations/create_validation.py's role
                    # check (fed by _seed_automation_setup_role above) is the
                    # defense-in-depth backstop if this is ever bypassed.
                    if (
                        planner_decision.workflow_key is WorkflowKey.AUTOMATION_SETUP
                        and str(canonical_event.fields.get("audience") or "SELF").strip().upper()
                        != "SELF"
                        and str(getattr(actor, "role", None) or "").strip().upper()
                        not in _AUTOMATION_TARGET_OTHERS_ROLES
                    ):
                        await send_text(message.sender.wa_id, _AUTOMATION_SETUP_DENIED_REPLY)
                        await _safe(
                            mlog.log_reply(
                                correlation_id=correlation_id, reply=_AUTOMATION_SETUP_DENIED_REPLY
                            )
                        )
                        await _safe(mlog.mark_completed(correlation_id=correlation_id))
                        return JourneyResult(
                            understanding=understanding,
                            resolved_context=resolved,
                            canonical_event=canonical_event,
                            planner_decision=planner_decision,
                            workflow_run=None,
                        )

                    workflow_run = await workflow_runtime.start(planner_decision, canonical_event)

                    # #1 Multi-Activity / #13 Cross-Module Trigger: the
                    # primary segment started normally above -- the
                    # single-active invariant is untouched, exactly as if
                    # this were an ordinary one-segment message (because,
                    # per Phase A4 of docs/execution/
                    # UNIFIED_UNDERSTANDING_PIPELINE.md, it usually IS one --
                    # n=1 is the common case of this same path now, not a
                    # separate one). Every started message becomes a Plan:
                    # size 1 for an ordinary message (Phase A4), size >1 when
                    # there ARE extra segments (Phase A2 -- repointed off
                    # workflows/batch.py's flat PendingBatchStore queue,
                    # deleted in Phase A6 once this repoint made it dead).
                    # segment_events[0]'s PlanStep always gets step_id "s1"
                    # (assigned before ordering, by build_plan_from_segments'
                    # own contract) and is marked RUNNING against the
                    # WorkflowInstance already started above -- never started
                    # a second time. The rest, if any, run one at a time as
                    # each prior step's confirmation resolves
                    # (plan_executor.advance_plan). origin=SINGLE_MESSAGE
                    # (only for the size-1 case) is what lets
                    # plan_executor.py suppress the closing summary once this
                    # one step resolves -- a size-1 plan here never showed an
                    # upfront preview, so its own confirmation reply is the
                    # whole story, exactly as it is today; _progress_prefix
                    # already returns "" for a size-1 plan regardless of
                    # origin, so the STARTING prompt is untouched either way.
                    if workflow_run.status is WorkflowRunStatus.STARTED and plan_store is not None:
                        try:
                            plan_origin = (
                                PlanOrigin.DECOMPOSITION if extra_segments else PlanOrigin.SINGLE_MESSAGE
                            )
                            plan_result = build_plan_from_segments(
                                canonical_events, plan_id=new_id("plan"), origin=plan_origin
                            )
                            if plan_result.plan is not None:
                                await plan_store.start_plan(plan=plan_result.plan)
                                await plan_store.mark_step_running(
                                    user_id=actor_user_id,
                                    step_id="s1",
                                    workflow_instance_id=workflow_run.workflow_instance_id,
                                )
                                running_plan = await plan_store.get_plan(user_id=actor_user_id)
                                prefix = _progress_prefix(running_plan) if running_plan else ""
                                if prefix:
                                    workflow_run = dataclasses.replace(
                                        workflow_run,
                                        pending_prompt=prefix + (workflow_run.pending_prompt or ""),
                                    )
                        except Exception:  # noqa: BLE001 -- a plan-persist failure here
                            # must not take down the primary segment, which already
                            # started successfully above and is the whole message as
                            # far as the user is concerned if this fails.
                            _log.exception(
                                "plan.multi_segment_persist_failed correlation_id=%s",
                                correlation_id,
                            )

                    if context_debug:
                        log_workflow_run(workflow_run)
                    if workflow_run.workflow_instance_id:
                        await _safe(
                            mlog.link_workflow_instance(
                                correlation_id=correlation_id,
                                workflow_instance_id=workflow_run.workflow_instance_id,
                            )
                        )
                    # Answering an inventory question ("how much cement is left?")
                    # means the next message is very likely a report about that
                    # same material ("40 bags of cement used...") -- bias the
                    # next message's extraction toward material_update the same
                    # way a category-menu tap does, so it doesn't fall through
                    # to the generic greeting/category menu and force a manual
                    # re-selection. Pop-once TTL (category_hint.py) means it
                    # only ever affects the very next message.
                    if (
                        workflow_run.status is WorkflowRunStatus.COMPLETED
                        and canonical_event.event_type is CanonicalEventType.INVENTORY_QUERY_ASKED
                        and category_hint_store is not None
                    ):
                        await category_hint_store.set_hint(
                            user_id=actor_user_id, semantic_hint="material_update"
                        )
                    await _safe(
                        tlog.log_stage(
                            correlation_id=correlation_id,
                            stage="workflow",
                            stage_payload={
                                "status": workflow_run.status.value,
                                "workflow_key": workflow_run.workflow_key.value,
                                "workflow_instance_id": workflow_run.workflow_instance_id,
                            },
                            duration_ms=int((time.perf_counter() - t0) * 1000),
                            succeeded=True,
                        )
                    )
                except Exception as exc:
                    await _safe(
                        tlog.log_stage(
                            correlation_id=correlation_id,
                            stage="workflow",
                            stage_payload=None,
                            duration_ms=int((time.perf_counter() - t0) * 1000),
                            succeeded=False,
                            error_code=type(exc).__name__,
                            error_message=str(exc),
                        )
                    )
                    await _safe(
                        mlog.mark_failed(
                            correlation_id=correlation_id, error_code=type(exc).__name__
                        )
                    )
                    raise
    else:
        error_code = result.error.error_code if result.error else "unknown"
        await _safe(
            tlog.log_stage(
                correlation_id=correlation_id,
                stage="context",
                stage_payload=None,
                duration_ms=int((time.perf_counter() - t0) * 1000),
                succeeded=False,
                error_code=error_code,
            )
        )
        _log.warning(
            "context.resolution_failed correlation_id=%s error_code=%s",
            correlation_id,
            error_code,
        )

    # --- Send reply ---
    # workflow_resume's own reply was already sent and logged earlier, at the
    # slow-path interaction dispatch above -- _render_reply returns None for
    # that case specifically so it isn't sent (or logged) a second time here.
    # held_reply, when set, always wins: the report is being held pending a
    # material/unit/project clarification, so nothing from planner/workflow
    # ran this turn.
    # Only the UNRECOGNIZED greeting branch changes copy on this, so the
    # database read is skipped for every other outcome (see
    # runtime/first_message_query.py, and _render_reply's own branch).
    is_first_message = False
    if (
        first_message_query is not None
        and held_reply is None
        and workflow_run is None
        and workflow_resume is None
        and planner_decision is not None
        and planner_decision.decision_type is PlannerDecisionType.DIRECT_REPLY
        and planner_decision.reason is CanonicalEventType.UNRECOGNIZED
    ):
        is_first_message = await first_message_query.is_first_message(
            sender_wa_id=message.sender.wa_id, correlation_id=correlation_id
        )

    reply = held_reply or _render_reply(
        workflow_run,
        workflow_resume,
        planner_decision,
        resolved,
        is_first_message=is_first_message,
    )

    # WA-11: a conversational reply (greeting, small talk, "what can you
    # do?", "I didn't follow") goes out in the sender's language, opening
    # with a word for their small talk when there was some. Workflow prompts,
    # confirmations and receipts are untouched (exact quantities and names).
    # Only the body text: list buttons and row titles have tight length
    # limits and stay as they are.
    if (
        reply is not None
        and reply_composer is not None
        and held_reply is None
        and workflow_run is None
        and workflow_resume is None
        and planner_decision is not None
        and planner_decision.decision_type is PlannerDecisionType.DIRECT_REPLY
    ):
        language = reply_language
        if language is None and user_language_store is not None:
            language = await user_language_store.get(user_id=actor_user_id)
        composed = await reply_composer.compose(
            reply.text,
            language=language,
            user_message=reply_user_message,
            correlation_id=correlation_id,
        )
        if composed != reply.text:
            reply = dataclasses.replace(reply, text=composed)

    # WA-01 save first: a capture draft (work done, labour, materials,
    # issues) is not asked "Confirm?" -- the caller (message_journey) saves
    # it straight away through InteractionHandler.save_now and sends the
    # saved reply instead, so nothing is sent from here.
    if (
        held_reply is None
        and workflow_run is not None
        and workflow_run.status is WorkflowRunStatus.STARTED
        and await interaction_handler.saves_first(
            workflow_key=workflow_run.workflow_key,
            organization_id=str(actor.organization_id) if actor and actor.organization_id else None,
        )
    ):
        reply = None

    # Attach the low-confidence caveat (if any) ONLY to a freshly-started
    # confirmation for THIS message (workflow_run.status STARTED). Never on
    # held_reply (a gate prompt is asking about something else entirely) and
    # never on BLOCKED_PENDING_CONFIRMATION (that prompt describes an OLDER
    # draft this message didn't produce -- captioning it with this message's
    # own field confidence would name the wrong report).
    if (
        held_reply is None
        and reply is not None
        and workflow_run is not None
        and workflow_run.status is WorkflowRunStatus.STARTED
    ):
        caveat = caveat_text(ambiguity_decision)
        if caveat:
            reply = ReplySpec(
                text=f"{caveat}\n\n{reply.text}",
                list_button_label=reply.list_button_label,
                list_rows=reply.list_rows,
                buttons=reply.buttons,
            )

    if reply is not None:
        send_result = await send_reply_spec(
            reply,
            message.sender.wa_id,
            send_text=send_text,
            send_list=send_list,
            send_button=send_button,
        )
        await _safe(mlog.log_reply(correlation_id=correlation_id, reply=reply.text))
        # #11 Reply Workflow: only the plain-text branch of send_reply_spec
        # returns a wamid (see that module's docstring) -- a str result
        # means the reply was captured; anything else (bool from the list/
        # button branches, or None on send failure) means there is nothing
        # to record.
        if isinstance(send_result, str):
            await _safe(
                mlog.set_reply_wamid(correlation_id=correlation_id, reply_wamid=send_result)
            )

    # #16 Daily Report Generation's chat trigger: the status text above is
    # always sent first (a supervisor should never get a document with no
    # explanation), and the PDF itself follows as a second message only
    # when _seed_dpr_request found a rendered one. This is a side-channel
    # deliberately separate from ReplySpec/send_reply_spec -- the same
    # shape send_image's receipt delivery uses (see the interaction-resume
    # leg's `handled.receipt_coro` branch) -- because ReplySpec has no
    # notion of a binary attachment and adding one there would ripple into
    # every other reply type that doesn't need it.
    if (
        workflow_run is not None
        and workflow_run.workflow_key is WorkflowKey.DPR_REQUEST
        and canonical_event is not None
        and canonical_event.fields.get("dpr_object_key")
        and send_document is not None
        and object_storage is not None
    ):
        try:
            stored = await object_storage.get_object(canonical_event.fields["dpr_object_key"])
            code = canonical_event.fields.get("dpr_code") or "DPR"
            await send_document(
                message.sender.wa_id,
                stored.data,
                filename=f"{code}.pdf",
                caption=None,
            )
        except Exception:  # noqa: BLE001 -- the status text was already sent; a
            # failed document fetch/send must not fail the whole journey.
            _log.warning(
                "dpr_request.document_send_failed correlation_id=%s", correlation_id, exc_info=True
            )

    # Query "send as PDF": the text reply above always goes first (same
    # reasoning as the DPR side-channel just above), and a PDF follows only
    # when the extractor set output_format="pdf" on the request (see
    # platform/ai/src/mesiri_ai/adapters/{gemini,deepseek}/adapter.py's
    # finance_query/inventory_query/labour_query/activity_query field docs).
    # Unlike DPR, there is no R2 artifact to fetch -- _build_query_pdf
    # renders on the fly from whichever *_results/*_levels key the matching
    # _seed_* function already seeded.
    if (
        workflow_run is not None
        and canonical_event is not None
        and canonical_event.fields.get("output_format") == "pdf"
        and send_document is not None
    ):
        built = _build_query_pdf(workflow_run.workflow_key, canonical_event.fields)
        if built is not None:
            pdf_bytes, filename = built
            try:
                await send_document(message.sender.wa_id, pdf_bytes, filename=filename, caption=None)
            except Exception:  # noqa: BLE001 -- the status text was already sent; a
                # failed PDF build/send must not fail the whole journey.
                _log.warning(
                    "query_pdf.send_failed correlation_id=%s",
                    correlation_id,
                    exc_info=True,
                )

    await _safe(mlog.mark_completed(correlation_id=correlation_id))

    if memory_coordinator is not None:
        user_text = understanding.transcript or understanding.normalized_text or ""
        asyncio.ensure_future(
            memory_coordinator.record_turn(
                user_id=actor_user_id,
                user_text=user_text,
                assistant_reply=reply.text if reply is not None else "",
                correlation_id=correlation_id,
            )
        )

    return JourneyResult(
        understanding=understanding,
        resolved_context=resolved,
        canonical_event=canonical_event,
        planner_decision=planner_decision,
        workflow_run=workflow_run,
        workflow_resume=workflow_resume,
    )
