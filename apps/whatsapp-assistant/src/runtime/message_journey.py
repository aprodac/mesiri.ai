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
from mesiri.infrastructure.postgres.tenant import bind_tenant, tenant_scope
from mesiri_ai.undo_classifier import UNDO_SEMANTIC_HINT, is_undo_trigger
from mesiri_contracts.assistant.enums import InputModality
from runtime import forward_batch
from runtime.account_admin_journey import try_handle_account_admin_command
from runtime.ai_outage import AIUnavailableError, retry_attempt
from runtime.reply_composer import (
    QUESTION,
    SETUP_OFFER,
    TEAM_PHOTO,
    UNDO_ROW,
    Offer,
    compose,
    fold_note,
    let_go_note,
    resolve_choice,
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
    from interactions.project_setup_offer import ProjectSetupOfferStore
    from interactions.team_photo_hint import TeamPhotoHintStore
    from memory.context_loader import ConversationMemoryLoader
    from memory.coordinator import ConversationMemoryCoordinator
    from memory.recent_turns import RecentTurnsStore
    from mesiri_contracts.common.storage import ObjectStoragePort
    from planning.plan_store import PlanStore
    from runtime.activity_query import ActivityQueryService
    from runtime.activity_search_service import ActivitySearchService
    from runtime.contact_share_journey import ContactShareJourney
    from runtime.dependencies import Settings
    from runtime.dpr_request_query import DprRequestQueryService
    from runtime.duplicate_expense_query import DuplicateExpenseQueryService
    from runtime.evidence_query import EvidenceAttachService
    from runtime.expense_query_service import ExpenseQueryService
    from runtime.first_message_query import FirstMessageQueryService
    from runtime.inventory_query import MaterialInventoryQueryService
    from runtime.labour_query_service import LabourQueryService
    from runtime.logging_ports import MessageLogger, TraceLogger
    from runtime.material_catalog_query import MaterialCatalogQueryService
    from runtime.money_account_query import MoneyAccountQueryService
    from runtime.onboarding_progress import OnboardingProgress
    from runtime.org_settings_query import OrganizationSettingsQueryService
    from runtime.project_detail_query import ProjectDetailQueryService
    from runtime.reply_language import ReplyComposer, UserLanguageStore
    from runtime.reversal_query import ReversalTargetQueryService
    from runtime.setup_questions import SetupQuestions
    from runtime.signup_journey import SignupJourney
    from runtime.site_day_review import SiteDayReview
    from runtime.trial_journey import TrialJourney
    from runtime.vendor_query import VendorQueryService
    from runtime.workforce_query import WorkforceQueryService
    from understanding.pipeline import UnderstandingPipeline
    from workflows import WorkflowRuntime

_log = logging.getLogger("mesiri.context")

#: How long a reply waits for its receipt card before going out without it.
RECEIPT_TIMEOUT_S = 4.0

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
    workflow_runtime: WorkflowRuntime,
    interaction_handler: InteractionHandler,
    object_storage: ObjectStoragePort,
    message_logger: MessageLogger,
    trace_logger: TraceLogger,
    inventory_query: MaterialInventoryQueryService,
    catalog_query: MaterialCatalogQueryService,
    org_settings_query: OrganizationSettingsQueryService,
    money_account_query: MoneyAccountQueryService,
    reversal_query: ReversalTargetQueryService,
    duplicate_expense_query: DuplicateExpenseQueryService,
    workforce_query: WorkforceQueryService,
    activity_query: ActivityQueryService,
    evidence_query: EvidenceAttachService,
    first_message_query: FirstMessageQueryService,
    plan_store: PlanStore,
    member_resolver: Any | None = None,
    site_issue_query: Any | None = None,
    recent_turns_store: RecentTurnsStore,
    labour_query_service: LabourQueryService,
    activity_search_service: ActivitySearchService,
    dpr_request_query: DprRequestQueryService,
    project_detail_query: ProjectDetailQueryService,
    vendor_query: VendorQueryService,
    expense_query_service: ExpenseQueryService,
    pending_media_store: PendingMediaStore,
    category_hint_store: CategoryHintStore,
    completion_photo_hint_store: CompletionPhotoHintStore,
    team_photo_hint_store: TeamPhotoHintStore,
    project_setup_offer_store: ProjectSetupOfferStore,
    memory_loader: ConversationMemoryLoader,
    memory_coordinator: ConversationMemoryCoordinator,
    signup_journey: SignupJourney | None = None,
    opt_in_journey: Any = None,
    forward_batcher: Any = None,
    contact_share: ContactShareJourney | None = None,
    join_journey: Any = None,
    setup_questions: SetupQuestions | None = None,
    onboarding_progress: OnboardingProgress | None = None,
    logo_from_whatsapp: Any = None,
    site_day_review: SiteDayReview | None = None,
    trial_journey: TrialJourney | None = None,
    reply_composer: ReplyComposer | None = None,
    user_language_store: UserLanguageStore | None = None,
    trial_usage_guard: Any | None = None,
    agent_provider: Any | None = None,
    offered_choices_store: Any | None = None,
    work_site: Any | None = None,
    cards: Any | None = None,
    later: Any | None = None,
    card_renderer: Any | None = None,
    ops_alerts: Any | None = None,
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
        except AIUnavailableError:
            # Already told the sender it is queued (runtime/ai_outage.py); the
            # re-raise is what makes the ARQ worker retry the message.
            raise
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
        if forward_batch.is_capturing():
            return  # WA-02: a forwarded batch gets one summary, no acks
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

    # The sender each in-flight message resolved to, for the follow-up below.
    _resolved_actors: dict[str, Any] = {}
    # Request [45]: messages (by correlation id) that saved data, and the ones
    # already given the instant check-mark reaction.
    _saved_messages: set[str] = set()
    _conversational: set[str] = set()
    _acknowledged: set[str] = set()

    async def _run_journey(message, raw_payload, retry_of_id=None) -> None:  # type: ignore[no-untyped-def]
        with tenant_scope(None):  # BE-03: bound once the sender is known
            if forward_batcher is None:
                await _run_journey_scoped(message, raw_payload, retry_of_id)
                return
            wa_id = message.sender.wa_id
            # WA-02: a batch whose summary was lost (a restart) goes first.
            try:
                await forward_batcher.flush(wa_id, stale_only=True)
            except Exception:  # noqa: BLE001 -- never let it cost this message
                _log.exception("forward_batch.stale_flush_failed")
            if not forward_batch.is_forwarded(message):
                await _run_journey_scoped(message, raw_payload, retry_of_id)
                return
            # WA-02: processed as usual; its replies join the sender's batch.
            await forward_batcher.begin(wa_id)
            capture = None
            try:
                with forward_batcher.capturing() as capture:
                    await _run_journey_scoped(message, raw_payload, retry_of_id)
            finally:
                await forward_batcher.finish(
                    wa_id,
                    capture.sends if capture else [],
                    known_sender=capture.known_sender if capture else False,
                )

    async def _run_journey_scoped(message, raw_payload, retry_of_id) -> None:  # type: ignore[no-untyped-def]
        timer = StepTimer()
        try:
            try:
                await _run_journey_steps(message, raw_payload, retry_of_id, timer)
            finally:
                # The new message produced no reply of its own: the let-go
                # line still reaches the sender, alone.
                try:
                    await _flush_held_note(message.sender.wa_id)
                except Exception:  # noqa: BLE001
                    _log.exception("let_go_note.flush_failed")
            # SS-14: after Mesiri has answered the owner, today's setup
            # question (if any). Here, after every path's reply, rather than
            # in each of the journey's many early returns.
            actor = _resolved_actors.get(message.correlation_id)
            # SS-17: the setup-progress card, after the first saved update and
            # after each step. Before the setup question, which then stays
            # quiet that day. Saved replies count (that is the trigger).
            if (
                onboarding_progress is not None
                and actor is not None
                and message.correlation_id not in _agent_parked
                and message.correlation_id not in _conversational
            ):
                try:
                    from runtime.plan_executor import plan_has_more_to_do

                    if not await plan_has_more_to_do(plan_store, user_id=str(actor.user_id)):
                        await onboarding_progress.after_reply(
                            actor,
                            wa_id=message.sender.wa_id,
                            send_image=sender.send_image,
                            send_spec=lambda spec: send_reply_spec(
                                spec,
                                message.sender.wa_id,
                                send_text=sender.send_text,
                                send_list=sender.send_list,
                                send_button=sender.send_button,
                            ),
                        )
                except Exception:  # noqa: BLE001 — a card never breaks a reply
                    _log.exception("onboarding_card.follow_up_failed user=%s", actor.user_id)
            if (
                setup_questions is not None
                and actor is not None
                and message.correlation_id not in _agent_parked
                # Never after a reply that saved data: it waits for a light message.
                and message.correlation_id not in _saved_messages
                # [68]: nor after a question or small-talk reply: one message.
                and message.correlation_id not in _conversational
            ):
                try:
                    # Not in the middle of a multi-part note: the letterhead
                    # question waits until the plan has finished.
                    from runtime.plan_executor import plan_has_more_to_do

                    if not await plan_has_more_to_do(plan_store, user_id=str(actor.user_id)):
                        await setup_questions.after_reply(
                            actor,
                            send=lambda spec: send_reply_spec(
                                spec,
                                message.sender.wa_id,
                                send_text=sender.send_text,
                                send_list=sender.send_list,
                                send_button=sender.send_button,
                            ),
                        )
                except Exception:  # noqa: BLE001 — a setup question never breaks a reply
                    _log.exception("setup_question.follow_up_failed user=%s", actor.user_id)
        finally:
            _resolved_actors.pop(message.correlation_id, None)
            _saved_messages.discard(message.correlation_id)
            _conversational.discard(message.correlation_id)
            _acknowledged.discard(message.correlation_id)
            _agent_parked.discard(message.correlation_id)
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

    # -- Assistant agent (request [40]) -------------------------------------
    _agent_runner = None
    if agent_provider is not None:
        from runtime.agent.runner import AgentRunner

        _agent_runner = AgentRunner(agent_provider)
    #: Correlation ids whose reply ended on a question: the daily setup
    #: question must not pile a second one on top of it.
    _agent_parked: set[str] = set()

    async def _later_follow_up(message, ctx):  # type: ignore[no-untyped-def]
        """WA-57: after a Save tap, the message the agent runs on for the parts
        of the earlier message still to do; None after a Cancel or when none are."""
        from runtime.agent import save_button
        from runtime.agent.later import follow_up_text

        if later is None or agent_provider is None:
            return None
        parsed = save_button.parse_tap(str((message.metadata or {}).get("interactive_reply_id") or ""))
        if parsed is None or parsed[0] != save_button.SAVE:
            return None
        item = await later.ask_next(ctx)
        if item is None:
            return None
        metadata = {
            k: v
            for k, v in (message.metadata or {}).items()
            if k not in ("interactive_reply_id", "interactive_reply_type")
        }
        return message.model_copy(
            update={"text": follow_up_text(item), "modality": InputModality.TEXT, "metadata": metadata}
        )

    def _as_tap(message, row):  # type: ignore[no-untyped-def]
        """The message a tap on ``row`` would have been. Undo becomes the typed
        "undo", so a tap and the word run exactly the same handler."""
        metadata = {
            k: v
            for k, v in (message.metadata or {}).items()
            if k not in ("interactive_reply_id", "interactive_reply_type")
        }
        if row.id == UNDO_ROW.id:
            return message.model_copy(
                update={"text": "undo", "modality": InputModality.TEXT, "metadata": metadata}
            )
        metadata["interactive_reply_id"] = row.id
        metadata["interactive_reply_type"] = "button_reply"
        return message.model_copy(
            update={"text": row.title, "modality": InputModality.INTERACTIVE, "metadata": metadata}
        )

    async def _resolve_typed_choice(message, ctx):  # type: ignore[no-untyped-def]
        """Request [45]: the choices on our last reply are good for the next
        message only. A typed "undo" / "photo" / option title / number is the
        tap; anything else just clears them."""
        if offered_choices_store is None:
            return message
        try:
            rows = await offered_choices_store.take(user_id=ctx.user_id)
        except Exception:  # noqa: BLE001 -- a hint; the word is handled as before
            return message
        if not rows:
            return message
        if message.modality is InputModality.INTERACTIVE:
            if (message.metadata or {}).get("interactive_reply_id") == UNDO_ROW.id:
                return _as_tap(message, UNDO_ROW)
            return message
        if message.modality is not InputModality.TEXT:
            return message
        row = resolve_choice(message.text or "", rows)
        return _as_tap(message, row) if row is not None else message

    async def _acknowledge(message, wa_id: str) -> None:  # type: ignore[no-untyped-def]
        """A check-mark reaction on the worker's message: the instant "got it"
        that lets the reply be one message. Best effort, once per message."""
        if message.correlation_id in _acknowledged:
            return
        _acknowledged.add(message.correlation_id)
        react = getattr(sender, "send_reaction", None)
        if react is None:
            return
        try:
            await react(wa_id, message.message_id, "✅")
        except Exception:  # noqa: BLE001 -- never blocks the reply
            _log.warning("reaction.failed wa_id=%s", wa_id)

    async def _in_sender_language(spec, user_id: str):  # type: ignore[no-untyped-def]
        """``spec`` with its fixed wording and button titles in the language
        this sender last spoke (request [51]); unchanged when unknown. Wording
        never costs the reply."""
        if user_language_store is None:
            return spec
        try:
            from runtime.reply_language import localize_reply_spec

            language, script = await user_language_store.get_profile(user_id=user_id)
            return localize_reply_spec(spec, language, script)
        except Exception:  # noqa: BLE001
            _log.exception("reply.localize_failed user=%s", user_id)
            return spec

    #: A let-go question's one short line, waiting to ride inside the reply
    #: to the message that let it go (request [53]); sent alone only if that
    #: message produces no reply of its own.
    _held_notes: dict[str, str] = {}

    def _with_held_note(spec, wa_id: str):  # type: ignore[no-untyped-def]
        note = _held_notes.pop(wa_id, None)
        return fold_note(spec, note) if note else spec

    _held_users: dict[str, str] = {}

    async def _flush_held_note(wa_id: str) -> None:
        note = _held_notes.pop(wa_id, None)
        if note:
            await _send_composed(wa_id, _held_users.pop(wa_id, ""), ReplySpec(text=note))

    async def _send_composed(  # type: ignore[no-untyped-def]
        wa_id: str, user_id: str, spec, *, header_image: bytes | None = None
    ) -> None:
        """Send the composed reply and remember its choices for typed answers.
        ``header_image`` (the receipt card) rides inside it: the header of the
        button message, or the image right after a text-only reply."""
        if header_image is not None:
            spec = dataclasses.replace(spec, header_image=header_image)
        spec = await _in_sender_language(_with_held_note(spec, wa_id), user_id)
        await send_reply_spec(
            spec,
            wa_id,
            send_text=sender.send_text,
            send_list=sender.send_list,
            send_button=sender.send_button,
            send_image=sender.send_image,
        )
        options = list(spec.buttons or spec.list_rows or ())
        if offered_choices_store is not None and options:
            try:
                await offered_choices_store.remember(user_id=user_id, rows=options)
            except Exception:  # noqa: BLE001
                _log.warning("offered_choices.remember_failed user=%s", user_id)

    async def _after_question_closed(closed, ctx, wa_id: str) -> None:  # type: ignore[no-untyped-def]
        """What follows a slot question closed with its safe default: any
        worker the promotion had already cleared is still written, and the one
        short line goes out first -- the new message is answered after it."""
        from runtime.inbound_journey import _create_promoted_workers

        try:
            await _create_promoted_workers(
                closed.result, workforce_query, ctx, wa_id, sender.send_text
            )
        except Exception:  # noqa: BLE001 -- never disturbs saved attendance
            _log.exception("worker_promotion.create_failed user=%s", ctx.user_id)
        # Not sent yet: it is folded into the reply to the new message, so
        # letting a question go never adds a message (request [53]).
        _held_users[wa_id] = ctx.user_id
        _held_notes[wa_id] = let_go_note(closed.result.collected_fields, closed.reply_text)

    def _agent_reads(message) -> bool:  # type: ignore[no-untyped-def]
        """Text, voice, photos and documents; a tap or text with no words is
        not a message for the model."""
        if message.modality in (InputModality.VOICE, InputModality.IMAGE, InputModality.DOCUMENT):
            return True
        return message.modality in (InputModality.TEXT, InputModality.INTERACTIVE) and bool(
            (message.text or "").strip()
        )

    async def _run_journey_steps(message, raw_payload, retry_of_id, timer) -> None:  # type: ignore[no-untyped-def]
        wa_id = message.sender.wa_id

        async def _run_agent(message, ctx, category_hint, timer) -> None:  # type: ignore[no-untyped-def]
            """The agent's turn. The pipeline it drives is the one below, with
            the senders swapped for a capture so the model writes the one reply."""
            from runtime.agent import save_button
            from runtime.agent.change_entry import ChangeEntry
            from runtime.agent.journey_gateway import JourneyGateway
            from runtime.agent.labour_entry import LabourEntry
            from runtime.agent.material_entry import MaterialEntry
            from runtime.agent.project_day import project_zone_name
            from runtime.agent.query_entry import QueryEntry
            from runtime.agent.site_entry import SiteEntry
            from runtime.agent.turn import AgentTurnDeps, run_agent_turn
            from runtime.inbound_journey import render_workflow_run_reply_spec
            from runtime.today_context import build_stock_line, build_today_line

            hint = category_hint.semantic_hint if category_hint else None
            if hint and category_hint.direction:
                # The Arrived/Used tap of the material menu (MATERIAL_DIRECTION_BUTTONS).
                hint = f"{hint} ({category_hint.direction})"

            async def _create_member(name, event, phone):  # type: ignore[no-untyped-def]
                from runtime.member_create_plan import start_member_create_plan

                return await start_member_create_plan(
                    name_hint=name,
                    original_event=event,
                    actor=ctx,
                    plan_store=plan_store,
                    workflow_runtime=workflow_runtime,
                    recent_turns=recent_turns_store,
                    whatsapp_number=phone,
                )

            async def _undo() -> str | None:
                return await interaction_handler.undo_latest_draft(
                    organization_id=str(ctx.organization_id), user_id=ctx.user_id
                )

            async def _undo_facts(facts):  # type: ignore[no-untyped-def]
                """Request 88: withdraw exactly these entries (a card's own)."""
                return await interaction_handler.undo_facts(
                    organization_id=str(ctx.organization_id), user_id=ctx.user_id, facts=facts
                )

            async def _save_now():  # type: ignore[no-untyped-def]
                saved = await interaction_handler.save_now(ctx.user_id, actor=ctx)
                if saved is not None and saved.saved_draft:
                    _saved_messages.add(message.correlation_id)
                    await _acknowledge(message, message.sender.wa_id)
                return saved

            async def _receipt_for(handled_list):  # type: ignore[no-untyped-def]
                """One card per reply: a single saved record gets its own
                card, a multi-part note gets one combined card with a row per
                record (the reply text lists them all too). A record whose own
                card was already started early still counts as one. A question
                passed to the engineer is no record to show (WA-37)."""
                for h in handled_list:
                    if save_button.is_engineer_question(h) and getattr(h, "receipt_coro", None) is not None:
                        h.receipt_coro.close()  # never started: nothing to wait for
                        h.receipt_coro = None
                handled_list = [h for h in handled_list if not save_button.is_engineer_question(h)]
                rendering = [
                    h
                    for h in handled_list
                    if getattr(h, "receipt_coro", None) is not None or id(h) in early["single"]
                ]
                if len(rendering) > 1:
                    for handled in rendering:  # the combined card replaces them
                        if handled.receipt_coro is not None:
                            handled.receipt_coro.close()
                            handled.receipt_coro = None
                    return await _combined_receipt_image(handled_list)
                if rendering and rendering[0].receipt_coro is not None:
                    early["single"].add(id(rendering[0]))
                    return await _receipt_image(rendering[0])
                return None

            # B-7: the card is made (and uploaded) while the model writes the
            # reply, not after it: started shortly after the last tool call,
            # started again if a later call saved more. A stale card is
            # discarded, never cancelled (a cancelled render would keep its
            # browser page).
            early: dict[str, Any] = {
                "gateway": None, "n": 0, "task": None, "timer": None, "single": set(),
            }

            async def _card_ready(handled_list):  # type: ignore[no-untyped-def]
                image = await _receipt_for(handled_list)
                prepare = getattr(sender, "prepare_image", None)
                if image and prepare is not None:
                    await prepare(image)
                return image

            def _start_card() -> None:
                gateway = early["gateway"]
                count = len(getattr(gateway, "handled", []) or [])
                if not count or count == early["n"]:
                    return
                early["n"] = count
                early["task"] = asyncio.ensure_future(_card_ready(list(gateway.handled)))

            def _after_tool() -> None:
                if early["timer"] is not None:
                    early["timer"].cancel()
                early["timer"] = asyncio.get_running_loop().call_later(0.05, _start_card)

            async def _attach_receipt(reply, gateway):  # type: ignore[no-untyped-def]
                if early["timer"] is not None:
                    early["timer"].cancel()
                # Request 91: an all-materials stock answer is the Stock card with
                # the reply as its caption. Only for a plain answer: nothing saved,
                # no buttons or list, so no receipt or Save card competes for it.
                stock_card = getattr(getattr(gateway, "query_entry", None), "stock_card", None)
                if (
                    stock_card
                    and not getattr(gateway, "handled", None)
                    and not reply.header_image
                    and not reply.buttons
                    and not reply.list_rows
                ):
                    return dataclasses.replace(reply, header_image=stock_card, caption_image=True)
                if getattr(gateway, "carry_before", None) or getattr(gateway, "carry_after", None):
                    # Request 88: a changed card shows all its items in the text;
                    # a picture of the one new entry would show only part of it.
                    return reply
                early["gateway"] = gateway
                _start_card()  # no-op when the card for these saves is under way
                task = early["task"]
                image = await task if task is not None else None
                return dataclasses.replace(reply, header_image=image) if image else reply

            async def _remember_card(gateway, *, open_card: bool) -> None:  # type: ignore[no-untyped-def]
                """Request 88: keep the card this reply shows, so "undo that" and
                "alla, 8 mason aanu" act on it. A reply without Save buttons
                (the old Undo button) leaves a marker that replaces any older
                card, so an id from it can never be used."""
                if cards is None:
                    return
                from runtime.agent.cards import LEGACY, OPEN, new_card

                items = [*gateway.carry_before, *gateway.card_items, *gateway.carry_after]
                try:
                    if open_card and items:
                        await cards.put(ctx, new_card(OPEN, items))
                    else:
                        await cards.put(ctx, new_card(LEGACY, []))
                except Exception:  # noqa: BLE001 -- the card only enables undo and edit
                    _log.warning("agent.card_remember_failed user=%s", ctx.user_id, exc_info=True)

            async def _send_agent_reply(reply, target_wa_id, gateway) -> None:  # type: ignore[no-untyped-def]
                """The agent's one reply, with the offers for what it saved
                folded in (buttons for the photo / undo) instead of sent as
                further messages."""
                handled_list = list(getattr(gateway, "handled", []))
                receipt_image = reply.header_image
                entries = save_button.entries_of(handled_list)
                if entries and (reply.buttons or reply.list_rows):
                    # Request 90: a question's buttons must not push the Save card
                    # out: the entries would stay drafts nobody was shown. The
                    # question stays in the words, to be answered by typing.
                    reply = save_button.question_as_text(reply)
                if not handled_list or reply.buttons or reply.list_rows:
                    await _send_composed(
                        target_wa_id, ctx.user_id, reply, header_image=receipt_image
                    )
                    return
                offers: list[Offer] = []
                for handled in handled_list:
                    try:
                        gathered = await _gather_offers(handled)
                    except Exception:  # noqa: BLE001 -- the offers are optional
                        _log.exception("offers.gather_failed user=%s", ctx.user_id)
                        continue
                    _gathered[id(handled)] = gathered
                    offers.extend(gathered.offers)
                # WA-37: a question passed to the engineer is no entry to undo.
                saved = any(h.saved_draft and not save_button.is_engineer_question(h) for h in handled_list)
                composed = compose(reply.text, offers, saved=saved)
                # WA-35: drafts wait on the sender's Save tap, not on Undo.
                plan, facts = save_button.card_plan(
                    handled_list,
                    before=[i.fact for i in getattr(gateway, "carry_before", ())],
                    after=[i.fact for i in getattr(gateway, "carry_after", ())],
                )
                if plan == "card":
                    composed = save_button.with_save_buttons(composed, facts)
                    await _remember_card(gateway, open_card=True)
                elif plan == "blocked":
                    # Request 90: records were written but no card can show them:
                    # block the reply, take them back, log it. No silent writes.
                    _log.error("agent.write_without_card user=%s entries=%s", ctx.user_id, len(facts))
                    await _undo_facts(facts)
                    await _remember_card(gateway, open_card=False)
                    composed = ReplySpec(text=save_button.NOT_SHOWN)
                    receipt_image = None
                elif saved:
                    if plan == "legacy":
                        _log.error("agent.write_without_card user=%s reviewable=false", ctx.user_id)
                    await _remember_card(gateway, open_card=False)
                await _send_composed(
                    target_wa_id,
                    ctx.user_id,
                    composed,
                    header_image=receipt_image,
                )

            from runtime.agent.work_site import site_label

            async def _set_today_site(project_id, site_id):  # type: ignore[no-untyped-def]
                await work_site.set_today(ctx, project_id=project_id, site_id=site_id)
                return site_label(ctx, site_id) or "that site"

            async def _work_site_line(actor):  # type: ignore[no-untyped-def]
                today = await work_site.today(actor)
                return site_label(actor, today[1]) if today else None

            async def _open_work_line(actor):  # type: ignore[no-untyped-def]
                """The open activities at today's site (or their only site)."""
                from runtime.today_context import render_open_work_line

                today = await work_site.today(actor) if work_site is not None else None
                sites = list(getattr(actor, "sites", None) or [])
                site_id = today[1] if today else (str(sites[0].id) if len(sites) == 1 else None)
                if site_id is None:
                    return None
                rows = await asyncio.wait_for(
                    activity_query.find_open_activities(
                        organization_id=str(actor.organization_id),
                        site_id=str(site_id),
                        reported_by_user_id=str(actor.user_id),
                        limit=6,
                    ),
                    timeout=0.5,
                )
                return render_open_work_line(site_label(actor, site_id), rows)

            async def _card_line(actor):  # type: ignore[no-untyped-def]
                """Request 88: the sender's latest card, with the ids the model
                may name in undo_last / update_pending_card."""
                from runtime.agent.cards import context_line

                return context_line(await cards.get(actor))

            def _gateway(msg, language):  # type: ignore[no-untyped-def]
                early["gateway"] = JourneyGateway(
                    message=msg,
                    save_now=_save_now,
                    undo=_undo,
                    followups=lambda handled: _deliver_followups(handled, audit=False),
                    held_prompt=lambda journey: render_workflow_run_reply_spec(journey.workflow_run),
                    language=language,
                    cards=cards,
                    actor=ctx,
                    undo_facts=_undo_facts,
                    set_today_site=_set_today_site if work_site is not None else None,
                    set_conversion=(
                        (
                            lambda material, unit, count: catalog_query.set_conversion(
                                organization_id=str(ctx.organization_id),
                                role=ctx.role,
                                user_id=ctx.user_id,
                                material_name=material,
                                unit_text=unit,
                                count=count,
                            )
                        )
                        if catalog_query is not None
                        else None
                    ),
                    # ARCH-01: known materials go straight to their workflow.
                    material_entry=(
                        MaterialEntry(
                            context_resolver=context_resolver,
                            catalog_query=catalog_query,
                            inventory_query=inventory_query,
                            org_settings_query=org_settings_query,
                            actor=ctx,
                            active_context=getattr(context_resolver, "active_context", None),
                        )
                        if catalog_query is not None
                        else None
                    ),
                    # ARCH-06 step 2: lookups, transfers, site/project create, money undo.
                    query_entry=QueryEntry(
                        context_resolver=context_resolver,
                        org_settings_query=org_settings_query,
                        actor=ctx,
                        active_context=getattr(context_resolver, "active_context", None),
                        inventory_query=inventory_query,
                        labour_query_service=labour_query_service,
                        activity_search_service=activity_search_service,
                        dpr_request_query=dpr_request_query,
                        project_detail_query=project_detail_query,
                        expense_query_service=expense_query_service,
                        money_account_query=money_account_query,
                        reversal_query=reversal_query,
                        object_storage=object_storage,
                        send_document=sender.send_document,
                        card_renderer=card_renderer,
                    ),
                    # ARCH-03: labour attendance (Alan's approval, 22 Oct).
                    labour_entry=LabourEntry(
                        context_resolver=context_resolver,
                        org_settings_query=org_settings_query,
                        actor=ctx,
                        active_context=getattr(context_resolver, "active_context", None),
                        workforce_query=workforce_query,
                    ),
                    # ARCH-02: work done, site issues and expenses too.
                    site_entry=SiteEntry(
                        context_resolver=context_resolver,
                        org_settings_query=org_settings_query,
                        actor=ctx,
                        active_context=getattr(context_resolver, "active_context", None),
                        activity_query=activity_query,
                        money_account_query=money_account_query,
                        duplicate_expense_query=duplicate_expense_query,
                        vendor_query=vendor_query,
                        remembered_activity=(
                            (lambda: memory_loader.current_activity_id(user_id=ctx.user_id))
                            if hasattr(memory_loader, "current_activity_id")
                            else None
                        ),
                    ),
                    change_entry=ChangeEntry(
                        context_resolver=context_resolver,
                        org_settings_query=org_settings_query,
                        actor=ctx,
                        active_context=getattr(context_resolver, "active_context", None),
                        member_resolver=member_resolver,
                        activity_query=activity_query,
                        site_issue_query=site_issue_query,
                        remembered_activity=(
                            (lambda: memory_loader.current_activity_id(user_id=ctx.user_id))
                            if hasattr(memory_loader, "current_activity_id")
                            else None
                        ),
                        create_member=_create_member,
                    ),
                    start_workflow=workflow_runtime.start,
                )
                return early["gateway"]

            deps = AgentTurnDeps(
                runner=_agent_runner,
                make_gateway=_gateway,
                send_spec=_send_spec,
                send_agent_reply=_send_agent_reply,
                attach_receipt=_attach_receipt,
                transcribe=pipeline.transcribe_voice,
                describe=pipeline.describe_media,
                message_logger=message_logger,
                memory_loader=memory_loader,
                memory_coordinator=memory_coordinator,
                user_language_store=user_language_store,
                reply_composer=reply_composer,
                lap=timer.lap,
                after_tool=_after_tool,
                today_line=lambda actor: build_today_line(
                    activity_search_service, actor, timezone_name=project_zone_name(getattr(actor, "timezone", None))
                ),
                stock_line=lambda actor: build_stock_line(inventory_query, actor),
                work_site_line=_work_site_line if work_site is not None else None,
                open_work_line=_open_work_line if activity_query is not None else None,
                card_line=_card_line if cards is not None else None,
                on_conversational=lambda: _conversational.add(message.correlation_id),
                trace_logger=trace_logger,
                later=later,
            )
            timer.lap("agent_setup")
            result = await run_agent_turn(message, ctx, deps, menu_hint=hint)
            timer.lap("agent_turn")
            if result is not None and result.toolbox.parked is not None:
                _agent_parked.add(message.correlation_id)


        # M4: resolve the sender before spending on understanding.
        try:
            ctx = await resolve_sender(actor_reader, wa_id)
        except Exception:  # noqa: BLE001 — never let a lookup error drop the message silently
            _log.exception("context.identity_lookup_failed wa_id=%s", wa_id)
            ctx = None

        timer.lap("resolve_sender")
        org_id = ctx.organization_id if ctx else None
        if ctx is not None:
            _resolved_actors[message.correlation_id] = ctx
            # BE-03: the rest of this message works for the sender's company.
            bind_tenant(org_id)
            forward_batch.mark_known_sender()  # WA-02: only users' forwards batch

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
        # A later ARQ attempt (runtime/ai_outage.py) is a new run of the same
        # message: its own log row, like an admin retry.
        later_attempt = (retry_attempt.get() or 1) > 1
        dedup_key = (
            message.message_id
            if retry_of_id is None and not later_attempt
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

        # SA-11: a super admin answering an error alert ("alert details",
        # "mute alerts 2h"), whoever else this number is in Mesiri.
        if ops_alerts is not None and message.text:
            try:
                alert_reply = await ops_alerts.handle_reply(wa_id, message.text)
            except Exception:  # noqa: BLE001 -- carry on with the message as usual
                _log.warning("ops_alert.reply_failed wa_id=%s", wa_id, exc_info=True)
                alert_reply = None
            if alert_reply is not None:
                await sender.send_text(wa_id, alert_reply)
                await message_logger.log_reply(correlation_id=message.correlation_id, reply=alert_reply)
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return

        if ctx is None:
            _log.info("context.sender_unregistered wa_id=%s", wa_id)
            # SS-05: "JOIN ACME-4821" asks a company's admins to let them in.
            # Before signup: works whether or not self-serve signup is on.
            try:
                reply = await join_journey.handle_unregistered(message) if join_journey else None
            except Exception:  # noqa: BLE001 -- fall through to the usual reply
                _log.exception("team_join.unregistered_failed wa_id=%s", wa_id)
                reply = None
            if reply is not None:
                await message_logger.log_reply(correlation_id=message.correlation_id, reply=reply)
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return
            # WA-09: an outside DPR contact answering the opt-in invite.
            reply = await opt_in_journey.handle(message) if opt_in_journey else None
            if reply is not None:
                await sender.send_text(wa_id, reply)
                await message_logger.log_reply(correlation_id=message.correlation_id, reply=reply)
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return
            # SS-04: when self-serve signup is on, an unknown number can start
            # a free trial instead of hitting a dead end.
            reply = await signup_journey.handle(message) if signup_journey else None
            if reply is None:
                reply = UNREGISTERED_MESSAGE
                await sender.send_text(wa_id, reply)
            await message_logger.log_reply(correlation_id=message.correlation_id, reply=reply)
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
            # SS-08: an ended trial gets its own reply (and "continue");
            # a suspended company keeps the generic one.
            inactive_reply = None
            if trial_journey is not None:
                try:
                    inactive_reply = await trial_journey.handle_inactive(message, ctx)
                except Exception:  # noqa: BLE001 — fall back to the generic reply
                    _log.exception("trial.inactive_reply_failed org=%s", ctx.organization_id)
            if inactive_reply is None:
                inactive_reply = ReplySpec(text=ORG_SUSPENDED_MESSAGE)
            await send_reply_spec(
                inactive_reply,
                wa_id,
                send_text=sender.send_text,
                send_list=sender.send_list,
                send_button=sender.send_button,
            )
            await message_logger.log_reply(
                correlation_id=message.correlation_id, reply=inactive_reply.text
            )
            await message_logger.mark_completed(correlation_id=message.correlation_id)
            return

        # SS-09: a trial company over today's AI/WhatsApp cap is paused until
        # tomorrow (India time) instead of running more AI. The message is
        # still logged; queued sends (the evening report) still go out.
        if trial_usage_guard is not None:
            usage_verdict = await trial_usage_guard.check(ctx.organization_id)
            if usage_verdict.over_cap:
                from mesiri.domains.organizations.guardrails import TRIAL_LIMIT_MESSAGE

                # An owner answering CONTINUE (SS-08) is asking to pay -- the
                # way out of the cap -- so that still gets its own reply.
                limit_reply: ReplySpec | None = None
                if trial_journey is not None:
                    try:
                        limit_reply = await trial_journey.handle_continue(message, ctx)
                    except Exception:  # noqa: BLE001 — fall back to the limit reply
                        _log.exception("trial.continue_failed user=%s", ctx.user_id)
                if limit_reply is None:
                    limit_reply = ReplySpec(text=TRIAL_LIMIT_MESSAGE)
                await send_reply_spec(
                    limit_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=limit_reply.text
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

        # Request [45]: a typed "undo" / "photo" / "skip" / option title / number
        # answering the choices on the last reply is the same as tapping it.
        message = await _resolve_typed_choice(message, ctx)

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
        if (
            contact_share is not None
            and (message.metadata or {}).get("raw_type") == "contacts"
            and (message.metadata or {}).get("shared_contacts")
        ):
            # SS-13: a shared contact card adds that person to the team.
            try:
                reply = await contact_share.handle_contacts(message, ctx)
            except Exception:  # noqa: BLE001 — a shared contact always gets a reply
                _log.exception("contact_share.failed user=%s", ctx.user_id)
                reply = ReplySpec(text="Sorry, I couldn't read that contact. Please try again.")
            await send_reply_spec(
                reply,
                wa_id,
                send_text=sender.send_text,
                send_list=sender.send_list,
                send_button=sender.send_button,
            )
            await message_logger.log_reply(correlation_id=message.correlation_id, reply=reply.text)
            await message_logger.mark_completed(correlation_id=message.correlation_id)
            return

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
            if _held_notes:
                spec = _with_held_note(spec, target_wa_id)
            await send_reply_spec(
                spec,
                target_wa_id,
                send_text=sender.send_text,
                send_list=sender.send_list,
                send_button=sender.send_button,
                send_image=sender.send_image,
            )

        async def _receipt_image(handled) -> bytes | None:  # type: ignore[no-untyped-def]
            """The receipt PNG for a saved record, or None: rendered within
            RECEIPT_TIMEOUT_S so a cold page pool never delays the reply.
            Never raises and never leaves the render running in the
            background (so an image can never arrive twice)."""
            coro = getattr(handled, "receipt_coro", None)
            if coro is None:
                return None
            handled.receipt_coro = None  # consumed: awaited exactly once
            try:
                return await asyncio.wait_for(coro, timeout=RECEIPT_TIMEOUT_S)
            except TimeoutError:
                _log.error("receipt.render_failed reason=timeout user=%s", ctx.user_id)
            except Exception:  # noqa: BLE001 -- the reply goes out without it
                _log.exception("receipt.render_failed user=%s", ctx.user_id)
            return None

        async def _combined_receipt_image(handled_list) -> bytes | None:  # type: ignore[no-untyped-def]
            """The one card for a multi-part note; same bound and same
            never-raises contract as _receipt_image."""
            try:
                return await asyncio.wait_for(
                    interaction_handler.build_combined_receipt(handled_list, ctx),
                    timeout=RECEIPT_TIMEOUT_S,
                )
            except TimeoutError:
                _log.error("receipt.render_failed reason=timeout user=%s", ctx.user_id)
            except Exception:  # noqa: BLE001 -- the reply goes out without it
                _log.exception("receipt.render_failed user=%s", ctx.user_id)
            return None

        async def _park_team_photo_report(store, user_id: str, report_id: str) -> None:
            """Remember which report a team photo would belong to.

            Never raises: Redis is a hint here, and losing it costs the photo
            offer, not the attendance.
            """
            try:
                await store.set_hint(user_id=user_id, report_id=report_id)
            except Exception:  # noqa: BLE001
                _log.warning("team_photo.park_failed user=%s", user_id)

        async def _hold_team_photo_for_plan(store, user_id: str, report_id: str) -> None:
            """Keep the team-photo offer for after the multi-part note ends."""
            try:
                await store.hold(user_id=user_id, report_id=report_id)
            except Exception:  # noqa: BLE001
                _log.warning("team_photo.hold_failed user=%s", user_id)

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
                reply_text = "Send the photo now 📷"
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
        if trial_journey is not None:
            # SS-08: a trial owner answering the trial reminder with CONTINUE.
            try:
                continue_reply = await trial_journey.handle_continue(message, ctx)
            except Exception:  # noqa: BLE001 — fall through to the normal journey
                _log.exception("trial.continue_failed user=%s", ctx.user_id)
                continue_reply = None
            if continue_reply is not None:
                await _send_spec(continue_reply, wa_id)
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=continue_reply.text
                )
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return

        if join_journey is not None:
            # SS-05: an admin's Approve / Reject on a join request, or an
            # admin / PM asking for the join code to share.
            try:
                join_reply = await join_journey.handle_tap(message, ctx)
                if join_reply is None:
                    join_reply = await join_journey.handle_code_request(message, ctx)
            except Exception:  # noqa: BLE001 — a tap must always get some reply
                _log.exception("team_join.registered_failed user=%s", ctx.user_id)
                join_reply = ReplySpec(text="Sorry, that didn't work — please try again.")
            if join_reply is not None:
                await send_reply_spec(
                    join_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=join_reply.text
                )
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return

        if logo_from_whatsapp is not None:
            # WA-13: a photo captioned as a logo sets the company's or a
            # client's logo straight away (owner only).
            try:
                logo_reply = await logo_from_whatsapp.handle_media(message, ctx)
            except Exception:  # noqa: BLE001 — fall through to the normal journey
                _log.exception("logo_from_whatsapp.failed user=%s", ctx.user_id)
                logo_reply = None
            if logo_reply is not None:
                await _send_spec(logo_reply, wa_id)
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=logo_reply.text
                )
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return

        if onboarding_progress is not None and message.modality is InputModality.TEXT:
            # SS-17: the owner typed "setup" / "setup status".
            from runtime.onboarding_progress import is_status_request

            if is_status_request(message.text) and str(ctx.role or "").upper() == "ADMIN":
                try:
                    await onboarding_progress.send_status(
                        ctx,
                        wa_id=wa_id,
                        send_image=sender.send_image,
                        send_spec=lambda spec: _send_spec(spec, wa_id),
                        send_text=sender.send_text,
                    )
                    await message_logger.log_reply(
                        correlation_id=message.correlation_id, reply="[setup progress card]"
                    )
                    await message_logger.mark_completed(correlation_id=message.correlation_id)
                    return
                except Exception:  # noqa: BLE001 — fall through to the normal journey
                    _log.exception("onboarding_card.status_failed user=%s", ctx.user_id)

        if setup_questions is not None:
            # SS-14: an answer to a daily setup question -- a tap on its
            # buttons, or the letterhead/logo photo it asked for. Before the
            # photo picker and the other taps: it is the question just asked.
            try:
                setup_reply = await setup_questions.handle_tap(message, ctx)
                if setup_reply is None:
                    setup_reply = await setup_questions.handle_media(message, ctx)
            except Exception:  # noqa: BLE001 — fall through to the normal journey
                _log.exception("setup_question.answer_failed user=%s", ctx.user_id)
                setup_reply = None
            if setup_reply is not None:
                await _send_spec(setup_reply, wa_id)
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=setup_reply.text
                )
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return

        if site_day_review is not None:
            # WA-04: a tap on the evening message about a site's day.
            try:
                review_reply = await site_day_review.handle_tap(message, ctx)
            except Exception:  # noqa: BLE001 — a tap must always get some reply
                _log.exception("site_day_review.tap_failed user=%s", ctx.user_id)
                review_reply = ReplySpec(text="Sorry, that didn't work — please try again.")
            if review_reply is not None:
                await _send_spec(review_reply, wa_id)
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=review_reply.text
                )
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return

        # WA-45: the morning "Where are you working today?" tap sets today's
        # site, then the message that was waiting for it runs.
        if work_site is not None:
            try:
                picked = await work_site.handle_tap(message, ctx)
            except Exception:  # noqa: BLE001 — a tap must always get some reply
                _log.exception("work_site.tap_failed user=%s", ctx.user_id)
                picked = (ReplySpec(text="Sorry, that didn't work — please try again."), None)
            if picked is not None:
                confirm, parked = picked
                await _send_spec(confirm, wa_id)
                await message_logger.log_reply(correlation_id=message.correlation_id, reply=confirm.text)
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                if parked is not None:
                    await _run_journey_steps(parked, {}, None, timer)
                return

        # WA-35: Save / Cancel on the agent's reply keeps or drops its drafts.
        from runtime.agent import save_button

        try:
            save_reply = await save_button.handle_tap(message, ctx, interaction_handler, cards)
        except Exception:  # noqa: BLE001 — a tap must always get some reply
            _log.exception("save_button.tap_failed user=%s", ctx.user_id)
            save_reply = ReplySpec(text="Sorry, that didn't work — please try again.")
        if save_reply is not None:
            await _send_composed(wa_id, ctx.user_id, save_reply)
            await message_logger.log_reply(correlation_id=message.correlation_id, reply=save_reply.text)
            await message_logger.mark_completed(correlation_id=message.correlation_id)
            # WA-58: the tap is part of the conversation the model reads next.
            try:
                await memory_coordinator.record_turn(
                    user_id=ctx.user_id,
                    user_text=str(message.text or "").strip() or "(tap)",
                    assistant_reply=save_reply.text,
                    correlation_id=message.correlation_id,
                )
            except Exception:  # noqa: BLE001 -- memory is a hint
                _log.warning("save_button.record_turn_failed user=%s", ctx.user_id, exc_info=True)
            # WA-57: what their message also had and is not recorded yet is
            # taken up right after the Save, not left behind.
            try:
                follow_up = await _later_follow_up(message, ctx)
                if follow_up is not None:
                    await _run_agent(follow_up, ctx, None, timer)
            except Exception:  # noqa: BLE001 -- the Save went through; this is a nicety
                _log.exception("agent.later_follow_up_failed user=%s", ctx.user_id)
            return

        if contact_share is not None:
            try:
                contact_reply = await contact_share.handle_project_tap(message, ctx)
            except Exception:  # noqa: BLE001 — a tap must always get some reply
                _log.exception("contact_share.tap_failed user=%s", ctx.user_id)
                contact_reply = ReplySpec(text="Sorry, I couldn't start that — please try again.")
            if contact_reply is not None:
                await send_reply_spec(
                    contact_reply,
                    wa_id,
                    send_text=sender.send_text,
                    send_list=sender.send_list,
                    send_button=sender.send_button,
                )
                await message_logger.log_reply(
                    correlation_id=message.correlation_id, reply=contact_reply.text
                )
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return

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

        async def _deliver_handled(handled, *, fold_plan_reply: bool = False) -> None:  # type: ignore[no-untyped-def]
            """Everything that follows a saved/answered confirmation: the
            reply, the receipt image, the worker-promotion / team-photo /
            project-setup offers, the plan advance and the audit rows. Shared
            by a typed "YES" (the fast path) and by save-first (WA-01), so
            an item saved without asking gets exactly the same follow-ups."""
            # Phase 4: send confirmation text FIRST so the user sees it
            # immediately, then await the receipt PNG (Playwright render) and
            # send the image. This keeps the reply feeling instant even when
            # the page-pool is cold.
            from runtime.plan_executor import plan_defers_rejection
            from runtime.reply_language import localize_fixed_reply

            reply_text = handled.reply_text
            try:
                if await plan_defers_rejection(handled, plan_store=plan_store, actor=ctx):
                    # One question at a time: this part's question comes with
                    # the closing summary, not beside the next part's Yes/No.
                    reply_text = "Not saved yet. I'll ask about this one after the rest."
                if user_language_store is not None:
                    language, script = await user_language_store.get_profile(user_id=ctx.user_id)
                    reply_text = localize_fixed_reply(reply_text, language, script)
            except Exception:  # noqa: BLE001 -- wording never costs the reply
                _log.exception("deliver.reply_wording_failed user=%s", ctx.user_id)
            if handled.saved_draft:
                await _acknowledge(message, wa_id)
            if handled.execution_result is not None and _succeeded(handled):
                _saved_messages.add(message.correlation_id)
            # One message: what was saved, plus the single follow-up that fits
            # (a question the record needs, else the team photo / setup offer).
            try:
                gathered = await _gather_offers(handled)
            except Exception:  # noqa: BLE001 -- the offers are optional
                _log.exception("offers.gather_failed user=%s", ctx.user_id)
                gathered = _Gathered()
            _gathered[id(handled)] = gathered
            if fold_plan_reply:
                # Save-first: a read-only answer the same message also asked
                # for rides in this one reply instead of a second message.
                # Anything with buttons (a step needing Yes/No) still goes on
                # its own, from _deliver_followups.
                try:
                    early = await _advance_plan_for(handled)
                except Exception:  # noqa: BLE001 -- advanced later, as before
                    _log.exception("plan.advance_failed user=%s", ctx.user_id)
                else:
                    _advanced[id(handled)] = early
                    if early is not None and not (early.buttons or early.list_rows) and early.text:
                        reply_text = f"{reply_text}\n\n{early.text}".strip()
                        _advanced[id(handled)] = None
            # The receipt card is rendered first (bounded) and sent inside
            # this one reply -- as the header of its button message.
            receipt_image = await _receipt_image(handled)
            await _send_composed(
                wa_id,
                ctx.user_id,
                compose(reply_text, gathered.offers, saved=handled.saved_draft),
                header_image=receipt_image,
            )
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
            await _deliver_followups(handled)

        def _succeeded(handled) -> bool:  # type: ignore[no-untyped-def]
            from mesiri_contracts.application.results.execution_result import ExecutionStatus

            return handled.execution_result.status is ExecutionStatus.SUCCEEDED

        class _Gathered:
            """What a saved/answered confirmation wants to say beyond its own
            reply: the offers (composed into that reply) and whether a
            worker-promotion question is among them."""

            def __init__(self, offers=None, promotion_offered: bool = False) -> None:  # type: ignore[no-untyped-def]
                self.offers: list[Offer] = list(offers or [])
                self.promotion_offered = promotion_offered

        # id(handled) -> its gathered offers, for the follow-ups that run after
        # the reply is out (the agent sends its reply before `finish`).
        _gathered: dict[int, Any] = {}

        async def _gather_offers(handled):  # type: ignore[no-untyped-def]
            """Worker promotion, team-photo and project-setup offers, collected
            instead of sent: request [45] puts them in the one reply. The
            hints and once-a-day claims are still written here, exactly as
            before; only the sending moved."""
            from runtime.inbound_journey import (
                _maybe_trigger_worker_promotion,
                _offer_project_setup,
                _offer_team_photo,
                _recorded_attendance_report_id,
            )
            from runtime.plan_executor import plan_has_more_to_do

            offers: list[Offer] = []
            questions: list[str] = []

            async def _collect_text(_wa_id, text, *args, **kwargs) -> bool:  # type: ignore[no-untyped-def]
                questions.append(text)
                return True

            async def _collect_spec(spec, _wa_id) -> None:  # type: ignore[no-untyped-def]
                from channel.replies import TEAM_PHOTO_BUTTONS

                kind = TEAM_PHOTO if spec.buttons == TEAM_PHOTO_BUTTONS else SETUP_OFFER
                offers.append(Offer(kind, spec=spec))

            async def _collect_question(spec, _wa_id) -> None:  # type: ignore[no-untyped-def]
                # A question the record needs, with its buttons (worker
                # promotion): one reply with the answer a tap away.
                offers.append(Offer(QUESTION, spec=spec))

            # Worker promotion follow-up. This belongs *here*, not in
            # inbound_journey: a confirmation reply is resolved by the fast
            # path above and returns before the journey ever runs, so a hook
            # placed there never fires for the one event it exists to follow.
            try:
                promotion_offered = await _maybe_trigger_worker_promotion(
                    handled,
                    workflow_runtime,
                    workforce_query,
                    ctx,
                    wa_id,
                    _collect_text,
                    send_spec_fn=_collect_question,
                )
            except Exception:  # noqa: BLE001 — promotion never disturbs saved attendance
                _log.exception("worker_promotion.trigger_failed user=%s", ctx.user_id)
                promotion_offered = False
            if questions:
                offers.append(Offer(QUESTION, text="\n\n".join(questions)))
            # Team photo. The report id is parked here, on confirmation,
            # whatever happens next -- the deferred branch pops it after the
            # promotion answer, and has no other way to learn which day the
            # photo belongs to.
            report_id = _recorded_attendance_report_id(handled)
            if report_id:
                await _park_team_photo_report(
                    team_photo_hint_store, ctx.user_id, report_id
                )
            # Offered now only when nothing is being promoted and no multi-part
            # note is still running; otherwise it waits (for that answer, or
            # for the note's last part).
            photo_held_for_plan = False
            if report_id:
                try:
                    photo_held_for_plan = await plan_has_more_to_do(
                        plan_store,
                        user_id=ctx.user_id,
                        finishing_instance_id=getattr(handled.result, "workflow_instance_id", None),
                    )
                except Exception:  # noqa: BLE001 -- the offer is optional
                    _log.exception("team_photo.plan_check_failed user=%s", ctx.user_id)
            if photo_held_for_plan:
                await _hold_team_photo_for_plan(team_photo_hint_store, ctx.user_id, report_id)
            elif report_id and not promotion_offered:
                await _offer_team_photo(
                    report_id, ctx, wa_id, team_photo_hint_store, _collect_spec
                )
            # Chained project/site setup offer: only fires for CREATE_PROJECT/
            # CREATE_SITE, mutually exclusive with the attendance offers.
            try:
                await _offer_project_setup(
                    handled, project_setup_offer_store, ctx, wa_id, _collect_spec
                )
            except Exception:  # noqa: BLE001 — offer never disturbs the saved project/site
                _log.exception("project_setup.offer_failed user=%s", ctx.user_id)
            if work_site is not None:
                # WA-45: a site they just created is where they work today.
                from runtime.agent.work_site import created_site

                new_site = created_site(handled)
                if new_site is not None:
                    await work_site.set_today(ctx, project_id=new_site[0], site_id=new_site[1])
            return _Gathered(offers, promotion_offered)

        # id(handled) -> the plan advance already run while composing its
        # reply (None when it was folded into that reply).
        _advanced: dict[int, Any] = {}

        async def _advance_plan_for(handled):  # type: ignore[no-untyped-def]
            from runtime.plan_executor import advance_plan

            return await advance_plan(
                handled,
                plan_store=plan_store,
                workflow_runtime=workflow_runtime,
                actor=ctx,
            )

        async def _deliver_followups(handled, *, audit: bool = True) -> None:  # type: ignore[no-untyped-def]
            """What follows a saved/answered confirmation once its reply is
            out: the plan advance, the held team-photo question, the invite,
            and (``audit``) the audit rows. The offers themselves went out
            inside the reply (`_gather_offers`)."""
            from runtime.inbound_journey import _offer_team_photo
            from runtime.plan_executor import plan_has_more_to_do

            gathered = _gathered.pop(id(handled), None)
            if gathered is None:
                # Not composed into a reply (nothing sent it yet): send what
                # was gathered as its own messages, as before request [45].
                gathered = await _gather_offers(handled)
                for offer in gathered.offers:
                    spec = offer.spec or ReplySpec(text=offer.text or "")
                    await _send_spec(spec, wa_id)
            promotion_offered = gathered.promotion_offered
            # Plan advance (docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md
            # §4.2/§7.1): after ANY confirmed/rejected workflow, check
            # whether it was a step in a Plan waiting on this exact
            # instance -- the entity-resolution layer's CREATE_USER ->
            # ADD_PROJECT_MEMBER chain (ENTITY_RESOLUTION_PLAN.md §3.3) and a
            # decomposed multi-intent plan (§9) both run through this same
            # call, generically, rather than one hand-written advance per
            # chain. A cheap no-op (one Redis read) for the overwhelmingly
            # common confirmation with no plan waiting on it at all.
            pending_plan_reply = None
            try:
                if id(handled) in _advanced:
                    plan_reply = _advanced.pop(id(handled))
                else:
                    plan_reply = await _advance_plan_for(handled)
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
                    # Sent below, once the held team-photo question is known:
                    # the closing summary carries it as buttons (request [45]).
                    pending_plan_reply = plan_reply
            except Exception:  # noqa: BLE001 — the confirmed/rejected step's own
                # outcome was already recorded either way.
                _log.exception("plan.advance_failed user=%s", ctx.user_id)
            # The note is finished (or was never a note): now the optional
            # team-photo question that was held back while it ran.
            held_offers: list[Offer] = []

            async def _hold_collect(spec, _wa_id) -> None:  # type: ignore[no-untyped-def]
                held_offers.append(Offer(TEAM_PHOTO, spec=spec))

            try:
                if not promotion_offered and not await plan_has_more_to_do(
                    plan_store, user_id=ctx.user_id
                ):
                    held_report = await team_photo_hint_store.pop_held(user_id=ctx.user_id)
                    if held_report:
                        await _offer_team_photo(
                            held_report, ctx, wa_id, team_photo_hint_store, _hold_collect
                        )
            except Exception:  # noqa: BLE001 -- the offer is optional
                _log.exception("team_photo.held_offer_failed user=%s", ctx.user_id)
            try:
                if pending_plan_reply is not None:
                    spec = pending_plan_reply
                    if held_offers and not (spec.buttons or spec.list_rows):
                        spec = compose(spec.text, held_offers, saved=True)
                        held_offers = []
                    await _send_composed(wa_id, ctx.user_id, spec)
                for offer in held_offers:
                    await _send_spec(offer.spec, wa_id)
            except Exception:  # noqa: BLE001
                _log.exception("plan.reply_failed user=%s", ctx.user_id)
            # SS-13: the person whose contact was shared is now on the
            # project; hand the owner an invite to forward them. After the
            # plan summary, so the message to forward is the last one.
            if contact_share is not None:
                try:
                    from mesiri_contracts.application.results.execution_result import (
                        ExecutionStatus,
                    )

                    confirmed = getattr(handled.result, "confirmed_action", None)
                    execution = handled.execution_result
                    if (
                        confirmed is not None
                        and execution is not None
                        and execution.status is ExecutionStatus.SUCCEEDED
                    ):
                        for text in await contact_share.invite_after_member_added(
                            action_type=confirmed.draft_action.action_type,
                            member_name=confirmed.draft_action.fields.get("member_name"),
                            actor=ctx,
                        ):
                            await sender.send_text(wa_id, text)
                except Exception:  # noqa: BLE001 — the member is already added
                    _log.exception("contact_share.invite_failed user=%s", ctx.user_id)
            # Was missing until now: every other fast-path step laps the
            # timer, but this one (and its three siblings above) didn't --
            # so the "prepipeline" trace a user pastes back for debugging
            # could never show whether this hook ran at all, only that
            # *something* between handle_fast_path and the final gather()
            # took some amount of time. Diagnosing a live "chain stopped at
            # user created" report needed this and didn't have it.
            timer.lap("plan_advance")
            if not audit:
                return
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
            await _deliver_handled(saved, fold_plan_reply=True)
            return True

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
        if slot_handled is not None and slot_handled.closed_question:
            # The open question was not answered (a site note, a greeting, a
            # second miss): it is closed with its safe default and THIS
            # message carries on as the new message it is (request [51]).
            await _after_question_closed(slot_handled, ctx, wa_id)
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
            # Sent like every composed reply: in the sender's language, with
            # its choices remembered so a typed "2" works like the tap.
            await _send_composed(wa_id, ctx.user_id, reply)
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
            # ARCH-06: the agent reads the photo, told what they tapped it is.
            from interactions.category_hint import CategoryHint

            await _run_agent(
                held_message, ctx, CategoryHint(IMAGE_PURPOSE_SEMANTIC_HINT[image_purpose_row_id]), timer
            )
            if len(held_batch) > 1:
                overflow_reply = render_batch_overflow_reply(
                    held_count=len(held_batch), remaining_count=len(held_batch) - 1
                )
                await sender.send_text(wa_id, overflow_reply)
                await message_logger.log_reply(correlation_id=message.correlation_id, reply=overflow_reply)
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
            known_language, known_script = await user_language_store.get_profile(user_id=ctx.user_id)
            if known_language is not None:
                greeting_text = await reply_composer.compose(
                    greeting_reply.text,
                    language=known_language,
                    correlation_id=message.correlation_id,
                    script=known_script,
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
        if message.modality is InputModality.IMAGE:
            # A later photo of a burst: held with the first, read when they
            # answer the picker -- never read on its own as well.
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
        # Request 90: for a sender whose replies carry Save cards, a bare "undo"
        # removes the entries of THEIR LATEST CARD (recorded by the code), never
        # "the latest draft of any type"; the older path below stays only for a
        # reply that had no card (the old Undo button) or where cards are off.
        if undo_hint is not None and cards is not None and agent_provider is not None:
            from runtime.agent.cards import LEGACY
            from runtime.agent.journey_gateway import undo_from_card

            latest = await cards.get(ctx)
            if latest is None or latest.state != LEGACY:

                async def _undo_card_facts(facts):  # type: ignore[no-untyped-def]
                    return await interaction_handler.undo_facts(
                        organization_id=str(ctx.organization_id), user_id=ctx.user_id, facts=facts
                    )

                step = await undo_from_card(cards, ctx, _undo_card_facts, [])
                if step.reply is not None:
                    await _send_composed(wa_id, ctx.user_id, step.reply)
                    reply_text = step.reply.text
                else:
                    await sender.send_text(wa_id, step.text)
                    reply_text = step.text
                await message_logger.log_reply(correlation_id=message.correlation_id, reply=reply_text)
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return
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
        # Request [40], ARCH-06: text, voice, photos and documents are read by
        # the tool-calling model, which runs the workflows directly. Everything
        # above (taps, YES/NO, UNDO, menu, signup, slot answers) had its turn.
        if agent_provider is not None and _agent_reads(message):
            # WA-45: the day's first message from someone with several sites
            # waits for "Where are you working today?".
            morning = None
            if work_site is not None and category_hint is None:
                try:
                    morning = await work_site.morning_question(message, ctx)
                except Exception:  # noqa: BLE001 — the question is a nicety
                    _log.exception("work_site.morning_failed user=%s", ctx.user_id)
            if morning is not None:
                await _send_spec(morning, wa_id)
                await message_logger.log_reply(correlation_id=message.correlation_id, reply=morning.text)
                await message_logger.mark_completed(correlation_id=message.correlation_id)
                return
            _fire_processing_ack(wa_id, message.modality)
            await _run_agent(message, ctx, category_hint, timer)
            return

        # Nothing the agent can read (an empty tap, an unknown kind of message).
        from runtime.agent.turn import UNREADABLE_REPLY

        await _send_spec(ReplySpec(text=UNREADABLE_REPLY), wa_id)
        await message_logger.log_reply(correlation_id=message.correlation_id, reply=UNREADABLE_REPLY)
        await message_logger.mark_completed(correlation_id=message.correlation_id)

    return _on_normalized, _mark_read_on_claim
