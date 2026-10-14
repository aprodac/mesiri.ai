"""Resume-leg handlers: the resume_pending_report_with_* functions that
continue a report/query held by one of the material/unit/project/site/stock
gates once the user answers the clarifying tap."""

from __future__ import annotations

from backend.ports import ActorIdentity
from channel.replies import (
    ALL_SITES_ROW_ID,
    AUDIENCE_CANDIDATE_NONE_ROW_ID,
    MATERIAL_CANDIDATE_NONE_ROW_ID,
    MEMBER_CANDIDATE_NONE_ROW_ID,
    PETTY_CASH_RECIPIENT_NONE_ROW_ID,
    ReplySpec,
    render_audience_not_found_reply,
    render_material_create_declined_reply,
    render_material_create_offer,
    render_material_create_unit_picker,
    render_material_created_reply,
    render_material_not_found_reply,
    render_member_create_declined_reply,
    render_member_create_offer,
    render_member_not_found_reply,
    render_petty_cash_recipient_not_found_reply,
)
from interactions.pending_report import PendingReportStore
from memory.recent_turns import RecentTurnsStore
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.canonical_event import IntentCompleteness as _IntentCompleteness
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage
from mesiri_contracts.assistant.planner_decision import PlannerDecisionType, WorkflowKey
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from mesiri_contracts.common.ids import new_id as _new_id
from planner import Planner
from planning.plan import Plan, PlanOrigin, PlanStep, StepRef, StepStatus
from planning.plan_store import PlanStore
from runtime.entity_resolution.member_resolution import MemberNameResolutionService
from runtime.inbound_journey._shared import _log
from runtime.inbound_journey.process import _plan_and_run
from runtime.inbound_journey.reply import (
    _complete_resume_leg,
    _safe,
    render_workflow_run_reply_spec,
)
from runtime.inbound_journey.seeding import (
    AUDIENCE_PENDING_NAME_FIELD,
    _actor_may_create_user,
    _may_create_material,
    _run_audience_name_gate,
    _run_material_unit_gates,
    _run_project_gate,
    _run_site_gate,
)
from runtime.inventory_query import MaterialInventoryQueryService
from runtime.logging_ports import MessageLogger
from runtime.material_catalog_query import MaterialCatalogQueryService
from runtime.org_settings_query import OrganizationSettingsQueryService
from runtime.petty_cash_query import PettyCashRecipientQueryService
from workflows import WorkflowRuntime
from workflows.create_user.nodes import find_mentioned_phone_number

_PROJECT_ROW_PREFIX = "proj_"


async def resume_pending_report_with_project(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_report_store: PendingReportStore,
    planner: Planner,
    workflow_runtime: WorkflowRuntime,
    actor: ActorIdentity | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    message_logger: MessageLogger | None = None,
) -> ReplySpec | None:
    """Resume a report that was held by the project-selection gate above, now
    that the user tapped which project it belongs to.

    ``actor_user_id`` is the resolved canonical user_id (the same key the
    gate stored the pending report under) -- not message.sender.wa_id, which
    is the raw phone number the identity gate has already resolved past by
    the time this runs.

    Re-runs the site gate before planner/workflow -- resolving project
    doesn't guarantee site does too (a project can still have more than one
    site to choose between). Returns None for anything that isn't a
    "proj_*" list-row tap, so the caller falls through to the normal journey
    exactly like the other fast-path checks (category tap, greeting,
    whoami).
    """
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = message.metadata.get("interactive_reply_id")
    if not row_id or not row_id.startswith(_PROJECT_ROW_PREFIX):
        return None

    event = await pending_report_store.pop_pending(user_id=actor_user_id)
    if event is None:
        if message_logger:
            await _safe(message_logger.mark_completed(correlation_id=message.correlation_id))
        return ReplySpec(text="That selection expired — please resend your report.")

    project_id = row_id.removeprefix(_PROJECT_ROW_PREFIX)

    # The picker only ever renders actor.projects (see _run_project_gate), but
    # the tapped row_id is untrusted client input -- WhatsApp interactive
    # replies echo back whatever id the button carried, and nothing stops a
    # replayed/crafted payload from naming a project the picker never offered.
    # Re-checking against the same authorized set the picker was built from
    # closes that gap instead of trusting the tap at face value.
    authorized_ids = {p.id for p in actor.projects} if actor is not None else set()
    if project_id not in authorized_ids:
        await _complete_resume_leg(message, event, message_logger)
        return ReplySpec(text="That project isn't available to you — please resend your report.")

    event = event.model_copy(update={"project_id": project_id})

    held_reply = await _run_site_gate(
        event,
        actor=actor,
        actor_user_id=actor_user_id,
        pending_report_store=pending_report_store,
        allow_combined=event.event_type is CanonicalEventType.INVENTORY_QUERY_ASKED,
    )
    if held_reply is not None:
        await _complete_resume_leg(message, event, message_logger)
        return held_reply

    reply = await _plan_and_run(
        event,
        planner=planner,
        workflow_runtime=workflow_runtime,
        inventory_query=inventory_query,
        pending_report_store=pending_report_store,
        actor_user_id=actor_user_id,
    )
    await _complete_resume_leg(message, event, message_logger)
    return reply


_AUDIENCE_ROW_PREFIX = "aud_"
_PETTY_CASH_RECIPIENT_ROW_PREFIX = "pcr_"
_MATERIAL_ROW_PREFIX = "mat_"
_UNIT_YES_ROW_PREFIX = "unit_yes_"
_UNIT_NO_ROW_ID = "unit_no"


async def resume_pending_report_with_material(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_report_store: PendingReportStore,
    catalog_query: MaterialCatalogQueryService,
    planner: Planner,
    workflow_runtime: WorkflowRuntime,
    actor: ActorIdentity | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    message_logger: MessageLogger | None = None,
    org_settings_query: OrganizationSettingsQueryService | None = None,
) -> ReplySpec | None:
    """Resume a report held by the material-resolution gate, now that the user
    tapped which catalog material it refers to -- or "None of these".

    Re-runs the remaining gate chain (unit, then project, then site) rather
    than jumping straight to planner -- material resolving doesn't guarantee
    unit/project/site do too (see _run_material_unit_gates: a resolved
    material_id with no unit_id yet still needs the Stock Unit check to
    run). Mirrors resume_pending_report_with_project's shape otherwise.

    "None of these" falls through to the same Missing handling the gate
    itself would have shown -- the create offer when the org's settings allow
    this sender to add a catalog entry, the plain not-found reply when they
    don't -- exactly as MEMBER_CANDIDATE_NONE_ROW_ID does for users. This is
    what keeps a one-row picker (a lone substring candidate, which no longer
    auto-resolves) an honest question rather than a trap.
    """
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = message.metadata.get("interactive_reply_id")
    if not row_id or not row_id.startswith(_MATERIAL_ROW_PREFIX):
        return None

    event = await pending_report_store.pop_pending(user_id=actor_user_id)
    if event is None:
        if message_logger:
            await _safe(message_logger.mark_completed(correlation_id=message.correlation_id))
        return ReplySpec(text="That selection expired — please resend your report.")

    if row_id == MATERIAL_CANDIDATE_NONE_ROW_ID:
        name = str(event.fields.get("material_name") or "")
        if await _may_create_material(
            event,
            actor_role=getattr(actor, "role", None),
            org_settings_query=org_settings_query,
        ):
            await pending_report_store.set_pending(user_id=actor_user_id, event=event)
            await _complete_resume_leg(message, event, message_logger)
            return render_material_create_offer(name)
        await _complete_resume_leg(message, event, message_logger)
        return ReplySpec(text=render_material_not_found_reply(name))

    material_id = row_id.removeprefix(_MATERIAL_ROW_PREFIX)
    event.fields["material_id"] = material_id

    held_reply = await _run_material_unit_gates(
        event,
        catalog_query=catalog_query,
        pending_report_store=pending_report_store,
        actor_user_id=actor_user_id,
    )
    if held_reply is not None:
        await _complete_resume_leg(message, event, message_logger)
        return held_reply

    held_reply = await _run_project_gate(
        event, actor=actor, actor_user_id=actor_user_id, pending_report_store=pending_report_store
    )
    if held_reply is not None:
        await _complete_resume_leg(message, event, message_logger)
        return held_reply

    held_reply = await _run_site_gate(
        event,
        actor=actor,
        actor_user_id=actor_user_id,
        pending_report_store=pending_report_store,
        allow_combined=event.event_type is CanonicalEventType.INVENTORY_QUERY_ASKED,
    )
    if held_reply is not None:
        await _complete_resume_leg(message, event, message_logger)
        return held_reply

    reply = await _plan_and_run(
        event,
        planner=planner,
        workflow_runtime=workflow_runtime,
        inventory_query=inventory_query,
        pending_report_store=pending_report_store,
        actor_user_id=actor_user_id,
    )
    await _complete_resume_leg(message, event, message_logger)
    return reply


async def resume_pending_report_with_unit(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_report_store: PendingReportStore,
    catalog_query: MaterialCatalogQueryService,
    planner: Planner,
    workflow_runtime: WorkflowRuntime,
    actor: ActorIdentity | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    message_logger: MessageLogger | None = None,
) -> ReplySpec | None:
    """Resume a report held by the unit-mismatch clarification, now that the
    user confirmed or declined the material's Stock Unit.

    "No" doesn't silently fall back to anything -- there's only one valid
    unit for this material in V1 (no unit conversion), so declining means the
    report can't be recorded as stated; the user is asked to resend it
    correctly rather than the assistant guessing.
    """
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = message.metadata.get("interactive_reply_id")
    if not row_id:
        return None
    if row_id == _UNIT_NO_ROW_ID:
        # Must still pop -- a stale pending report must never resurrect later.
        await pending_report_store.pop_pending(user_id=actor_user_id)
        if message_logger:
            await _safe(message_logger.mark_completed(correlation_id=message.correlation_id))
        return ReplySpec(text="No problem — please resend the report with the correct unit.")
    if not row_id.startswith(_UNIT_YES_ROW_PREFIX):
        return None

    event = await pending_report_store.pop_pending(user_id=actor_user_id)
    if event is None:
        if message_logger:
            await _safe(message_logger.mark_completed(correlation_id=message.correlation_id))
        return ReplySpec(text="That selection expired — please resend your report.")

    unit_id = row_id.removeprefix(_UNIT_YES_ROW_PREFIX)
    event.fields["unit_id"] = unit_id

    held_reply = await _run_project_gate(
        event, actor=actor, actor_user_id=actor_user_id, pending_report_store=pending_report_store
    )
    if held_reply is not None:
        await _complete_resume_leg(message, event, message_logger)
        return held_reply

    held_reply = await _run_site_gate(
        event,
        actor=actor,
        actor_user_id=actor_user_id,
        pending_report_store=pending_report_store,
        allow_combined=event.event_type is CanonicalEventType.INVENTORY_QUERY_ASKED,
    )
    if held_reply is not None:
        await _complete_resume_leg(message, event, message_logger)
        return held_reply

    reply = await _plan_and_run(
        event,
        planner=planner,
        workflow_runtime=workflow_runtime,
        inventory_query=inventory_query,
        pending_report_store=pending_report_store,
        actor_user_id=actor_user_id,
    )
    await _complete_resume_leg(message, event, message_logger)
    return reply


_SITE_ROW_PREFIX = "site_"


async def resume_pending_report_with_site(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_report_store: PendingReportStore,
    planner: Planner,
    workflow_runtime: WorkflowRuntime,
    actor: ActorIdentity | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    message_logger: MessageLogger | None = None,
) -> ReplySpec | None:
    """Resume a report/query held by the site-selection gate, now that the
    user tapped which site it belongs to (or "All Sites Combined", for an
    inventory query -- see render_site_picker's allow_combined).

    Site is the last gate in the chain (material/unit/project must already
    be settled to have reached the site gate at all -- see _run_site_gate's
    project_id-is-None short-circuit), so nothing else needs re-running here.
    Returns None for anything that isn't a "site_*" list-row tap, so the
    caller falls through to the normal journey exactly like the other
    fast-path checks.
    """
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = message.metadata.get("interactive_reply_id")
    if not row_id or not row_id.startswith(_SITE_ROW_PREFIX):
        return None

    event = await pending_report_store.pop_pending(user_id=actor_user_id)
    if event is None:
        if message_logger:
            await _safe(message_logger.mark_completed(correlation_id=message.correlation_id))
        return ReplySpec(text="That selection expired — please resend your report.")

    if row_id == ALL_SITES_ROW_ID:
        site_id = None
    else:
        site_id = row_id.removeprefix(_SITE_ROW_PREFIX)
        # Same untrusted-tap concern as the project resume leg above: the
        # picker only ever renders sites from actor.sites for this project
        # (_run_site_gate), so re-check the tap against that same set rather
        # than trusting whatever site_id the interactive reply carried.
        authorized_ids = {s.id for s in actor.sites} if actor is not None else set()
        if site_id not in authorized_ids:
            await _complete_resume_leg(message, event, message_logger)
            return ReplySpec(text="That site isn't available to you — please resend your report.")
    event = event.model_copy(update={"site_id": site_id})

    reply = await _plan_and_run(
        event,
        planner=planner,
        workflow_runtime=workflow_runtime,
        inventory_query=inventory_query,
        pending_report_store=pending_report_store,
        actor_user_id=actor_user_id,
    )
    await _complete_resume_leg(message, event, message_logger)
    return reply


_MATERIAL_CREATE_YES_ROW_ID = "matnew_yes"
_MATERIAL_CREATE_NO_ROW_ID = "matnew_no"
_MATERIAL_CREATE_UNIT_PREFIX = "matunit_"


async def _create_material_and_resume(
    event: CanonicalEventV2,
    *,
    unit_id: str,
    unit_display: str,
    message: NormalizedMessage,
    actor_user_id: str,
    catalog_query: MaterialCatalogQueryService,
    pending_report_store: PendingReportStore,
    planner: Planner,
    workflow_runtime: WorkflowRuntime,
    actor: ActorIdentity | None,
    inventory_query: MaterialInventoryQueryService | None,
    message_logger: MessageLogger | None,
) -> ReplySpec:
    """Create the catalog entry, then run the held report through the rest of
    the gate chain -- shared by both routes into creation (the Yes tap when
    the unit was already known, and the unit-picker tap when it wasn't).

    The created material_id/unit_id are written onto the event before the
    gates re-run, so _run_material_unit_gates takes its already-resolved
    path rather than looking the brand-new name up again.
    """
    name = str(event.fields.get("material_name") or "")
    try:
        created = await catalog_query.create_material(
            organization_id=event.organization_id,
            name=name,
            unit_id=unit_id,
            created_by=actor_user_id,
        )
    except Exception:
        _log.exception("material_create.failed correlation_id=%s", event.correlation_id)
        created = None

    if created is None:
        await _complete_resume_leg(message, event, message_logger)
        return ReplySpec(
            text="Sorry, I couldn't add that material — please try again, or ask your admin."
        )

    event.fields["material_id"] = str(created["id"])
    event.fields["unit_id"] = str(created["default_unit_id"] or unit_id)
    # The reported unit text may have been a synonym of the chosen unit (or
    # absent entirely). Replace it with the canonical display name so the
    # confirmation prompt shows what the material is actually tracked in.
    event.fields["unit"] = unit_display

    confirmation = render_material_created_reply(created["name"], unit_display)

    held_reply = await _run_project_gate(
        event, actor=actor, actor_user_id=actor_user_id, pending_report_store=pending_report_store
    )
    if held_reply is None:
        held_reply = await _run_site_gate(
            event,
            actor=actor,
            actor_user_id=actor_user_id,
            pending_report_store=pending_report_store,
            allow_combined=event.event_type is CanonicalEventType.INVENTORY_QUERY_ASKED,
        )

    if held_reply is not None:
        await _complete_resume_leg(message, event, message_logger)
        # Prepend the creation confirmation so the user sees the catalog
        # entry landed even though the report is now paused on a different
        # question (which project/site).
        return held_reply.with_prefix(confirmation)

    reply = await _plan_and_run(
        event,
        planner=planner,
        workflow_runtime=workflow_runtime,
        inventory_query=inventory_query,
        pending_report_store=pending_report_store,
        actor_user_id=actor_user_id,
    )
    await _complete_resume_leg(message, event, message_logger)
    if reply is None:
        return ReplySpec(text=confirmation)
    return reply.with_prefix(confirmation)


async def resume_pending_report_with_material_create(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_report_store: PendingReportStore,
    catalog_query: MaterialCatalogQueryService,
    planner: Planner,
    workflow_runtime: WorkflowRuntime,
    actor: ActorIdentity | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    message_logger: MessageLogger | None = None,
) -> ReplySpec | None:
    """Resume a report held by the material-create offer, now that the user
    said whether to add the unknown material to the catalog (STA-139).

    On Yes, the Stock Unit is taken from the report's own words when they
    resolved to a real unit ("50 bags of Fevicol" -> bags) so the common case
    costs no extra turn; otherwise a unit picker is sent and creation happens
    on that tap instead (resume_pending_report_with_material_unit_choice).

    On No the report is dropped with a nudge toward a spelling mistake --
    the likeliest reason a real material didn't match -- rather than
    silently closing.
    """
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = message.metadata.get("interactive_reply_id")
    if row_id not in (_MATERIAL_CREATE_YES_ROW_ID, _MATERIAL_CREATE_NO_ROW_ID):
        return None

    event = await pending_report_store.pop_pending(user_id=actor_user_id)
    if event is None:
        if message_logger:
            await _safe(message_logger.mark_completed(correlation_id=message.correlation_id))
        return ReplySpec(text="That selection expired — please resend your report.")

    name = str(event.fields.get("material_name") or "")

    if row_id == _MATERIAL_CREATE_NO_ROW_ID:
        await _complete_resume_leg(message, event, message_logger)
        return ReplySpec(text=render_material_create_declined_reply(name))

    # Yes -- try to settle the Stock Unit from what the report already said.
    unit_text = event.fields.get("unit")
    resolved_unit: dict | None = None
    if unit_text:
        try:
            resolved_unit = await catalog_query.resolve_unit(str(unit_text))
        except Exception:
            _log.exception("material_create.unit_lookup_failed correlation_id=%s", event.correlation_id)

    if resolved_unit is not None:
        return await _create_material_and_resume(
            event,
            unit_id=str(resolved_unit["id"]),
            unit_display=resolved_unit.get("display_name") or str(unit_text),
            message=message,
            actor_user_id=actor_user_id,
            catalog_query=catalog_query,
            pending_report_store=pending_report_store,
            planner=planner,
            workflow_runtime=workflow_runtime,
            actor=actor,
            inventory_query=inventory_query,
            message_logger=message_logger,
        )

    # No usable unit in the report -- ask, and create on that tap instead.
    try:
        units = await catalog_query.list_units()
    except Exception:
        _log.exception("material_create.unit_list_failed correlation_id=%s", event.correlation_id)
        units = []
    if not units:
        await _complete_resume_leg(message, event, message_logger)
        return ReplySpec(
            text="Sorry, I couldn't load the units list — please try again, or ask your admin."
        )

    await pending_report_store.set_pending(user_id=actor_user_id, event=event)
    await _complete_resume_leg(message, event, message_logger)
    return render_material_create_unit_picker(
        name, [(str(u["id"]), u["display_name"]) for u in units]
    )


async def resume_pending_report_with_material_unit_choice(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_report_store: PendingReportStore,
    catalog_query: MaterialCatalogQueryService,
    planner: Planner,
    workflow_runtime: WorkflowRuntime,
    actor: ActorIdentity | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    message_logger: MessageLogger | None = None,
) -> ReplySpec | None:
    """Resume a report held by the new-material unit picker, now that the
    user chose which unit the material is tracked in. Creates the catalog
    entry and continues the report (STA-139).

    Kept distinct from resume_pending_report_with_unit ("unit_yes_*", the
    Stock Unit *mismatch* clarification for an existing material) -- these
    two answer different questions and must not share a row-id prefix.
    """
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = message.metadata.get("interactive_reply_id")
    if not row_id or not row_id.startswith(_MATERIAL_CREATE_UNIT_PREFIX):
        return None

    event = await pending_report_store.pop_pending(user_id=actor_user_id)
    if event is None:
        if message_logger:
            await _safe(message_logger.mark_completed(correlation_id=message.correlation_id))
        return ReplySpec(text="That selection expired — please resend your report.")

    unit_id = row_id.removeprefix(_MATERIAL_CREATE_UNIT_PREFIX)
    try:
        unit = await catalog_query.get_unit(unit_id)
    except Exception:
        _log.exception("material_create.unit_lookup_failed correlation_id=%s", event.correlation_id)
        unit = None

    return await _create_material_and_resume(
        event,
        unit_id=unit_id,
        unit_display=(unit or {}).get("display_name") or "",
        message=message,
        actor_user_id=actor_user_id,
        catalog_query=catalog_query,
        pending_report_store=pending_report_store,
        planner=planner,
        workflow_runtime=workflow_runtime,
        actor=actor,
        inventory_query=inventory_query,
        message_logger=message_logger,
    )


_STOCK_CAP_ROW_ID = "stock_cap"
_STOCK_ARRIVAL_ROW_ID = "stock_arrival"
_STOCK_CANCEL_ROW_ID = "stock_cancel"


async def resume_pending_report_with_stock_choice(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_report_store: PendingReportStore,
    planner: Planner,
    workflow_runtime: WorkflowRuntime,
    inventory_query: MaterialInventoryQueryService | None = None,
    message_logger: MessageLogger | None = None,
) -> ReplySpec | None:
    """Resume a usage report held by the stock sufficiency gate
    (_run_stock_gate), now that the user picked how to resolve an over-stock
    report.

    "Cap at available" corrects quantity down to the stock figure the gate
    already computed, then re-runs the same planner/workflow path a normal
    usage report would -- the gate re-checks on the way back through
    _plan_and_run, but requested == available by construction so it never
    re-triggers. "It's an arrival" flips the report to a Material Receipt
    with the same material/quantity/unit -- covers the common mistake of the
    message actually being about stock arriving, not being used. "Cancel"
    discards it, mirroring the wording of a "No" on the normal confirmation
    prompt. Returns None for anything that isn't one of the three "stock_*"
    button taps, so the caller falls through to the normal journey exactly
    like the other fast-path checks.
    """
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = message.metadata.get("interactive_reply_id")
    if row_id not in (_STOCK_CAP_ROW_ID, _STOCK_ARRIVAL_ROW_ID, _STOCK_CANCEL_ROW_ID):
        return None

    event = await pending_report_store.pop_pending(user_id=actor_user_id)
    if event is None:
        if message_logger:
            await _safe(message_logger.mark_completed(correlation_id=message.correlation_id))
        return ReplySpec(text="That selection expired — please resend your report.")

    if row_id == _STOCK_CANCEL_ROW_ID:
        await _complete_resume_leg(message, event, message_logger)
        return ReplySpec(text="❌ Discarded. Nothing was recorded.")

    if row_id == _STOCK_CAP_ROW_ID:
        event.fields["quantity"] = event.fields.get("available_stock")
    else:  # _STOCK_ARRIVAL_ROW_ID
        event = event.model_copy(
            update={"event_type": CanonicalEventType.MATERIAL_RECEIPT_REQUESTED}
        )
        event.fields["direction"] = "received"
        event.fields.pop("available_stock", None)

    reply = await _plan_and_run(
        event,
        planner=planner,
        workflow_runtime=workflow_runtime,
        inventory_query=inventory_query,
        pending_report_store=pending_report_store,
        actor_user_id=actor_user_id,
    )
    await _complete_resume_leg(message, event, message_logger)
    return reply


# ---------------------------------------------------------------------------
# Member-name resolution resume paths (ENTITY_RESOLUTION_PLAN.md) -- the two
# taps _run_member_name_gate's Ambiguous/Missing outcomes can produce, plus
# the CREATE_USER-then-resume chain Missing's "Yes, create" answer starts.
# ---------------------------------------------------------------------------

_MEMBER_CREATE_YES_ROW_ID = "membernew_yes"
_MEMBER_CREATE_NO_ROW_ID = "membernew_no"

#: Plan step ids for the two-step CREATE_USER -> ADD_PROJECT_MEMBER chain.
#: Constant, not generated, because there is exactly one shape of plan this
#: module ever builds -- see start_member_create_plan below.
_CREATE_USER_STEP_ID = "create_user"
_ADD_MEMBER_STEP_ID = "add_member"


async def resume_pending_report_with_member_candidate(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_report_store: PendingReportStore,
    member_resolver: MemberNameResolutionService,
    planner: Planner,
    workflow_runtime: WorkflowRuntime,
    actor: ActorIdentity | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    message_logger: MessageLogger | None = None,
) -> ReplySpec | None:
    """Resume a report held by the member-name picker (_run_member_name_gate's
    Ambiguous case), now that the sender tapped either a specific candidate
    or "Someone else".

    A specific candidate: re-checks the id is still an active user (it may
    have been deactivated between the offer and the tap) and, if so, patches
    member_name to that user's *current* exact name -- the backend's own
    exact-match resolver (application/projects/name_resolution.py) then
    finds the same row again at execution, so nothing else needs to change
    (ADR-E2). "Someone else": falls through to the same Missing handling
    render_member_create_offer/render_member_not_found_reply would have
    shown, gated by the same role check.
    """
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = message.metadata.get("interactive_reply_id")
    if not row_id or not str(row_id).startswith("member_"):
        return None

    event = await pending_report_store.pop_pending(user_id=actor_user_id)
    if event is None:
        if message_logger:
            await _safe(message_logger.mark_completed(correlation_id=message.correlation_id))
        return ReplySpec(text="That selection expired — please resend your request.")

    if row_id == MEMBER_CANDIDATE_NONE_ROW_ID:
        name_hint = str(event.fields.get("member_name") or "")
        actor_role = getattr(actor, "role", None)
        if _actor_may_create_user(actor_role):
            await pending_report_store.set_pending(user_id=actor_user_id, event=event)
            await _complete_resume_leg(message, event, message_logger)
            return render_member_create_offer(name_hint)
        await _complete_resume_leg(message, event, message_logger)
        return ReplySpec(text=render_member_not_found_reply(name_hint))

    entity_id = str(row_id)[len("member_"):]
    try:
        display_name = await member_resolver.get_active_display_name(
            organization_id=event.organization_id, entity_id=entity_id
        )
    except Exception:
        _log.exception("member_candidate.lookup_failed correlation_id=%s", event.correlation_id)
        display_name = None

    if display_name is None:
        await _complete_resume_leg(message, event, message_logger)
        return ReplySpec(text="That selection expired — please resend your request.")

    event.fields["member_name"] = display_name
    reply = await _plan_and_run(
        event,
        planner=planner,
        workflow_runtime=workflow_runtime,
        inventory_query=inventory_query,
        pending_report_store=pending_report_store,
        actor_user_id=actor_user_id,
    )
    await _complete_resume_leg(message, event, message_logger)
    return reply


async def resume_pending_report_with_audience_candidate(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_report_store: PendingReportStore,
    member_resolver: MemberNameResolutionService,
    planner: Planner,
    workflow_runtime: WorkflowRuntime,
    actor: ActorIdentity | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    message_logger: MessageLogger | None = None,
) -> ReplySpec | None:
    """Resume an automation held by _run_audience_name_gate, now that the
    user tapped who one of its audience names meant -- or "None of these".

    Patches that single name and re-enters the gate, which either asks about
    the next unresolved name or lets the automation through to its
    confirmation. The loop lives in the gate rather than here, so a reminder
    naming three unknown people needs no special handling: it is simply this
    leg, three times.

    "None of these" stops rather than dropping that person and creating the
    automation for everyone else -- a reminder that silently omits someone
    fails exactly when it was supposed to help.
    """
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = message.metadata.get("interactive_reply_id")
    if not row_id or not str(row_id).startswith(_AUDIENCE_ROW_PREFIX):
        return None

    event = await pending_report_store.pop_pending(user_id=actor_user_id)
    if event is None:
        if message_logger:
            await _safe(message_logger.mark_completed(correlation_id=message.correlation_id))
        return ReplySpec(text="That selection expired — please resend your request.")

    pending_name = str(event.fields.get(AUDIENCE_PENDING_NAME_FIELD) or "")

    if row_id == AUDIENCE_CANDIDATE_NONE_ROW_ID:
        await _complete_resume_leg(message, event, message_logger)
        return ReplySpec(text=render_audience_not_found_reply(pending_name))

    entity_id = str(row_id)[len(_AUDIENCE_ROW_PREFIX):]
    try:
        display_name = await member_resolver.get_active_display_name(
            organization_id=event.organization_id, entity_id=entity_id
        )
    except Exception:
        _log.exception("audience_candidate.lookup_failed correlation_id=%s", event.correlation_id)
        display_name = None

    if display_name is None:
        await _complete_resume_leg(message, event, message_logger)
        return ReplySpec(text="That selection expired — please resend your request.")

    names = event.fields.get("audience_names")
    if isinstance(names, list):
        event.fields["audience_names"] = [
            display_name if str(n) == pending_name else str(n) for n in names
        ]
    event.fields.pop(AUDIENCE_PENDING_NAME_FIELD, None)

    # Back through the gate -- the next unknown name, if any, asks itself.
    held_reply = await _run_audience_name_gate(
        event,
        member_resolver=member_resolver,
        pending_report_store=pending_report_store,
        actor_user_id=actor_user_id,
    )
    if held_reply is not None:
        await _complete_resume_leg(message, event, message_logger)
        return held_reply

    reply = await _plan_and_run(
        event,
        planner=planner,
        workflow_runtime=workflow_runtime,
        inventory_query=inventory_query,
        pending_report_store=pending_report_store,
        actor_user_id=actor_user_id,
    )
    await _complete_resume_leg(message, event, message_logger)
    return reply


async def resume_pending_report_with_petty_cash_recipient(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_report_store: PendingReportStore,
    member_resolver: MemberNameResolutionService,
    petty_cash_query: PettyCashRecipientQueryService,
    planner: Planner,
    workflow_runtime: WorkflowRuntime,
    actor: ActorIdentity | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    message_logger: MessageLogger | None = None,
) -> ReplySpec | None:
    """Resume a petty-cash issuance held by _run_petty_cash_recipient_gate,
    now that the user tapped who the cash is actually for -- or "None of
    these".

    Unlike resume_pending_report_with_member_candidate, this cannot simply
    patch the name and hand off to _plan_and_run: the recipient's *advance
    account* still has to be resolved (created on first issuance), which is
    a DB round trip, and _plan_and_run does not re-run the seeding pass that
    would otherwise do it. So this leg performs that resolution itself --
    the same call _seed_petty_cash_recipient makes -- before planning.

    That ordering is deliberate: the account is only ever created for the
    person the user actually chose. Resolving accounts for every candidate
    up front would have made the picker cheaper to build and would have
    created advance accounts for people who were never picked.
    """
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = message.metadata.get("interactive_reply_id")
    if not row_id or not str(row_id).startswith(_PETTY_CASH_RECIPIENT_ROW_PREFIX):
        return None

    event = await pending_report_store.pop_pending(user_id=actor_user_id)
    if event is None:
        if message_logger:
            await _safe(message_logger.mark_completed(correlation_id=message.correlation_id))
        return ReplySpec(text="That selection expired — please resend your request.")

    name_hint = str(event.fields.get("recipient_name") or "")

    if row_id == PETTY_CASH_RECIPIENT_NONE_ROW_ID:
        await _complete_resume_leg(message, event, message_logger)
        return ReplySpec(text=render_petty_cash_recipient_not_found_reply(name_hint))

    entity_id = str(row_id)[len(_PETTY_CASH_RECIPIENT_ROW_PREFIX):]
    try:
        display_name = await member_resolver.get_active_display_name(
            organization_id=event.organization_id, entity_id=entity_id
        )
    except Exception:
        _log.exception(
            "petty_cash_recipient.lookup_failed correlation_id=%s", event.correlation_id
        )
        display_name = None

    if display_name is None:
        await _complete_resume_leg(message, event, message_logger)
        return ReplySpec(text="That selection expired — please resend your request.")

    event.fields["recipient_name"] = display_name

    # The leg _plan_and_run won't do for us -- see the docstring above.
    try:
        account = await petty_cash_query.resolve_or_create_advance_account(
            organization_id=event.organization_id,
            recipient_name=display_name,
            created_by=actor.user_id if actor is not None else actor_user_id,
        )
    except Exception:
        _log.exception(
            "petty_cash_recipient.account_failed correlation_id=%s", event.correlation_id
        )
        account = None

    if account is None:
        await _complete_resume_leg(message, event, message_logger)
        return ReplySpec(
            text="Sorry, I couldn't set up that account — please resend your request."
        )

    event.fields["recipient_account_id"] = str(account.id)
    event.fields["recipient_account_name"] = account.name

    reply = await _plan_and_run(
        event,
        planner=planner,
        workflow_runtime=workflow_runtime,
        inventory_query=inventory_query,
        pending_report_store=pending_report_store,
        actor_user_id=actor_user_id,
    )
    await _complete_resume_leg(message, event, message_logger)
    return reply


async def start_member_create_plan(
    *,
    name_hint: str,
    original_event: CanonicalEventV2,
    actor: ActorIdentity | None,
    plan_store: PlanStore,
    workflow_runtime: WorkflowRuntime,
    recent_turns: RecentTurnsStore | None = None,
) -> ReplySpec | None:
    """Start CREATE_USER for real, and remember (in the shared PlanStore)
    that the held ADD_PROJECT_MEMBER request should resume once it succeeds.

    A Plan of exactly two steps -- create_user (RUNNING, started here) and
    add_member (PENDING, its member_name a StepRef pointing at create_user's
    full_name output) -- per ENTITY_RESOLUTION_PLAN.md sections 3.3/8.1: this
    is the entity-resolution layer's continuation, built on the shared
    Plan/PlanStep/PlanStore contracts rather than a standalone mechanism, so
    the composite-request plan layer's Phase 4 has one executor to extend
    rather than a second one to reconcile against.

    add_member's role/created_by_role/project_id travel as literals, copied
    from original_event -- they were already known before the Missing result
    paused this request and never depended on CREATE_USER's outcome. Only
    member_name is a StepRef, because it is the one field CREATE_USER's own
    execution determines (the exact name the new user was actually created
    under).

    Mirrors start_project_setup_followup's "hand-build a PlannerDecisionV2 +
    CanonicalEventV2, then call workflow_runtime.start()" pattern for
    starting CREATE_USER itself -- there is no lower-level shortcut. CREATE_
    USER's role is seeded from the SAME role hint the original add-member
    request carried (a project manager added as PM plausibly gets that as
    their org-wide role too).

    ``recent_turns``, when supplied, is checked for a phone number the
    sender already stated earlier in this conversation (e.g. "+91 97781
    90485 create Hysam in project hospital" -- ADD_PROJECT_MEMBER's own
    extraction has no phone-number field, so that number is otherwise
    dropped on the floor, and CREATE_USER re-asking for it several turns
    later reads as "I already told you that"). When found, it is seeded
    directly, so CREATE_USER's own build_draft has everything it needs on
    this very first pass and goes straight to its confirmation prompt --
    which already says "please double check this number", the existing
    safety net for a value the sender didn't just re-type on purpose. When
    not found (or ``recent_turns`` is None), CREATE_USER's own build_draft
    asks for it as before -- this is purely additive, never a regression on
    the case nothing was mentioned.

    Returns the full ReplySpec for CREATE_USER's own next question -- a
    Yes/No-buttoned confirmation if the number was recalled, otherwise a
    plain-text question (usually the phone number) -- or None if nothing
    could be started. Built via render_workflow_run_reply_spec, the one
    place that decides plain text vs buttons vs a tappable list for a
    WorkflowRunResult (see its own docstring): this function used to return
    only run.pending_prompt as a bare string, which meant a recalled number
    -- landing on STARTED, a real draft, on the very first call -- sent a
    plain-text "Reply YES to confirm or NO to cancel" instead of tappable
    buttons. That prompt was reachable before recall existed too, in
    principle, but recall is what actually made STARTED reachable from
    here on the very first pass; going through pending_prompt was correct
    right up until it wasn't. render_workflow_run_reply_spec's own
    docstring documents this exact bug class already happening once before,
    in the slot-answer fast path -- reusing it here instead of a second
    hand-rolled prompt extraction is what stops a third occurrence.
    """
    org_id = str(getattr(actor, "organization_id", None) or "")
    user_id = str(getattr(actor, "user_id", None) or "")
    if not org_id or not user_id:
        return None

    role_hint = original_event.fields.get("role")

    recalled_number: str | None = None
    if recent_turns is not None:
        try:
            turns = await recent_turns.recent(user_id=user_id)
            recalled_number = find_mentioned_phone_number(t.user_text for t in turns)
        except Exception:  # noqa: BLE001 -- a recall miss just means CREATE_USER
            # asks for the number the normal way; never worth failing the
            # create-offer over.
            _log.warning("member_create_plan.recall_failed user=%s", user_id, exc_info=True)

    corr_id = _new_id("member_create")
    decision = PlannerDecisionV2(
        correlation_id=corr_id,
        source_message_id=corr_id,
        decision_type=PlannerDecisionType.START_WORKFLOW,
        workflow_key=WorkflowKey.CREATE_USER,
        reason=CanonicalEventType.CREATE_USER_REQUESTED,
        organization_id=org_id,
        user_id=user_id,
    )
    event_fields: dict[str, object] = {
        "full_name": name_hint,
        "role": role_hint,
        "created_by_role": getattr(actor, "role", None),
    }
    if recalled_number is not None:
        event_fields["whatsapp_number"] = recalled_number
    event = CanonicalEventV2(
        event_id=corr_id,
        correlation_id=corr_id,
        source_message_id=corr_id,
        event_type=CanonicalEventType.CREATE_USER_REQUESTED,
        completeness=_IntentCompleteness.ACTIONABLE,
        organization_id=org_id,
        user_id=user_id,
        fields=event_fields,
    )

    await _safe(workflow_runtime.abandon_optional_question(user_id))

    try:
        run = await workflow_runtime.start(decision, event)
    except Exception:  # noqa: BLE001 -- never raise into the tap handler
        _log.exception("member_create_plan.start_failed org=%s", org_id)
        return None
    if not run.pending_prompt:
        _log.error("member_create_plan.no_prompt org=%s status=%s", org_id, run.status.value)
        return None

    # Persisted only AFTER the workflow actually started, so the plan can
    # record the real workflow_instance_id it is waiting on -- the guard that
    # stops an abandoned plan from later attaching itself to a *different*
    # CREATE_USER the same user starts inside the TTL window (see
    # advance_member_plan_after_user_created). Storing first and patching
    # afterwards would leave a window where the plan matches any CREATE_USER;
    # storing after means a failed start simply leaves no plan behind at all,
    # which is also why the two failure branches above no longer need to
    # clear one.
    create_user_step = PlanStep(
        step_id=_CREATE_USER_STEP_ID,
        workflow_key=WorkflowKey.CREATE_USER,
        event_type=CanonicalEventType.CREATE_USER_REQUESTED,
        fields={"full_name": name_hint, "role": role_hint},
        status=StepStatus.RUNNING,
        workflow_instance_id=run.workflow_instance_id,
    )
    add_member_step = PlanStep(
        step_id=_ADD_MEMBER_STEP_ID,
        workflow_key=WorkflowKey.ADD_PROJECT_MEMBER,
        event_type=CanonicalEventType.ADD_PROJECT_MEMBER_REQUESTED,
        fields={
            "member_name": StepRef(step_id=_CREATE_USER_STEP_ID, output_key="full_name"),
            "role": role_hint,
            "created_by_role": original_event.fields.get("created_by_role"),
        },
        # Which project this adds to is SCOPE, not a collected field --
        # add_project_member reads it off the event, the same way
        # site_create reads state["project_id"]. Previously carried in
        # `fields` and popped back out by hand before building the event;
        # `scope` is now the typed home for it (plan-layer doc §11.1(b)).
        scope={"project_id": str(original_event.project_id or "")},
        status=StepStatus.PENDING,
    )
    plan = Plan(
        plan_id=_new_id("plan"),
        correlation_id=original_event.correlation_id,
        user_id=user_id,
        organization_id=org_id,
        origin=PlanOrigin.RESOLUTION,
        source_message_id=original_event.source_message_id,
        conversation_id=original_event.conversation_id,
        permissions=tuple(original_event.permissions),
        steps=(create_user_step, add_member_step),
    )
    await _safe(plan_store.start_plan(plan=plan))
    return render_workflow_run_reply_spec(run)


async def resume_pending_report_with_member_create_offer(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_report_store: PendingReportStore,
    plan_store: PlanStore,
    workflow_runtime: WorkflowRuntime,
    actor: ActorIdentity | None = None,
    message_logger: MessageLogger | None = None,
    recent_turns: RecentTurnsStore | None = None,
) -> ReplySpec | None:
    """Resume a report held by the member-create offer
    (_run_member_name_gate's Missing case), now that the sender said whether
    to create the missing user.

    On Yes, starts the CREATE_USER -> ADD_PROJECT_MEMBER chain (see
    start_member_create_plan) instead of the old dead end. On No, the
    original held event is simply dropped -- there is nothing further to
    resume, mirroring resume_pending_report_with_material_create's decline
    path.
    """
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = message.metadata.get("interactive_reply_id")
    if row_id not in (_MEMBER_CREATE_YES_ROW_ID, _MEMBER_CREATE_NO_ROW_ID):
        return None

    event = await pending_report_store.pop_pending(user_id=actor_user_id)
    if event is None:
        if message_logger:
            await _safe(message_logger.mark_completed(correlation_id=message.correlation_id))
        return ReplySpec(text="That selection expired — please resend your request.")

    name_hint = str(event.fields.get("member_name") or "")

    if row_id == _MEMBER_CREATE_NO_ROW_ID:
        await _complete_resume_leg(message, event, message_logger)
        return ReplySpec(text=render_member_create_declined_reply(name_hint))

    reply = await start_member_create_plan(
        name_hint=name_hint,
        original_event=event,
        actor=actor,
        plan_store=plan_store,
        workflow_runtime=workflow_runtime,
        recent_turns=recent_turns,
    )
    await _complete_resume_leg(message, event, message_logger)
    if reply is None:
        return ReplySpec(
            text="Sorry, I couldn't start that — please try again, or ask your admin."
        )
    return reply

