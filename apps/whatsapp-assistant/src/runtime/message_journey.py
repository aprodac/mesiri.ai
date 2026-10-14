"""Inbound WhatsApp message handling -- the callbacks WhatsAppReceiver invokes
once a message is normalized and deduplicated (see runtime/dependencies.py's
build_container, which wires WhatsAppReceiver(on_normalized=..., ...) to
`build_message_handlers`'s return value).

Split out of runtime/dependencies.py (2026-07-29) purely for file size --
build_container was one 1,800+ line function, and this handler logic (the
identity gate, every deterministic fast path, and the call into
process_inbound_message) was over half of it. These were originally closures
over build_container's own locals; `build_message_handlers` below takes the
same values as explicit parameters instead, which is functionally identical
-- a closure over a parameter behaves exactly like a closure over a local --
but keeps wiring (build_container) and message handling (this module) in
separate files. The nested closures' bodies are unchanged from the original.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import TYPE_CHECKING, Any

from channel.replies import (
    CATEGORY_SEMANTIC_HINT,
    SILENTLY_IGNORED_RAW_TYPES,
    ReplySpec,
    render_unsupported_media_reply,
)
from context.live_identity import (
    NO_ORG_MESSAGE,
    ORG_SUSPENDED_MESSAGE,
    UNREGISTERED_MESSAGE,
    resolve_sender,
)
from interactions.image_purpose import try_hold_new_image_for_purpose_picker
from mesiri_ai.undo_classifier import UNDO_SEMANTIC_HINT, is_undo_trigger
from mesiri_contracts.assistant.enums import InputModality
from runtime.account_admin_journey import try_handle_account_admin_command
from runtime.inbound_journey import (
    process_inbound_message,
    resume_pending_decomposition_with_material,
    resume_pending_decomposition_with_material_create,
    resume_pending_decomposition_with_material_unit_choice,
    resume_pending_decomposition_with_project,
    resume_pending_decomposition_with_site,
    resume_pending_decomposition_with_stock_choice,
    resume_pending_decomposition_with_unit,
    resume_pending_plan_confirmation,
    resume_pending_report_with_audience_candidate,
    resume_pending_report_with_material,
    resume_pending_report_with_material_create,
    resume_pending_report_with_material_unit_choice,
    resume_pending_report_with_member_candidate,
    resume_pending_report_with_member_create_offer,
    resume_pending_report_with_petty_cash_recipient,
    resume_pending_report_with_project,
    resume_pending_report_with_site,
    resume_pending_report_with_stock_choice,
    resume_pending_report_with_unit,
)
from runtime.reply_dispatch import send_reply_spec
from runtime.step_timing import StepTimer
from workflows import WorkflowRunResult, WorkflowRunStatus
from workflows import registry as workflow_registry

if TYPE_CHECKING:
    from backend.ports import ActorReader
    from channel.whatsapp.outbound import WhatsAppSender
    from context.resolver import ContextResolver
    from interactions import InteractionHandler
    from interactions.category_hint import CategoryHintStore
    from interactions.completion_photo_hint import CompletionPhotoHintStore
    from interactions.pending_media import PendingMediaStore
    from interactions.pending_report import PendingReportStore
    from interactions.project_setup_offer import ProjectSetupOfferStore
    from interactions.team_photo_hint import TeamPhotoHintStore
    from memory.context_loader import ConversationMemoryLoader
    from memory.coordinator import ConversationMemoryCoordinator
    from memory.recent_turns import RecentTurnsStore
    from mesiri_ai.ports.decomposition import DecompositionProvider
    from mesiri_contracts.common.storage import ObjectStoragePort
    from planner import Planner
    from planning.plan_store import PlanStore
    from runtime.activity_query import ActivityQueryService
    from runtime.activity_search_service import ActivitySearchService
    from runtime.capability_help import CapabilityHelpService
    from runtime.dependencies import Settings
    from runtime.dpr_request_query import DprRequestQueryService
    from runtime.duplicate_expense_query import DuplicateExpenseQueryService
    from runtime.entity_resolution.member_resolution import MemberNameResolutionService
    from runtime.escalation_query import EscalationCreateService
    from runtime.evidence_query import EvidenceAttachService
    from runtime.expense_category_query import ExpenseCategoryQueryService
    from runtime.expense_query_service import ExpenseQueryService
    from runtime.first_message_query import FirstMessageQueryService
    from runtime.inbound_journey.pending_decomposition import PendingDecompositionStore
    from runtime.inventory_query import MaterialInventoryQueryService
    from runtime.labour_query_service import LabourQueryService
    from runtime.logging_ports import MessageLogger, TraceLogger
    from runtime.material_catalog_query import MaterialCatalogQueryService
    from runtime.money_account_query import MoneyAccountQueryService
    from runtime.org_settings_query import OrganizationSettingsQueryService
    from runtime.petty_cash_query import PettyCashRecipientQueryService
    from runtime.project_detail_query import ProjectDetailQueryService
    from runtime.reply_language import ReplyComposer, UserLanguageStore
    from runtime.reversal_query import ReversalTargetQueryService
    from runtime.site_issue_query import SiteIssueTargetQueryService
    from runtime.vendor_query import VendorQueryService
    from runtime.workforce_query import WorkforceQueryService
    from understanding.pipeline import UnderstandingPipeline
    from workflows import WorkflowRuntime

_log = logging.getLogger("mesiri.context")

# See _send_processing_ack below. text/interactive deliberately absent --
# they already reply in under ~2s (measured), where a second message
# would just add noise.
_PROCESSING_ACK_TEXT: dict[InputModality, str] = {
    InputModality.IMAGE: "📷 Got your photo — reading it now...",
    InputModality.DOCUMENT: "📄 Got your document — reading it now...",
    InputModality.VOICE: "🎤 Got your voice note — listening now...",
}


def build_message_handlers(
    *,
    settings: Settings,
    sender: WhatsAppSender,
    actor_reader: ActorReader,
    pipeline: UnderstandingPipeline,
    context_resolver: ContextResolver,
    planner: Planner,
    workflow_runtime: WorkflowRuntime,
    interaction_handler: InteractionHandler,
    object_storage: ObjectStoragePort,
    message_logger: MessageLogger,
    trace_logger: TraceLogger,
    inventory_query: MaterialInventoryQueryService,
    catalog_query: MaterialCatalogQueryService,
    org_settings_query: OrganizationSettingsQueryService,
    expense_category_query: ExpenseCategoryQueryService,
    money_account_query: MoneyAccountQueryService,
    petty_cash_query: PettyCashRecipientQueryService,
    reversal_query: ReversalTargetQueryService,
    site_issue_query: SiteIssueTargetQueryService,
    duplicate_expense_query: DuplicateExpenseQueryService,
    workforce_query: WorkforceQueryService,
    activity_query: ActivityQueryService,
    evidence_query: EvidenceAttachService,
    escalation_query: EscalationCreateService,
    capability_help: CapabilityHelpService,
    first_message_query: FirstMessageQueryService,
    member_resolver: MemberNameResolutionService,
    plan_store: PlanStore,
    pending_decomposition_store: PendingDecompositionStore,
    decomposition: DecompositionProvider | None = None,
    recent_turns_store: RecentTurnsStore,
    labour_query_service: LabourQueryService,
    activity_search_service: ActivitySearchService,
    dpr_request_query: DprRequestQueryService,
    project_detail_query: ProjectDetailQueryService,
    vendor_query: VendorQueryService,
    expense_query_service: ExpenseQueryService,
    pending_report_store: PendingReportStore,
    pending_media_store: PendingMediaStore,
    category_hint_store: CategoryHintStore,
    completion_photo_hint_store: CompletionPhotoHintStore,
    team_photo_hint_store: TeamPhotoHintStore,
    project_setup_offer_store: ProjectSetupOfferStore,
    memory_loader: ConversationMemoryLoader,
    memory_coordinator: ConversationMemoryCoordinator,
    reply_composer: ReplyComposer | None = None,
    user_language_store: UserLanguageStore | None = None,
) -> tuple[Any, Any]:
    """Build the `on_normalized`/`on_message_claimed` callbacks WhatsAppReceiver
    invokes for every inbound message, closing over the already-built services
    passed in above rather than reaching for a container. Returns
    `(on_normalized, on_message_claimed)`, in the same order
    WhatsAppReceiver's constructor takes them.
    """
    # _send_understanding_reply (the old reply_sender=... callback) is gone:
    # inbound_journey._render_reply() now covers every outcome, so the
    # understanding-only fallback it fed was dead weight.
    async def _on_normalized(message, raw_payload, retry_of_id=None) -> None:  # type: ignore[no-untyped-def]
        """Never let an unhandled exception reach the user as silence.

        The journey below has error handling at every stage it anticipates,
        but anything it does *not* anticipate propagates to
        WhatsAppReceiver._process_message, which logs it and writes a trace
        row -- and sends nothing. From the sender's side that is
        indistinguishable from Mesiri being down: they photographed an
        attendance sheet, answered "what is this photo for?", and then
        nothing ever came back.

        inbound_journey._render_reply already states the principle for the
        paths it owns ("a message that reaches the assistant and gets no
        answer is indistinguishable from Mesiri being down"); this extends
        the same guarantee to the paths nobody predicted. The exception is
        still re-raised so the trace row and the log line are unchanged --
        this only adds the reply that was missing.
        """
        try:
            await _run_journey(message, raw_payload, retry_of_id)
        except Exception:
            _log.exception(
                "inbound.unhandled correlation_id=%s message_id=%s",
                getattr(message, "correlation_id", "?"),
                getattr(message, "message_id", "?"),
            )
            try:
                await sender.send_text(
                    message.sender.wa_id,
                    "⚠️ Something went wrong handling that — nothing was recorded. "
                    "Please try again, and tell us if it keeps happening.",
                )
            except Exception:  # noqa: BLE001 -- the send itself can fail; the
                # re-raise below still gets the failure into the trace log.
                _log.exception("inbound.unhandled_reply_failed")
            raise

    async def _mark_read_on_claim(message_id: str) -> None:
        """Blue tick + "typing..." -- wired into WhatsAppReceiver as
        on_message_claimed so it fires the instant the webhook lands, in
        parallel with processing. It used to run here at the top of
        _run_journey, which for voice/image meant the sender saw no blue
        tick until the Meta media download (~1.5-1.7s measured), upload and
        normalization had all finished first."""
        await sender.mark_as_read(message_id)

    # Held so a fire-and-forget ack task can't be garbage-collected mid-flight
    # -- asyncio only keeps a weak reference to a task nothing else holds.
    # Same reasoning, same pattern as WhatsAppReceiver._background_tasks.
    _ack_tasks: set[asyncio.Task[None]] = set()

    def _fire_processing_ack(wa_id: str, modality: InputModality) -> None:
        """Schedule _send_processing_ack without awaiting it -- the caller's
        real work (the slow understanding call that follows) must start
        immediately, not after this ~600-900ms Meta round trip."""
        task = asyncio.create_task(_send_processing_ack(wa_id, modality))
        _ack_tasks.add(task)
        task.add_done_callback(_ack_tasks.discard)

    async def _send_processing_ack(wa_id: str, modality: InputModality) -> None:
        """A second, real message sent before understanding starts, not just
        the read-receipt blue tick.

        Voice/image replies still take several real seconds (traced:
        analyze_image ~6.4s, understand_voice ~3.2s, plus a confirmed
        expense's receipt render + a second send) -- without this the
        sender watches "typing..." with zero information for that whole
        window, which reads as "did this even go through?" rather than
        "still working on it". Fire-and-forget like the read receipt:
        nothing downstream depends on it, and a failure here must never
        delay or replace the real reply.

        Deliberately skips text/interactive -- those already reply in
        under ~2s (measured), where a second message would arrive at
        almost the same time as the real one and just add noise.
        """
        text = _PROCESSING_ACK_TEXT.get(modality)
        if text is None:
            return
        try:
            await sender.send_text(wa_id, text)
        except Exception:  # noqa: BLE001
            _log.exception(
                "processing_ack_failed wa_id=%s modality=%s", wa_id, modality.value
            )

    async def _run_journey(message, raw_payload, retry_of_id=None) -> None:  # type: ignore[no-untyped-def]
        timer = StepTimer()
        try:
            await _run_journey_steps(message, raw_payload, retry_of_id, timer)
        finally:
            # Emitted in `finally` so every path is covered by one write --
            # this block has a dozen early returns (unregistered sender,
            # suspended org, a fast path that handled the message outright),
            # and a per-return emit would be a dozen chances to miss one.
            # duration_ms is the whole journey; subtract the
            # process_inbound_message lap for the pre-pipeline cost alone.
            try:
                await trace_logger.log_stage(
                    correlation_id=message.correlation_id,
                    stage="prepipeline",
                    stage_payload=timer.steps,
                    duration_ms=timer.total_ms,
                    succeeded=True,
                )
            except Exception:  # noqa: BLE001 -- diagnostics must never break a message
                _log.exception("prepipeline.trace_failed correlation_id=%s", message.correlation_id)

    async def _run_journey_steps(message, raw_payload, retry_of_id, timer) -> None:  # type: ignore[no-untyped-def]
        wa_id = message.sender.wa_id

        # M4: resolve the sender before spending on understanding.
        try:
            ctx = await resolve_sender(actor_reader, wa_id)
        except Exception:  # noqa: BLE001 — never let a lookup error drop the message silently
            _log.exception("context.identity_lookup_failed wa_id=%s", wa_id)
            ctx = None

        timer.lap("resolve_sender")
        org_id = ctx.organization_id if ctx else None

        # Best-effort inbound message log (for debugging/replay). raw_payload
        # is a self-contained, replayable envelope of the raw Meta webhook
        # JSON (see ingress.receiver.WhatsAppReceiver._envelope) -- stored in
        # full so a failed message can later be replayed via the admin retry
        # action. A retry reuses the same WhatsApp message_id, so its dedup_key
        # is suffixed with the new correlation_id to avoid colliding with the
        # original row (ON CONFLICT (dedup_key) DO NOTHING would otherwise
        # silently drop the retry attempt).
        #
        # Phase 7 perf: fired in the background with ensure_future so the DB
        # write does not block the reply path. The return value is never read
        # and the write is already best-effort (it was wrapped in try/except
        # at the call site before this change). Same pattern as _safe() used
        # throughout this module. In the rare event of a process crash within
        # ~50ms, this one audit row is lost; the message itself is not lost
        # because WhatsApp retries unacknowledged webhooks.
        dedup_key = (
            message.message_id
            if retry_of_id is None
            else f"{message.message_id}:retry:{message.correlation_id}"
        )
        asyncio.ensure_future(
            message_logger.log_received(
                correlation_id=message.correlation_id,
                sender_wa_id=wa_id,
                message_type=message.modality.value,
                raw_payload=dict(raw_payload),
                normalized_message=message.model_dump(mode="json"),
                body_text=message.text,
                media_object_key=message.media.object_key if message.media else None,
                dedup_key=dedup_key,
                retry_of_id=retry_of_id,
                organization_id=org_id,
            )
        )
        timer.lap("log_received")

        if ctx is None:
            _log.info("context.sender_unregistered wa_id=%s", wa_id)
            await sender.send_text(wa_id, UNREGISTERED_MESSAGE)
            await message_logger.log_reply(
                correlation_id=message.correlation_id, reply=UNREGISTERED_MESSAGE
            )
            await message_logger.mark_completed(correlation_id=message.correlation_id)
            return

        if ctx.organization_id is None:
            _log.info("context.user_no_org user=%s", ctx.user_id)
            reply = NO_ORG_MESSAGE.format(name=ctx.full_name)
            await sender.send_text(wa_id, reply)
            await message_logger.log_reply(correlation_id=message.correlation_id, reply=reply)
            await message_logger.mark_completed(correlation_id=message.correlation_id)
            return

        if not ctx.org_active:
            _log.info("context.org_suspended org=%s", ctx.organization_id)
            await sender.send_text(wa_id, ORG_SUSPENDED_MESSAGE)
            await message_logger.log_reply(
                correlation_id=message.correlation_id, reply=ORG_SUSPENDED_MESSAGE
            )
            await message_logger.mark_completed(correlation_id=message.correlation_id)
            return

        _log.info(
            "context.resolved user=%s org=%s projects=%s",
            ctx.user_id,
            ctx.organization_id,
            len(ctx.projects),
        )

        # WA-07: the company's switched-on modules, set before the fast paths
        # below (slot answers, confirmations, the account command) so they
        # see it too; process_inbound_message sets it again for its own path.
        workflow_registry.set_enabled_modules(
            await org_settings_query.enabled_modules(organization_id=str(ctx.organization_id))
        )

        # A message type Mesiri can't act on yet (PDF, video, sticker,
        # location pin, shared contact, music file). Answered here rather
        # than dropped: normalization used to raise on these, aborting
        # ingress with no reply at all, so the sender couldn't tell "Mesiri
        # can't read PDFs" from "Mesiri is down" and had no idea whether
        # their report had landed.
        #
        # Placed after the identity/org gates on purpose -- an unregistered
        # sender or a suspended org needs to hear *that* first, since it's
        # the more actionable problem. Placed before the interaction fast
        # path because an UNKNOWN-modality message can never be a
        # confirmation reply or a menu tap, and must not be able to resolve
        # a pending draft.
        if message.modality is InputModality.UNKNOWN:
            raw_type = (message.metadata or {}).get("raw_type")
            if str(raw_type or "") in SILENTLY_IGNORED_RAW_TYPES:
                # An emoji reaction on one of our own replies, or a Meta
                # system notice -- logged, but replying would be noise.
                _log.info("ingress.ignored_raw_type type=%s user=%s", raw_type, ctx.user_id)
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return
            _log.info("ingress.unsupported_raw_type type=%s user=%s", raw_type, ctx.user_id)
            unsupported_reply = render_unsupported_media_reply(raw_type)
            await sender.send_text(wa_id, unsupported_reply)
            await message_logger.log_reply(
                correlation_id=message.correlation_id, reply=unsupported_reply
            )
            await message_logger.mark_completed(correlation_id=message.correlation_id)
            return

        async def _send_spec(spec, target_wa_id: str) -> None:
            """Send a ReplySpec through whichever transport it asks for."""
            await send_reply_spec(
                spec,
                target_wa_id,
                send_text=sender.send_text,
                send_list=sender.send_list,
                send_button=sender.send_button,
            )

        async def _park_team_photo_report(store, user_id: str, report_id: str) -> None:
            """Remember which report a team photo would belong to.

            Never raises: Redis is a hint here, and losing it costs the photo
            offer, not the attendance.
            """
            try:
                await store.set_hint(user_id=user_id, report_id=report_id)
            except Exception:  # noqa: BLE001
                _log.warning("team_photo.park_failed user=%s", user_id)

        async def _safe_pop_pending_report(store, user_id: str) -> str | None:
            """Pop the pending team-photo report id, never raising.

            Redis is a hint here, not a source of truth: if it is unreachable
            the photo simply goes through the normal picker instead, which is
            a worse experience but not a broken one.
            """
            try:
                return await store.pop_hint(user_id=user_id)
            except Exception:  # noqa: BLE001
                _log.warning("team_photo.hint_read_failed user=%s", user_id)
                return None

        # A tap on the team-photo offer. Handled before everything else
        # because both buttons are answers to a question Mesiri asked, and
        # "Skip" in particular must not fall through to the confirmation
        # classifier, which would read it as rejecting the attendance.
        team_photo_tap = str((message.metadata or {}).get("interactive_reply_id") or "")
        if team_photo_tap in ("team_photo_upload", "team_photo_skip"):
            from channel.replies import render_team_photo_skipped_reply

            if team_photo_tap == "team_photo_skip":
                # Drop the hint, so a photo sent later for some other purpose
                # is not quietly attached to an offer already declined.
                try:
                    await team_photo_hint_store.clear(user_id=ctx.user_id)
                except Exception:  # noqa: BLE001
                    _log.warning("team_photo.clear_failed user=%s", ctx.user_id)
                reply_text = render_team_photo_skipped_reply()
            else:
                # "Upload Photo" is an acknowledgement, not a command -- the
                # hint stays live and the next photo attaches to it.
                reply_text = "📷 Go ahead — send the photo whenever you're ready."
            await sender.send_text(wa_id, reply_text)
            await message_logger.log_reply(
                correlation_id=message.correlation_id, reply=reply_text
            )
            await message_logger.mark_completed(correlation_id=message.correlation_id)
            return

        # A tap on the chained project/site setup offer (see
        # _offer_project_setup / start_project_setup_followup in
        # runtime/inbound_journey/seeding.py). Handled before everything
        # else for the same reason as the team-photo tap above: "Skip" must
        # not fall through to the confirmation classifier.
        setup_tap = str((message.metadata or {}).get("interactive_reply_id") or "")
        if setup_tap in (
            "setup_add_site",
            "setup_skip_site",
            "setup_add_member",
            "setup_skip_member",
        ):
            from channel.replies import (
                render_setup_offer_expired_reply,
                render_setup_offer_skipped_reply,
            )
            from runtime.inbound_journey import start_project_setup_followup

            if setup_tap in ("setup_skip_site", "setup_skip_member"):
                try:
                    await project_setup_offer_store.clear(user_id=ctx.user_id)
                except Exception:  # noqa: BLE001
                    _log.warning("project_setup.clear_failed user=%s", ctx.user_id)
                reply = ReplySpec(text=render_setup_offer_skipped_reply())
            else:
                expected_stage = "site" if setup_tap == "setup_add_site" else "member"
                try:
                    offer = await project_setup_offer_store.pop_offer(user_id=ctx.user_id)
                except Exception:  # noqa: BLE001
                    _log.warning("project_setup.pop_failed user=%s", ctx.user_id)
                    offer = None
                if offer is None or offer.stage != expected_stage:
                    reply = ReplySpec(text=render_setup_offer_expired_reply())
                else:
                    try:
                        reply = await start_project_setup_followup(
                            stage=offer.stage,
                            project_id=offer.project_id,
                            actor=ctx,
                            workflow_runtime=workflow_runtime,
                        )
                    except Exception:  # noqa: BLE001 — a tap must always get some reply
                        _log.exception("project_setup.followup_failed user=%s", ctx.user_id)
                        reply = None
                    reply = reply or ReplySpec(
                        text="Sorry, I couldn't start that — please try again."
                    )
            await send_reply_spec(
                reply,
                wa_id,
                send_text=sender.send_text,
                send_list=sender.send_list,
                send_button=sender.send_button,
            )
            await message_logger.log_reply(
                correlation_id=message.correlation_id, reply=reply.text
            )
            await message_logger.mark_completed(correlation_id=message.correlation_id)
            return

        async def _deliver_handled(handled) -> None:  # type: ignore[no-untyped-def]
            """Everything that follows a saved/answered confirmation: the
            reply, the receipt image, the worker-promotion / team-photo /
            project-setup offers, the plan advance and the audit rows. Shared
            by a typed "YES" (the fast path) and by save-first (WA-01), so
            an item saved without asking gets exactly the same follow-ups."""
            # Phase 4: send confirmation text FIRST so the user sees it
            # immediately, then await the receipt PNG (Playwright render) and
            # send the image. This keeps the reply feeling instant even when
            # the page-pool is cold.
            await sender.send_text(wa_id, handled.reply_text)
            if handled.next_segment_reply is not None:
                # #1 Multi-Activity: the batch's next queued segment, as its
                # own message -- not concatenated above -- so a confirmable
                # next segment keeps its Yes/No buttons (see workflows/
                # batch.py's render_started_segment_reply_spec).
                await send_reply_spec(
                    handled.next_segment_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
            if handled.receipt_coro is not None:
                try:
                    image_bytes = await handled.receipt_coro
                except Exception:  # noqa: BLE001 -- receipt failure must never drop the message
                    image_bytes = None
                if image_bytes is not None:
                    sent = await sender.send_image(wa_id, image_bytes, caption=None)
                    if not sent:
                        pass  # image already tried; text was already sent above
            # Worker promotion follow-up. This belongs *here*, not in
            # inbound_journey: a confirmation reply is resolved by the fast
            # path above and returns before the journey ever runs, so a hook
            # placed there never fires for the one event it exists to follow
            # -- which is exactly why no promotion offer was ever sent.
            # Attendance text and receipt are already delivered above; this is
            # strictly a second-step offer that never delays either.
            from runtime.inbound_journey import (
                _maybe_trigger_worker_promotion,
                _offer_project_setup,
                _offer_team_photo,
                _recorded_attendance_report_id,
            )
            from runtime.plan_executor import advance_plan

            try:
                promotion_offered = await _maybe_trigger_worker_promotion(
                    handled,
                    workflow_runtime,
                    workforce_query,
                    ctx,
                    wa_id,
                    sender.send_text,
                )
            except Exception:  # noqa: BLE001 — promotion never disturbs saved attendance
                _log.exception("worker_promotion.trigger_failed user=%s", ctx.user_id)
                promotion_offered = False
            # Team photo. The report id is parked here, on confirmation,
            # whatever happens next -- the deferred branch below pops it after
            # the promotion answer, and has no other way to learn which day
            # the photo belongs to. An earlier version parked it only inside
            # _offer_team_photo, so a report *with* new workers deferred the
            # offer and then looked for an id nobody had written: the prompt
            # never arrived for exactly the reports most likely to want one.
            report_id = _recorded_attendance_report_id(handled)
            if report_id:
                await _park_team_photo_report(
                    team_photo_hint_store, ctx.user_id, report_id
                )
            # Sent now only when nothing is being promoted; otherwise it waits
            # for that answer, so the supervisor faces one question at a time
            # rather than two prompts at once.
            if report_id and not promotion_offered:
                await _offer_team_photo(
                    report_id, ctx, wa_id, team_photo_hint_store, _send_spec
                )
            # Chained project/site setup offer: independent of the two
            # attendance-only follow-ups above (mutually exclusive triggers
            # -- this only fires for CREATE_PROJECT/CREATE_SITE, those only
            # for RECORD_LABOUR_ATTENDANCE), so it always runs regardless of
            # what happened above. See _offer_project_setup's docstring.
            try:
                await _offer_project_setup(
                    handled, project_setup_offer_store, ctx, wa_id, _send_spec
                )
            except Exception:  # noqa: BLE001 — offer never disturbs the saved project/site
                _log.exception("project_setup.offer_failed user=%s", ctx.user_id)
            # Plan advance (docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md
            # §4.2/§7.1): after ANY confirmed/rejected workflow, check
            # whether it was a step in a Plan waiting on this exact
            # instance -- the entity-resolution layer's CREATE_USER ->
            # ADD_PROJECT_MEMBER chain (ENTITY_RESOLUTION_PLAN.md §3.3) and a
            # decomposed multi-intent plan (§9) both run through this same
            # call, generically, rather than one hand-written advance per
            # chain. A cheap no-op (one Redis read) for the overwhelmingly
            # common confirmation with no plan waiting on it at all.
            try:
                plan_reply = await advance_plan(
                    handled,
                    plan_store=plan_store,
                    workflow_runtime=workflow_runtime,
                    actor=ctx,
                )
                if plan_reply is not None and await _save_first_now():
                    # WA-01: the plan's next step was a capture draft --
                    # saved and answered already; its "Confirm?" prompt
                    # is not sent.
                    plan_reply = None
                if plan_reply is not None:
                    # send_reply_spec, not sender.send_text -- a mid-plan
                    # reply carries Yes/No buttons for whatever step just
                    # started (render_workflow_run_reply_spec attaches
                    # them), and send_text would have silently dropped them
                    # to plain "Reply YES/NO" text, the same bug class
                    # start_member_create_plan had. The closing summary is
                    # plain text either way (format_plan_summary), which
                    # ReplySpec/send_reply_spec already handle correctly.
                    await send_reply_spec(
                        plan_reply,
                        wa_id,
                        send_text=sender.send_text,
                        send_list=sender.send_list,
                        send_button=sender.send_button,
                    )
            except Exception:  # noqa: BLE001 — the confirmed/rejected step's own
                # outcome was already recorded either way.
                _log.exception("plan.advance_failed user=%s", ctx.user_id)
            # Was missing until now: every other fast-path step laps the
            # timer, but this one (and its three siblings above) didn't --
            # so the "prepipeline" trace a user pastes back for debugging
            # could never show whether this hook ran at all, only that
            # *something* between handle_fast_path and the final gather()
            # took some amount of time. Diagnosing a live "chain stopped at
            # user created" report needed this and didn't have it.
            timer.lap("plan_advance")
            # Phase 8 perf: user reply is already sent above. These 4 writes
            # are order-independent audit rows -- run them concurrently.
            await asyncio.gather(
                message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=handled.reply_text
                ),
                message_logger.link_workflow_instance(
                    correlation_id=message.correlation_id,
                    workflow_instance_id=handled.result.workflow_instance_id,
                ) if handled.result.workflow_instance_id else asyncio.sleep(0),
                message_logger.update_context(
                    correlation_id=message.correlation_id,
                    project_id=handled.project_id,
                    site_id=handled.site_id,
                ),
                message_logger.mark_completed(correlation_id=message.correlation_id),
                return_exceptions=True,
            )

        async def _save_first_now() -> bool:
            """WA-01: save the sender's waiting capture draft without asking
            and deliver it like a confirmed one. False when there is nothing
            to save first (no draft waiting, or not a save-first kind)."""
            try:
                saved = await interaction_handler.save_now(ctx.user_id, actor=ctx)
            except Exception:  # noqa: BLE001 -- the draft stays waiting; nothing lost
                _log.exception("save_first.failed user=%s", ctx.user_id)
                return False
            if saved is None:
                return False
            await _deliver_handled(saved)
            return True

        async def _save_first_after_journey(journey) -> None:  # type: ignore[no-untyped-def]
            """After the normal journey: when it started a capture draft
            (process_inbound_message then sent no "Confirm?"), save it now.
            Keyed on THIS message having started a draft, so a draft left
            waiting from an earlier message is never saved by an unrelated
            one."""
            run = getattr(journey, "workflow_run", None)
            if run is None or run.status is not WorkflowRunStatus.STARTED:
                return
            if await _save_first_now():
                return
            # Not saved after all (a failure, or the company was switched in
            # between): if the journey held back its "Confirm?" for us, send
            # it now, so the sender is never left with no reply at all.
            try:
                held_back = await interaction_handler.saves_first(
                    workflow_key=run.workflow_key, organization_id=str(ctx.organization_id)
                )
            except Exception:  # noqa: BLE001
                held_back = False
            if held_back:
                from runtime.inbound_journey import render_workflow_run_reply_spec

                await _send_spec(render_workflow_run_reply_spec(run), wa_id)

        # M7: if the user has a workflow awaiting confirmation and this message
        # is a confirmation reply, resume it and stop — the AI pipeline (and its
        # token cost) is never touched. A plain "yes" ends here.
        try:
            handled = await interaction_handler.handle_fast_path(ctx.user_id, message, actor=ctx)
            timer.lap("handle_fast_path")
        except Exception:  # noqa: BLE001 — a resume error must not drop the message
            _log.exception("interaction.handle_failed user=%s", ctx.user_id)
            handled = None
        if handled is not None:
            await _deliver_handled(handled)
            return

        # Finance Module Slice 1: if the user has a workflow awaiting a slot
        # answer (e.g. "which account?") and this message can answer it
        # (text/interactive only -- see handle_slot_answer's docstring),
        # resume it and stop, same principle and same priority as the
        # confirmation fast path above.
        try:
            slot_handled = await interaction_handler.handle_slot_answer(ctx.user_id, message)
            timer.lap("handle_slot_answer")
        except Exception:  # noqa: BLE001 — a resume error must not drop the message
            _log.exception("interaction.slot_answer_failed user=%s", ctx.user_id)
            slot_handled = None
        if slot_handled is not None:
            # Resuming a slot answer can land on any WorkflowRunResult status
            # -- another AWAITING_INPUT (next slot) or STARTED (draft ready,
            # needs Yes/No) just as often as COMPLETED -- so this must render
            # through the same status-aware ReplySpec logic every other
            # workflow-run reply uses, not always plain text. See
            # runtime/inbound_journey.py's render_workflow_run_reply_spec
            # docstring for the bug this fixes.
            from runtime.inbound_journey import render_workflow_run_reply_spec

            # WA-01: the answer completed a capture draft (e.g. "which
            # worker?" answered) -- save it now instead of asking "Confirm?".
            # _deliver_handled sends the reply and writes the audit rows.
            if (
                isinstance(slot_handled.result, WorkflowRunResult)
                and slot_handled.result.status is WorkflowRunStatus.STARTED
                and await _save_first_now()
            ):
                return

            reply = render_workflow_run_reply_spec(slot_handled.result)
            await send_reply_spec(
                reply,
                wa_id,
                send_text=sender.send_text,
                send_list=sender.send_list,
                send_button=sender.send_button,
            )
            # The other half of worker promotion: answering the offer arrives
            # here, as a slot answer. The node decided who to add but cannot
            # write (it is pure), so the inserts happen on this side. Same
            # reason as the fast path above -- inbound_journey never runs for
            # a slot answer either.
            from runtime.inbound_journey import (
                _create_promoted_workers,
                _offer_team_photo,
                _promotion_just_finished,
            )

            try:
                await _create_promoted_workers(
                    slot_handled.result,
                    workforce_query,
                    ctx,
                    wa_id,
                    sender.send_text,
                )
            except Exception:  # noqa: BLE001 — never disturbs saved attendance
                _log.exception("worker_promotion.create_failed user=%s", ctx.user_id)
            # The promotion question is now answered, so the team-photo offer
            # follows. The report id was parked when the attendance was
            # confirmed; nothing here needs to know it.
            if _promotion_just_finished(slot_handled.result):
                pending_report = await _safe_pop_pending_report(
                    team_photo_hint_store, ctx.user_id
                )
                if pending_report:
                    await _offer_team_photo(
                        pending_report, ctx, wa_id, team_photo_hint_store, _send_spec
                    )
            await asyncio.gather(
                message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=reply.text
                ),
                message_logger.link_workflow_instance(
                    correlation_id=message.correlation_id,
                    workflow_instance_id=slot_handled.result.workflow_instance_id,
                ) if slot_handled.result.workflow_instance_id else asyncio.sleep(0),
                message_logger.update_context(
                    correlation_id=message.correlation_id,
                    project_id=slot_handled.project_id,
                    site_id=slot_handled.site_id,
                ),
                message_logger.mark_completed(correlation_id=message.correlation_id),
                return_exceptions=True,
            )
            return

        # Deterministic "create/rename/deactivate account" command (Finance
        # Module Slice 6, account-admin scope) -- bypasses the AI pipeline
        # entirely, same priority as the slot-answer/confirmation fast paths
        # above. See runtime/account_admin_journey.py.
        # Only when finance is switched on (WA-07): otherwise the message falls
        # through to the normal path, whose module gate answers it politely.
        account_admin_handled = None
        if workflow_registry.module_is_enabled("finance"):
            try:
                account_admin_handled = await try_handle_account_admin_command(
                    message, ctx, workflow_runtime
                )
                timer.lap("account_admin_command")
            except Exception:  # noqa: BLE001 — a resume error must not drop the message
                _log.exception("account_admin.command_failed user=%s", ctx.user_id)
                account_admin_handled = None
        if account_admin_handled is not None:
            # send_reply_spec, not sender.send_text -- account_admin_handled
            # .reply carries Yes/No buttons for a real confirmable draft
            # (e.g. "Create account Site Cash?"), and send_text would have
            # silently dropped them to plain "Reply YES/NO" text, the same
            # bug class the member-create chain had.
            await send_reply_spec(
                account_admin_handled.reply,
                wa_id,
                send_text=sender.send_text,
                send_list=sender.send_list,
                send_button=sender.send_button,
            )
            run = account_admin_handled.workflow_run
            await asyncio.gather(
                message_logger.log_reply(
                    correlation_id=message.correlation_id,
                    reply=account_admin_handled.reply.text,
                ),
                message_logger.link_workflow_instance(
                    correlation_id=message.correlation_id,
                    workflow_instance_id=run.workflow_instance_id,
                ) if (run is not None and run.workflow_instance_id) else asyncio.sleep(0),
                message_logger.mark_completed(correlation_id=message.correlation_id),
                return_exceptions=True,
            )
            return

        # Category-menu tap (from render_direct_reply's greeting list): a
        # deterministic reply, no AI call, no workflow state touched. Runs
        # after the confirmation fast path so a pending confirmation still
        # wins over a stale menu tap from an earlier message. See
        # InteractionHandler.handle_category_tap for why this lives there.
        category_prompt = interaction_handler.handle_category_tap(message)
        if category_prompt is not None:
            row_id = message.metadata.get("interactive_reply_id")
            hint = CATEGORY_SEMANTIC_HINT.get(row_id) if row_id else None
            if hint:
                try:
                    await category_hint_store.set_hint(user_id=ctx.user_id, semantic_hint=hint)
                except Exception:  # noqa: BLE001 — a hint is a nudge, never worth losing the reply
                    _log.exception("category_hint.set_failed user=%s", ctx.user_id)
            await send_reply_spec(
                category_prompt,
                wa_id,
                send_text=sender.send_text,
                send_list=sender.send_list,
                send_button=sender.send_button,
            )
            await message_logger.log_reply(
                correlation_id=message.correlation_id, reply=category_prompt.text
            )
            await message_logger.mark_completed(correlation_id=message.correlation_id)
            return

        # Material Arrived/Used button tap (from render_category_prompt's
        # "cat_material" case) -- locks direction as a fallback default for
        # canonicalization (see build_canonical_event's direction_hint), never
        # an override of what the report itself says. Deterministic, no AI,
        # same principle as the category tap above.
        material_direction_prompt = interaction_handler.handle_material_direction_tap(message)
        if material_direction_prompt is not None:
            row_id = message.metadata.get("interactive_reply_id")
            direction = "received" if row_id == "dir_received" else "used"
            try:
                await category_hint_store.set_hint(
                    user_id=ctx.user_id, semantic_hint="material_update", direction=direction
                )
            except Exception:  # noqa: BLE001 — a hint is a nudge, never worth losing the reply
                _log.exception("category_hint.set_failed user=%s", ctx.user_id)
            await sender.send_text(wa_id, material_direction_prompt)
            await message_logger.log_reply(
                correlation_id=message.correlation_id, reply=material_direction_prompt
            )
            await message_logger.mark_completed(correlation_id=message.correlation_id)
            return

        # A tap on the "what is this photo for?" list (see
        # interactions/image_purpose.py and channel/replies.IMAGE_PURPOSE_ROWS)
        # -- resumes the whole HELD BATCH (not this tap message) with the
        # chosen purpose. Deterministic tap detection, same principle as the
        # two fast paths above. #2 Batch Media: the batch can hold more than
        # one photo (a burst); "img_site_update" attaches ALL of them to the
        # open activity in one write, while "img_expense"/"img_attendance"
        # still only process the FIRST through the normal single-report
        # confirm flow (see render_batch_overflow_reply's docstring for why).
        image_purpose_row_id = interaction_handler.handle_image_purpose_tap(message)
        if image_purpose_row_id is not None:
            from channel.replies import (
                IMAGE_PURPOSE_SEMANTIC_HINT,
                render_batch_overflow_reply,
                render_evidence_attached_reply,
                render_no_open_activity_for_evidence_reply,
            )

            held_batch = await pending_media_store.pop_batch(user_id=ctx.user_id)
            timer.lap("pop_pending_media")
            if not held_batch:
                expired_reply = "That photo has expired — please resend it."
                await sender.send_text(wa_id, expired_reply)
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=expired_reply
                )
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return

            if image_purpose_row_id == "img_site_update":
                # Evidence attach is a direct write, never a confirmable
                # workflow (see AttachEvidenceCommand's docstring) -- no
                # single-active-invariant concern, so the WHOLE batch
                # attaches in one shot regardless of size.
                found = await activity_query.find_open_activity(
                    organization_id=ctx.organization_id,
                    site_id=None,
                    reported_by_user_id=ctx.user_id,
                )
                if found is None:
                    reply_text = render_no_open_activity_for_evidence_reply()
                else:
                    media_keys = [m.media.object_key for m in held_batch if m.media is not None]
                    created_ids = await evidence_query.attach_photos(
                        organization_id=ctx.organization_id,
                        activity_id=found["activity_id"],
                        media_object_keys=media_keys,
                        uploaded_by=ctx.user_id,
                        correlation_id=message.correlation_id,
                    )
                    summary_bits = [
                        b for b in (found.get("work_type"), found.get("narrative")) if b
                    ]
                    activity_summary = " — ".join(summary_bits) if summary_bits else None
                    reply_text = render_evidence_attached_reply(
                        count=len(created_ids), activity_summary=activity_summary
                    )
                await sender.send_text(wa_id, reply_text)
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=reply_text
                )
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return

            held_message = held_batch[0]
            _fire_processing_ack(wa_id, held_message.modality)
            held_journey = await process_inbound_message(
                held_message,
                actor_user_id=ctx.user_id,
                actor=ctx,
                semantic_hint=IMAGE_PURPOSE_SEMANTIC_HINT[image_purpose_row_id],
                category_hint_store=category_hint_store,
                pipeline=pipeline,
                context_resolver=context_resolver,
                planner=planner,
                workflow_runtime=workflow_runtime,
                interaction_handler=interaction_handler,
                send_text=sender.send_text_capturing_id,
                send_list=sender.send_list,
                send_button=sender.send_button,
                send_image=sender.send_image,
                send_document=sender.send_document,
                object_storage=object_storage,
                context_debug=settings.context_debug,
                message_logger=message_logger,
                trace_logger=trace_logger,
                inventory_query=inventory_query,
                catalog_query=catalog_query,
                org_settings_query=org_settings_query,
                expense_category_query=expense_category_query,
                money_account_query=money_account_query,
                petty_cash_query=petty_cash_query,
                reversal_query=reversal_query,
                site_issue_query=site_issue_query,
                duplicate_expense_query=duplicate_expense_query,
                workforce_query=workforce_query,
                activity_query=activity_query,
                labour_query_service=labour_query_service,
                activity_search_service=activity_search_service,
                dpr_request_query=dpr_request_query,
                project_detail_query=project_detail_query,
                vendor_query=vendor_query,
                expense_query_service=expense_query_service,
                pending_report_store=pending_report_store,
                decomposition=decomposition,
                plan_store=plan_store,
                pending_decomposition_store=pending_decomposition_store,
                memory_loader=memory_loader,
                memory_coordinator=memory_coordinator,
                escalation_query=escalation_query,
                capability_help=capability_help,
                first_message_query=first_message_query,
                member_resolver=member_resolver,
                reply_composer=reply_composer,
                user_language_store=user_language_store,
            )
            timer.lap("process_inbound_message_held_media")
            await _save_first_after_journey(held_journey)
            if len(held_batch) > 1:
                overflow_reply = render_batch_overflow_reply(
                    held_count=len(held_batch), remaining_count=len(held_batch) - 1
                )
                await sender.send_text(wa_id, overflow_reply)
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=overflow_reply
                )
            await message_logger.mark_completed(correlation_id=message.correlation_id)
            return

        # Bare "hi"/"menu"/"help"/etc (see greeting_phrases.json): the AI
        # pipeline is never touched, same principle as the two fast paths
        # above. Text only -- voice can't be checked until Sarvam
        # transcribes it, so the identical check runs again inside
        # understanding/pipeline.py post-transcription instead.
        # handle_greeting_trigger is pure and I/O-free, so probing it first
        # to decide whether the first-message lookup is worth doing costs
        # nothing -- and keeps that database read off every message that
        # isn't a greeting, which is nearly all of them.
        greeting_reply = interaction_handler.handle_greeting_trigger(message)
        if greeting_reply is not None:
            greeting_reply = interaction_handler.handle_greeting_trigger(
                message,
                is_first_message=await first_message_query.is_first_message(
                    sender_wa_id=wa_id, correlation_id=message.correlation_id
                ),
            )
        if greeting_reply is not None and reply_composer is not None and user_language_store is not None:
            # WA-11: in the language this sender last spoke. English (or not
            # known yet) returns at once with no AI call, so "hi" stays instant.
            known_language = await user_language_store.get(user_id=ctx.user_id)
            if known_language is not None:
                greeting_text = await reply_composer.compose(
                    greeting_reply.text,
                    language=known_language,
                    correlation_id=message.correlation_id,
                )
                greeting_reply = dataclasses.replace(greeting_reply, text=greeting_text)
        if greeting_reply is not None:
            if greeting_reply.list_rows:
                await sender.send_list(
                    wa_id,
                    body=greeting_reply.text,
                    button_label=greeting_reply.list_button_label or "Choose one",
                    rows=list(greeting_reply.list_rows),
                )
            else:
                await sender.send_text(wa_id, greeting_reply.text)
            await message_logger.log_reply(
                correlation_id=message.correlation_id, reply=greeting_reply.text
            )
            await message_logger.mark_completed(correlation_id=message.correlation_id)
            return

        # Bare "who am i"/"whoami"/"my profile"/etc (see
        # workflows/who_am_i/phrases.json): deterministic identity-lookup
        # fast path, same principle as the greeting trigger above -- the AI
        # pipeline is never touched. Uses ctx (already resolved above), so
        # no extra DB round-trip.
        whoami_reply_text = interaction_handler.handle_whoami_trigger(message, ctx)
        if whoami_reply_text is not None:
            await sender.send_text(wa_id, whoami_reply_text)
            await message_logger.log_reply(
                correlation_id=message.correlation_id, reply=whoami_reply_text
            )
            await message_logger.mark_completed(correlation_id=message.correlation_id)
            return

        # Phase 6 perf: all of the resume_pending_report_with_* checks below can
        # only ever return something when the incoming message is a button/list tap
        # (InputModality.INTERACTIVE). For text and voice messages they always
        # return None, so we skip them entirely — eliminating up to 8 sequential
        # DB reads (pending_report_store lookups) from every normal message.
        if message.modality is InputModality.INTERACTIVE:
            # A tap on the material picker sent by the material-resolution gate
            # (runtime/inbound_journey.py, ambiguous/unmatched material name) --
            # resumes with material_id filled in and re-runs the remaining gates
            # (unit, then project) rather than assuming those are settled.
            material_reply = await resume_pending_report_with_material(
                message,
                ctx.user_id,
                pending_report_store=pending_report_store,
                catalog_query=catalog_query,
                planner=planner,
                workflow_runtime=workflow_runtime,
                actor=ctx,
                inventory_query=inventory_query,
                message_logger=message_logger,
                # Needed by the "None of these" leg to decide whether this
                # sender may be offered the create option (STA-139's org
                # setting), same check the gate itself makes.
                org_settings_query=org_settings_query,
            )
            timer.lap("resume_material")
            if material_reply is not None:
                await send_reply_spec(
                    material_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=material_reply.text
                )
                return

            # A Yes/No tap on the "add this material to the catalog?" offer sent
            # when a reported name matched nothing and the sender's role is
            # allowed to create one (STA-139). Checked before the Stock Unit
            # mismatch resume below -- distinct row-id prefixes, but these two
            # answer different questions and must stay separately dispatched.
            material_create_reply = await resume_pending_report_with_material_create(
                message,
                ctx.user_id,
                pending_report_store=pending_report_store,
                catalog_query=catalog_query,
                planner=planner,
                workflow_runtime=workflow_runtime,
                actor=ctx,
                inventory_query=inventory_query,
                message_logger=message_logger,
            )
            timer.lap("resume_material_create")
            if material_create_reply is not None:
                await send_reply_spec(
                    material_create_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=material_create_reply.text
                )
                return

            # A tap on the member-name picker sent by _run_member_name_gate
            # (ENTITY_RESOLUTION_PLAN.md) when a project-member name hint
            # matched one or more active users closely but not exactly --
            # resumes with member_name patched to the tapped user's exact
            # name, or falls through to the create offer for "Someone else".
            # A tap on "who should I remind?" -- _run_audience_name_gate's
            # Ambiguous case. Answering re-enters that gate, so a reminder
            # naming several unknown people is simply this leg, repeated.
            aud_reply = await resume_pending_report_with_audience_candidate(
                message,
                ctx.user_id,
                pending_report_store=pending_report_store,
                member_resolver=member_resolver,
                planner=planner,
                workflow_runtime=workflow_runtime,
                actor=ctx,
                inventory_query=inventory_query,
                message_logger=message_logger,
            )
            timer.lap("resume_audience_candidate")
            if aud_reply is not None:
                await send_reply_spec(
                    aud_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=aud_reply.text
                )
                return

            # A tap on "who is this cash for?" -- _run_petty_cash_recipient_
            # gate's Ambiguous case. Checked before the member picker below:
            # both resolve a person, and only the row-id prefix distinguishes
            # which request is being continued.
            pcr_reply = await resume_pending_report_with_petty_cash_recipient(
                message,
                ctx.user_id,
                pending_report_store=pending_report_store,
                member_resolver=member_resolver,
                petty_cash_query=petty_cash_query,
                planner=planner,
                workflow_runtime=workflow_runtime,
                actor=ctx,
                inventory_query=inventory_query,
                message_logger=message_logger,
            )
            timer.lap("resume_petty_cash_recipient")
            if pcr_reply is not None:
                await send_reply_spec(
                    pcr_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=pcr_reply.text
                )
                return

            member_candidate_reply = await resume_pending_report_with_member_candidate(
                message,
                ctx.user_id,
                pending_report_store=pending_report_store,
                member_resolver=member_resolver,
                planner=planner,
                workflow_runtime=workflow_runtime,
                actor=ctx,
                inventory_query=inventory_query,
                message_logger=message_logger,
            )
            timer.lap("resume_member_candidate")
            if member_candidate_reply is not None:
                await send_reply_spec(
                    member_candidate_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=member_candidate_reply.text
                )
                return

            # A Yes/No tap on "create this user and continue adding them to
            # the project?" -- _run_member_name_gate's Missing case. Yes
            # starts the CREATE_USER -> ADD_PROJECT_MEMBER chain (see
            # resume.py's start_member_create_plan); its own reply is
            # CREATE_USER's first question (usually the phone number), not a
            # finished confirmation -- distinct row-id prefix from every
            # other resume above, dispatched independently.
            member_create_reply = await resume_pending_report_with_member_create_offer(
                message,
                ctx.user_id,
                pending_report_store=pending_report_store,
                plan_store=plan_store,
                workflow_runtime=workflow_runtime,
                actor=ctx,
                message_logger=message_logger,
                recent_turns=recent_turns_store,
            )
            timer.lap("resume_member_create")
            if member_create_reply is not None:
                await send_reply_spec(
                    member_create_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=member_create_reply.text
                )
                return

            # A Yes/No tap on the whole-plan preview (docs/execution/
            # COMPOSITE_REQUEST_PLAN_LAYER.md §8) -- decomposed_plan.py's
            # try_start_decomposed_plan persisted an all-PENDING Plan and sent
            # this preview; nothing runs until Yes. Distinct row-id pair from
            # every other resume above, dispatched independently.
            plan_confirm_reply = await resume_pending_plan_confirmation(
                message,
                ctx.user_id,
                plan_store=plan_store,
                workflow_runtime=workflow_runtime,
                message_logger=message_logger,
            )
            timer.lap("resume_plan_confirmation")
            if plan_confirm_reply is not None:
                await send_reply_spec(
                    plan_confirm_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=plan_confirm_reply.text
                )
                return

            # A tap on the unit picker shown when a brand-new material's Stock
            # Unit couldn't be inferred from the report's own words -- creates
            # the catalog entry and continues the held report.
            material_unit_reply = await resume_pending_report_with_material_unit_choice(
                message,
                ctx.user_id,
                pending_report_store=pending_report_store,
                catalog_query=catalog_query,
                planner=planner,
                workflow_runtime=workflow_runtime,
                actor=ctx,
                inventory_query=inventory_query,
                message_logger=message_logger,
            )
            timer.lap("resume_material_unit_choice")
            if material_unit_reply is not None:
                await send_reply_spec(
                    material_unit_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=material_unit_reply.text
                )
                return

            # A Yes/No tap on the Stock Unit mismatch clarification -- resumes
            # with unit_id filled in (or tells the sender to resend on "No") and
            # re-runs the project gate before planner/workflow.
            unit_reply = await resume_pending_report_with_unit(
                message,
                ctx.user_id,
                pending_report_store=pending_report_store,
                catalog_query=catalog_query,
                planner=planner,
                workflow_runtime=workflow_runtime,
                actor=ctx,
                inventory_query=inventory_query,
                message_logger=message_logger,
            )
            timer.lap("resume_unit")
            if unit_reply is not None:
                await send_reply_spec(
                    unit_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=unit_reply.text
                )
                return

            # A tap on one of the three buttons sent by the stock sufficiency
            # gate (runtime/inbound_journey.py, usage quantity greater than what's
            # in stock) -- resumes with the report capped/switched-to-arrival/
            # cancelled per the tap, same principle as the other interactive fast
            # paths above.
            stock_reply = await resume_pending_report_with_stock_choice(
                message,
                ctx.user_id,
                pending_report_store=pending_report_store,
                planner=planner,
                workflow_runtime=workflow_runtime,
                inventory_query=inventory_query,
                message_logger=message_logger,
            )
            timer.lap("resume_stock_choice")
            if stock_reply is not None:
                await send_reply_spec(
                    stock_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=stock_reply.text
                )
                return

            # A tap on the project-picker list sent by the project-selection gate
            # (runtime/inbound_journey.py, when a report was otherwise complete
            # but no project could be resolved) -- resumes the held report with
            # the chosen project_id and runs planner/workflow directly, same
            # principle as the other interactive fast paths above.
            project_reply = await resume_pending_report_with_project(
                message,
                ctx.user_id,
                pending_report_store=pending_report_store,
                planner=planner,
                workflow_runtime=workflow_runtime,
                actor=ctx,
                inventory_query=inventory_query,
                message_logger=message_logger,
            )
            timer.lap("resume_project")
            if project_reply is not None:
                await send_reply_spec(
                    project_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=project_reply.text
                )
                return

            # A tap on the site-picker list sent by the site-selection gate
            # (runtime/inbound_journey.py, once project is settled but the
            # project has more than one site) -- resumes the held report/query
            # with the chosen site_id (or None for "All Sites Combined") and
            # runs planner/workflow directly, same principle as the other
            # interactive fast paths above.
            site_reply = await resume_pending_report_with_site(
                message,
                ctx.user_id,
                pending_report_store=pending_report_store,
                planner=planner,
                workflow_runtime=workflow_runtime,
                actor=ctx,
                inventory_query=inventory_query,
                message_logger=message_logger,
            )
            timer.lap("resume_site")
            if site_reply is not None:
                await send_reply_spec(
                    site_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=site_reply.text
                )
                return

            # A tap on the project/site picker sent by
            # decomposed_plan.py's _resolve_project_and_site (docs/execution/
            # COMPOSITE_REQUEST_PLAN_LAYER.md §14) -- the whole-decomposition
            # equivalent of the two resumes just above, checked after them:
            # both share the exact same "proj_"/"site_" row-id prefixes, and
            # a user is only ever in one pending state at a time, so
            # whichever store (PendingReportStore vs
            # PendingDecompositionStore) actually holds something answers,
            # while the other's resume safely no-ops.
            plan_project_reply = await resume_pending_decomposition_with_project(
                message,
                ctx.user_id,
                pending_decomposition_store=pending_decomposition_store,
                plan_store=plan_store,
                pipeline=pipeline,
                actor=ctx,
                catalog_query=catalog_query,
                inventory_query=inventory_query,
                org_settings_query=org_settings_query,
            )
            timer.lap("resume_plan_project")
            if plan_project_reply is not None:
                await send_reply_spec(
                    plan_project_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=plan_project_reply.text
                )
                return

            plan_site_reply = await resume_pending_decomposition_with_site(
                message,
                ctx.user_id,
                pending_decomposition_store=pending_decomposition_store,
                plan_store=plan_store,
                pipeline=pipeline,
                actor=ctx,
                catalog_query=catalog_query,
                inventory_query=inventory_query,
                org_settings_query=org_settings_query,
            )
            timer.lap("resume_plan_site")
            if plan_site_reply is not None:
                await send_reply_spec(
                    plan_site_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=plan_site_reply.text
                )
                return

            # Phase A5 (docs/execution/UNIFIED_UNDERSTANDING_PIPELINE.md): a
            # decomposition segment's own material/unit/stock gate, held the
            # same way the project/site gates above are -- five taps, one
            # per resume leg, mirroring resume.py's own five single-message
            # legs for the identical row-id shapes (mat_/matnew_/matunit_/
            # unit_yes_+unit_no/stock_*). Order does not matter for
            # correctness (each checks its own row-id prefix/set and no-ops
            # otherwise), only for which one actually answers a given tap.
            plan_material_reply = await resume_pending_decomposition_with_material(
                message,
                ctx.user_id,
                pending_decomposition_store=pending_decomposition_store,
                plan_store=plan_store,
                pipeline=pipeline,
                actor=ctx,
                catalog_query=catalog_query,
                inventory_query=inventory_query,
                org_settings_query=org_settings_query,
            )
            timer.lap("resume_plan_material")
            if plan_material_reply is not None:
                await send_reply_spec(
                    plan_material_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=plan_material_reply.text
                )
                return

            plan_material_create_reply = await resume_pending_decomposition_with_material_create(
                message,
                ctx.user_id,
                pending_decomposition_store=pending_decomposition_store,
                plan_store=plan_store,
                pipeline=pipeline,
                actor=ctx,
                catalog_query=catalog_query,
                inventory_query=inventory_query,
                org_settings_query=org_settings_query,
            )
            timer.lap("resume_plan_material_create")
            if plan_material_create_reply is not None:
                await send_reply_spec(
                    plan_material_create_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=plan_material_create_reply.text
                )
                return

            plan_material_unit_reply = await resume_pending_decomposition_with_material_unit_choice(
                message,
                ctx.user_id,
                pending_decomposition_store=pending_decomposition_store,
                plan_store=plan_store,
                pipeline=pipeline,
                actor=ctx,
                catalog_query=catalog_query,
                inventory_query=inventory_query,
                org_settings_query=org_settings_query,
            )
            timer.lap("resume_plan_material_unit")
            if plan_material_unit_reply is not None:
                await send_reply_spec(
                    plan_material_unit_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=plan_material_unit_reply.text
                )
                return

            plan_unit_reply = await resume_pending_decomposition_with_unit(
                message,
                ctx.user_id,
                pending_decomposition_store=pending_decomposition_store,
                plan_store=plan_store,
                pipeline=pipeline,
                actor=ctx,
                catalog_query=catalog_query,
                inventory_query=inventory_query,
                org_settings_query=org_settings_query,
            )
            timer.lap("resume_plan_unit")
            if plan_unit_reply is not None:
                await send_reply_spec(
                    plan_unit_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=plan_unit_reply.text
                )
                return

            plan_stock_reply = await resume_pending_decomposition_with_stock_choice(
                message,
                ctx.user_id,
                pending_decomposition_store=pending_decomposition_store,
                plan_store=plan_store,
                pipeline=pipeline,
                actor=ctx,
                catalog_query=catalog_query,
                inventory_query=inventory_query,
                org_settings_query=org_settings_query,
            )
            timer.lap("resume_plan_stock")
            if plan_stock_reply is not None:
                await send_reply_spec(
                    plan_stock_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=plan_stock_reply.text
                )
                return

        # #25 AI Follow-up: if Mesiri just asked "want to attach a
        # completion photo?" (interactions/handler.py, after an Activity is
        # marked COMPLETED), the very next photo answers that question --
        # skip the normal "what is this for?" picker entirely and attach
        # directly. Checked BEFORE the picker gate below on purpose: this
        # hint is pop-once and must not be silently skipped past for an
        # unrelated later photo.
        if message.modality is InputModality.IMAGE and message.media is not None:
            completion_activity_id = await completion_photo_hint_store.pop_hint(
                user_id=ctx.user_id
            )
            if completion_activity_id is not None:
                from channel.replies import render_evidence_attached_reply

                created_ids = await evidence_query.attach_photos(
                    organization_id=ctx.organization_id,
                    activity_id=completion_activity_id,
                    media_object_keys=[message.media.object_key],
                    uploaded_by=ctx.user_id,
                    correlation_id=message.correlation_id,
                )
                reply_text = render_evidence_attached_reply(
                    count=len(created_ids), activity_summary=None
                )
                await sender.send_text(wa_id, reply_text)
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=reply_text
                )
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return

        # A photo sent right after Mesiri offered a team photo is plainly the
        # answer to that offer, so it attaches straight to the attendance
        # record. Checked before the purpose picker for the same reason the
        # completion-photo hint is: asking "what is this photo for?" about a
        # question Mesiri itself just asked is absurd, and the hint is
        # pop-once so it must not be stepped past.
        if message.modality is InputModality.IMAGE and message.media is not None:
            team_photo_report_id = await _safe_pop_pending_report(
                team_photo_hint_store, ctx.user_id
            )
            if team_photo_report_id is not None:
                from channel.replies import render_team_photo_attached_reply

                attachment_id = None
                try:
                    attachment_id = await workforce_query.attach_team_photo(
                        organization_id=ctx.organization_id,
                        report_id=team_photo_report_id,
                        media_object_key=message.media.object_key,
                        created_by=ctx.user_id,
                    )
                except Exception:  # noqa: BLE001 — a failed photo never unsettles attendance
                    _log.exception(
                        "team_photo.attach_failed user=%s report=%s",
                        ctx.user_id,
                        team_photo_report_id,
                    )
                if attachment_id:
                    _log.info(
                        "team_photo.attached user=%s report=%s attachment=%s",
                        ctx.user_id,
                        team_photo_report_id,
                        attachment_id,
                    )
                    reply_text = render_team_photo_attached_reply()
                else:
                    # Say so rather than going quiet: a supervisor who sent a
                    # photo and heard nothing cannot tell it failed from it
                    # having worked.
                    reply_text = (
                        "⚠️ I couldn't attach that photo to today's attendance. "
                        "The attendance itself is safely recorded — you can add "
                        "the photo from the dashboard."
                    )
                await sender.send_text(wa_id, reply_text)
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=reply_text
                )
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return

        # A genuinely new image (not a tap answering the picker above) is
        # held while we ask "what is this photo for?" instead of running
        # understanding/vision straight away -- a bare photo often arrives
        # with no caption saying what it's for. See
        # interactions/image_purpose.py.
        image_purpose_reply = await try_hold_new_image_for_purpose_picker(
            message, user_id=ctx.user_id, pending_media_store=pending_media_store
        )
        timer.lap("image_purpose_picker")
        if image_purpose_reply is not None:
            await send_reply_spec(
                image_purpose_reply,
                wa_id,
                send_text=sender.send_text,
                send_list=sender.send_list,
                send_button=sender.send_button,
            )
            await message_logger.log_reply(
                correlation_id=message.correlation_id, reply=image_purpose_reply.text
            )
            await message_logger.mark_completed(correlation_id=message.correlation_id)
            return

        category_hint = await category_hint_store.pop_hint(user_id=ctx.user_id)
        timer.lap("pop_category_hint")
        # #6 Undo: a bare "undo"/"delete that" (mesiri_ai.undo_classifier) --
        # deterministic, zero-cost, same principle as the greeting/whoami
        # triggers above. Checked THIS message's own text directly (unlike
        # category_hint, which biases the NEXT message) and wins over any
        # stale category_hint from an unrelated earlier tap -- an explicit
        # "undo" right now must not be diluted by a leftover hint.
        undo_hint = (
            UNDO_SEMANTIC_HINT
            if message.modality is InputModality.TEXT and is_undo_trigger(message.text)
            else None
        )
        # WA-01: "UNDO" right after a save-first update removes that draft
        # (through its own module's undo). Only when there is no recent draft
        # of the sender's does it fall through to the older undo handling.
        if undo_hint is not None:
            try:
                undo_reply = await interaction_handler.undo_latest_draft(
                    organization_id=str(ctx.organization_id), user_id=ctx.user_id
                )
            except Exception:  # noqa: BLE001 -- fall back to the older undo handling
                _log.exception("save_first.undo_failed user=%s", ctx.user_id)
                undo_reply = None
            if undo_reply is not None:
                await sender.send_text(wa_id, undo_reply)
                await message_logger.log_reply(correlation_id=message.correlation_id, reply=undo_reply)
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return
        _fire_processing_ack(wa_id, message.modality)
        journey = await process_inbound_message(
            message,
            actor_user_id=ctx.user_id,
            actor=ctx,
            semantic_hint=undo_hint or (category_hint.semantic_hint if category_hint else None),
            direction_hint=category_hint.direction if category_hint else None,
            category_hint_store=category_hint_store,
            pipeline=pipeline,
            context_resolver=context_resolver,
            planner=planner,
            workflow_runtime=workflow_runtime,
            interaction_handler=interaction_handler,
            send_text=sender.send_text_capturing_id,
            send_list=sender.send_list,
            send_button=sender.send_button,
            send_image=sender.send_image,
            send_document=sender.send_document,
            object_storage=object_storage,
            context_debug=settings.context_debug,
            message_logger=message_logger,
            trace_logger=trace_logger,
            inventory_query=inventory_query,
            catalog_query=catalog_query,
            org_settings_query=org_settings_query,
            expense_category_query=expense_category_query,
            money_account_query=money_account_query,
            petty_cash_query=petty_cash_query,
            reversal_query=reversal_query,
            site_issue_query=site_issue_query,
            duplicate_expense_query=duplicate_expense_query,
            workforce_query=workforce_query,
            activity_query=activity_query,
            labour_query_service=labour_query_service,
            activity_search_service=activity_search_service,
            dpr_request_query=dpr_request_query,
            project_detail_query=project_detail_query,
            vendor_query=vendor_query,
            expense_query_service=expense_query_service,
            pending_report_store=pending_report_store,
            decomposition=decomposition,
            plan_store=plan_store,
            pending_decomposition_store=pending_decomposition_store,
            memory_loader=memory_loader,
            memory_coordinator=memory_coordinator,
            escalation_query=escalation_query,
            capability_help=capability_help,
            first_message_query=first_message_query,
            member_resolver=member_resolver,
            reply_composer=reply_composer,
            user_language_store=user_language_store,
        )
        timer.lap("process_inbound_message")
        await _save_first_after_journey(journey)

    return _on_normalized, _mark_read_on_claim
