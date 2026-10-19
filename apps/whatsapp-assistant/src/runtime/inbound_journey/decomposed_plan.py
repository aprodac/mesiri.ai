"""Wires the decomposer into the live message path
(docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md §9, §14).

Called from process_inbound_message right after the canonicalization stage,
only when the primary (single-segment) canonicalization came back
UNRECOGNIZED with semantic_type UNKNOWN -- exactly the trace evidence §9
records: a multi-intent message has no representable single semantic_type,
so "unknown" is extraction's honest answer for it, and today that answer
produces the dead-end generic reply. This is the one place that answer gets
a second chance before falling back to it.

## Project/site resolution (added 2026-07-30)

§14's risk table named a real gap: the single-message path's project-
selection and site-selection gates (runtime/inbound_journey/seeding.py)
never ran for a decomposed segment at all. Closed here, once per
decomposition rather than once per segment -- project/site ambiguity is a
property of the SENDER (which projects/sites they're authorized on), not of
any individual segment, so every segment of one message shares the same
answer. _resolve_project_and_site runs before any segment is canonicalized;
if it can't resolve automatically (more than one project, or the resolved
project has more than one site), the already-decomposed segment texts are
held in PendingDecompositionStore while a picker asks -- mirroring
_run_project_gate/_run_site_gate's own "hold + ask" shape, generalized from
one CanonicalEventV2 to N segment texts.

## Material-unit/stock gates (added 2026-07-31, Phase A5)

The other half of §14's gap, closed by
docs/execution/UNIFIED_UNDERSTANDING_PIPELINE.md's Phase A5: unlike
project/site, an ambiguous catalog name or an over-stock usage report is
genuinely PER-SEGMENT (it depends on that one segment's own material_name/
quantity, never the sender as a whole), so it cannot be resolved once up
front the way project/site is. _process_remaining_segments below builds
each segment's CanonicalEventV2 one at a time, in order, and runs the same
single-message gates (seeding.py's _run_material_unit_gates/_run_stock_gate,
completely unmodified) on it before moving to the next. When a segment's own
gate needs to pause, EVERYTHING needed to continue -- every earlier
segment's already-fully-resolved event (`built_events`), the one segment
paused mid-gate (`pending_event`), and every segment text not yet even
touched (`segments`) -- is held in the same PendingDecompositionStore the
project/site gate already uses, and one of five new resume legs
(resume_pending_decomposition_with_material/_material_create/
_material_unit_choice/_unit/_stock_choice) answers it, mirroring
resume.py's own five single-message legs almost exactly -- the difference
is always "then continue the decomposition loop" where resume.py says
"then call _plan_and_run".

_run_segment_gates reuses seeding.py's gate functions completely
unmodified, via `_NullPendingReportStore`: those functions were written to
pause by writing into interactions/pending_report.py's PendingReportStore
(one CanonicalEventV2, no notion of "N more segments still to come"), which
is the wrong store for a decomposition segment's pause -- so a throwaway
stub swallows that write, and THIS module persists the real pause state
(built_events/pending_event/segments) itself. No gate function in
seeding.py was changed to make this work.

Deliberately NOT touching interactions/handler.py, runtime/plan_executor.py,
or any already-STARTED workflow's own gates -- this closes the gap only for
segments still being turned into a Plan, before anything has started. A
Plan's later steps (once the whole-plan preview is confirmed) run through
plan_executor.py exactly as before; project/site is already trivially
satisfied there since every segment's event already carries a resolved
project_id/site_id (either from this module's own resolution, or a StepRef
for one created earlier in the same message) by the time _build_and_preview_
plan calls build_plan_from_segments.

Every failure mode here degrades to `None` -- "not applicable, fall through
to today's unrecognized-message reply unchanged" -- never an exception that
could take down an otherwise-working message. A message that reaches this
function has already failed single-intent understanding once; there is
nothing this module could do that makes that outcome worse, and several
things (a bad decomposition, a provider outage) that must not make it worse
either.
"""

from __future__ import annotations

from backend.ports import ActorIdentity
from canonicalization import build_canonical_event
from canonicalization.question_note import question_note_candidate
from channel.replies import (
    ReplySpec,
    render_material_create_declined_reply,
    render_material_create_offer,
    render_material_create_unit_picker,
    render_material_created_reply,
    render_module_disabled_reply,
    render_no_projects_reply,
    render_plan_preview_reply,
    render_project_picker,
    render_site_picker,
)
from mesiri_ai.ports.decomposition import DecompositionProvider
from mesiri_contracts.assistant.canonical_event import CanonicalEventType, IntentCompleteness
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage
from mesiri_contracts.assistant.understanding_result import UnderstandingResult
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.resolved_context import ResolvedContextV2
from mesiri_contracts.common.ids import new_id
from planner.routing import WORKFLOW_KEY_BY_EVENT
from planning.decomposition import build_plan_from_segments
from planning.plan_store import PlanStore
from planning.preview import render_plan_preview
from runtime.inbound_journey._shared import _log
from runtime.inbound_journey.pending_decomposition import (
    PendingDecomposition,
    PendingDecompositionStore,
)
from runtime.inbound_journey.seeding import (
    _inject_inventory_context,
    _run_material_unit_gates,
    _run_stock_gate,
)
from runtime.inventory_query import MaterialInventoryQueryService
from runtime.material_catalog_query import MaterialCatalogQueryService
from runtime.org_settings_query import OrganizationSettingsQueryService
from understanding.pipeline import UnderstandingPipeline
from workflows import registry as workflow_registry

#: Decomposition only makes sense where there is text to split.
#: IMAGE/DOCUMENT go through vision first and their "text" is a rendering of
#: extracted fields, not something a sender composed as several sentences --
#: out of scope for V1, same narrowness this whole layer states plainly
#: elsewhere (ENTITY_RESOLUTION_PLAN.md ADR-E3).
_DECOMPOSABLE_MODALITIES = (InputModality.TEXT, InputModality.INTERACTIVE, InputModality.VOICE)

#: Deliberately the SAME prefixes resume.py's single-report project/site
#: gates use (render_project_picker/render_site_picker bake these in). Safe
#: to share: PendingReportStore and PendingDecompositionStore are two
#: different Redis keys, and a user is only ever in one pending state at a
#: time by construction (a message goes down the single-report path or the
#: decomposed path, never both) -- so whichever store actually holds
#: something for a given tap is the one that answers, and the other's
#: resume function safely no-ops (its own pop_pending returns None first).
_PROJECT_ROW_PREFIX = "proj_"
_SITE_ROW_PREFIX = "site_"

#: Same reasoning as _PROJECT_ROW_PREFIX/_SITE_ROW_PREFIX above -- these are
#: the SAME row ids resume.py's own material/unit/stock resume legs answer
#: (render_material_picker/render_material_create_offer/
#: render_material_create_unit_picker/render_unit_mismatch_reply/
#: render_usage_exceeds_stock_reply all bake these in), re-declared as
#: literals rather than imported from runtime.inbound_journey.resume: that
#: module imports runtime.inbound_journey.process, which imports THIS
#: module (try_start_decomposed_plan) -- importing resume.py here would
#: close that into a circular import.
_MATERIAL_ROW_PREFIX = "mat_"
_MATERIAL_CREATE_YES_ROW_ID = "matnew_yes"
_MATERIAL_CREATE_NO_ROW_ID = "matnew_no"
_MATERIAL_CREATE_UNIT_PREFIX = "matunit_"
_UNIT_YES_ROW_PREFIX = "unit_yes_"
_UNIT_NO_ROW_ID = "unit_no"
_STOCK_CAP_ROW_ID = "stock_cap"
_STOCK_ARRIVAL_ROW_ID = "stock_arrival"
_STOCK_CANCEL_ROW_ID = "stock_cancel"


class _NullPendingReportStore:
    """Stands in for interactions/pending_report.py's PendingReportStore
    when seeding.py's gate functions run over a DECOMPOSITION segment rather
    than a single message. Those functions pause by calling
    ``pending_report_store.set_pending(...)`` -- meant for a single
    CanonicalEventV2 with no notion of "N more segments still to come" --
    so that write is simply discarded here; THIS module persists the real
    pause state (built_events/pending_event/segments) via
    PendingDecompositionStore instead. The gate functions are otherwise
    unmodified: they still mutate the event in place and still return a
    ReplySpec to signal "pause here", which is all this module reads."""

    async def set_pending(self, *, user_id: str, event: CanonicalEventV2) -> None:
        return None


async def _run_segment_gates(
    event: CanonicalEventV2,
    *,
    actor: ActorIdentity | None,
    actor_user_id: str,
    catalog_query: MaterialCatalogQueryService | None,
    inventory_query: MaterialInventoryQueryService | None,
    org_settings_query: OrganizationSettingsQueryService | None,
) -> ReplySpec | None:
    """Run every remaining single-message gate against one segment's own
    CanonicalEventV2, mutating it in place exactly as the single-message
    path (runtime/inbound_journey/process.py, resume.py) does before
    starting a workflow. Returns the first pause reply, or None once every
    gate has passed.

    Deliberately does NOT re-run _run_project_gate/_run_site_gate here --
    _resolve_project_and_site already settled project/site for the whole
    decomposition (see module docstring), and calling those two gates again
    would reintroduce a failure mode that resolution deliberately avoids:
    _run_project_gate fails CLOSED (asks, or says "no projects") the moment
    project_id is None regardless of WHY -- including `actor is None`, which
    _resolve_project_and_site treats as "no gate applicable, fall through
    unresolved" on purpose (its own docstring: "the same degrade every other
    optional dependency in this layer uses, not a new failure mode"). A
    real regression, caught by this module's own pre-existing tests, which
    is why this note exists."""
    null_store = _NullPendingReportStore()

    if catalog_query is not None:
        reply = await _run_material_unit_gates(
            event,
            catalog_query=catalog_query,
            pending_report_store=null_store,
            actor_user_id=actor_user_id,
            actor_role=getattr(actor, "role", None),
            org_settings_query=org_settings_query,
        )
        if reply is not None:
            return reply

    await _inject_inventory_context(event, inventory_query)
    reply = await _run_stock_gate(
        event,
        pending_report_store=null_store,
        actor_user_id=actor_user_id,
        org_settings_query=org_settings_query,
    )
    if reply is not None:
        return reply
    return None


async def _may_create_material_for_segment(
    event: CanonicalEventV2,
    *,
    actor: ActorIdentity | None,
    org_settings_query: OrganizationSettingsQueryService | None,
) -> bool:
    from runtime.inbound_journey.seeding import _may_create_material

    return await _may_create_material(
        event, actor_role=getattr(actor, "role", None), org_settings_query=org_settings_query
    )


async def _create_material_for_segment(
    event: CanonicalEventV2,
    *,
    unit_id: str,
    unit_display: str,
    actor_user_id: str,
    catalog_query: MaterialCatalogQueryService,
) -> str | None:
    """Create the catalog entry a decomposition segment's material-create
    offer was accepted for, mutating `event` with the new material_id/
    unit_id exactly as resume.py's own _create_material_and_resume does.
    Returns the confirmation text to prepend once the plan preview is sent,
    or None if creation failed (the segment is left as-is; its own material/
    unit gate will simply ask again on the way through, same degrade as a
    lookup failure elsewhere in this layer)."""
    name = str(event.fields.get("material_name") or "")
    try:
        created = await catalog_query.create_material(
            organization_id=event.organization_id,
            name=name,
            unit_id=unit_id,
            created_by=actor_user_id,
        )
    except Exception:  # noqa: BLE001 -- never let a catalog write failure
        # take down a whole decomposition; the segment just stays unresolved.
        _log.exception("plan.material_create_failed correlation_id=%s", event.correlation_id)
        return None
    if created is None:
        return None
    event.fields["material_id"] = str(created["id"])
    event.fields["unit_id"] = str(created["default_unit_id"] or unit_id)
    event.fields["unit"] = unit_display
    return render_material_created_reply(created["name"], unit_display)


def _inherit_resolved_scope(
    event: CanonicalEventV2, resolved: ResolvedContextV2, actor: ActorIdentity | None
) -> None:
    """Every part of one message is about the same project and site, so a
    part never asks for them again (request [38]: "Plastering done on 2nd
    floor" inside a four-part note was rejected with "Which site is this
    for?" when the company has one site and the message names it).

    Fills a part's missing project/site from the message's resolved context,
    then from the sender's own access: a lone project, and a lone site under
    it (or a lone site overall when no project is known). With more than one
    site nothing is guessed -- _resolve_project_and_site has already asked.
    Mutates ``event`` in place, like the single-message gates do."""
    if event.project_id is None and resolved.project_id is not None:
        event.project_id = resolved.project_id
    if event.site_id is None and resolved.site_id is not None:
        event.site_id = resolved.site_id
    if actor is None:
        return
    if event.project_id is None and len(actor.projects) == 1:
        event.project_id = actor.projects[0].id
    if event.site_id is None:
        sites = [
            s
            for s in actor.sites
            if event.project_id is None or s.project_id == event.project_id
        ]
        if len(sites) == 1:
            event.site_id = sites[0].id
            if event.project_id is None:
                event.project_id = sites[0].project_id


def _not_understood_event(resolved: ResolvedContextV2, segment_text: str) -> CanonicalEventV2:
    """A placeholder for a part that could not be read. It maps to no
    workflow, so build_plan_from_segments reports it as skipped and nothing
    runs for it."""
    return CanonicalEventV2(
        event_id=new_id("evt"),
        correlation_id=resolved.correlation_id,
        source_message_id=resolved.source_message_id,
        conversation_id=resolved.conversation_id,
        event_type=CanonicalEventType.CLARIFICATION_REQUIRED,
        completeness=IntentCompleteness.NOT_ACTIONABLE,
        organization_id=resolved.organization_id,
        user_id=resolved.user_id,
        project_id=resolved.project_id,
        site_id=resolved.site_id,
        permissions=resolved.permissions,
        fields={"source_text": segment_text, "not_understood": True},
    )


def render_skipped_parts_note(skipped) -> str:  # type: ignore[no-untyped-def]
    """One short block for the plan preview naming the parts of the note that
    are not in the plan: questions (not answerable here, so say who can) and
    parts that could not be read. Empty when nothing was left out. Honest
    about what happens: nothing is forwarded, so it asks them to follow up."""
    lines: list[str] = []
    for part in skipped:
        text = " ".join(str(part.text).split())[:120]
        if part.reason == "not_understood":
            lines.append(f"I couldn't understand: \"{text}\"")
        elif part.event_type == CanonicalEventType.GENERAL_QUESTION_ASKED.value and text:
            lines.append(
                f"Your question \"{text}\" isn't something I can answer yet -- please check with your engineer."
            )
    return "\n".join(lines)


async def _process_remaining_segments(
    *,
    segment_texts: tuple[str, ...],
    built_events: list[CanonicalEventV2],
    resolved: ResolvedContextV2,
    pipeline: UnderstandingPipeline,
    expense_categories: list[str] | None,
    correlation_id: str,
    source_message_id: str,
    actor: ActorIdentity | None,
    actor_user_id: str,
    catalog_query: MaterialCatalogQueryService | None,
    inventory_query: MaterialInventoryQueryService | None,
    org_settings_query: OrganizationSettingsQueryService | None,
    pending_decomposition_store: PendingDecompositionStore | None,
) -> list[CanonicalEventV2] | ReplySpec:
    """Build and gate every segment in `segment_texts`, in order, appending
    each to `built_events` once it fully passes. Returns the complete event
    list once every segment is done (or was skipped -- see the try/except
    below), or a ReplySpec the moment any segment's own gate needs to pause
    -- with the pause state (built_events so far, this segment's own
    partially-resolved event, and every segment text after it) already
    persisted, so a resume leg has everything it needs."""
    for index, segment_text in enumerate(segment_texts):
        try:
            segment_understanding = await pipeline.understand_text_segment(
                segment_text,
                source_message_id=source_message_id,
                correlation_id=correlation_id,
                expense_categories=expense_categories,
            )
            event = build_canonical_event(segment_understanding, resolved)
            if event.event_type is CanonicalEventType.GENERAL_QUESTION_ASKED and segment_text.strip():
                # A question inside a site note (request 57, B2): not echoed
                # and dropped -- noted for the engineer, as a step the sender
                # sees in the preview like any other part of the note.
                note = question_note_candidate(segment_text)
                event = build_canonical_event(
                    segment_understanding.model_copy(
                        update={
                            "semantic_type": note.semantic_type,
                            "candidates": [note],
                            "intents": [note],
                        }
                    ),
                    resolved,
                )
            _inherit_resolved_scope(event, resolved, actor)
            if WORKFLOW_KEY_BY_EVENT.get(event.event_type) is None:
                # Small talk inside a site note: no workflow will run it, but
                # the reply says it was seen.
                event.fields["source_text"] = segment_text
        except Exception:  # noqa: BLE001 -- one bad segment must not sink the
            # rest -- same degrade try_start_decomposed_plan's docstring
            # already documents for this exact loop.
            _log.warning(
                "plan.segment_understand_failed correlation_id=%s segment=%r",
                correlation_id,
                segment_text,
                exc_info=True,
            )
            # Carried in built_events (which survives every picker pause) so
            # the closing reply can say "I couldn't understand: ...".
            built_events.append(_not_understood_event(resolved, segment_text))
            continue

        gate_reply = await _run_segment_gates(
            event,
            actor=actor,
            actor_user_id=actor_user_id,
            catalog_query=catalog_query,
            inventory_query=inventory_query,
            org_settings_query=org_settings_query,
        )
        if gate_reply is not None:
            if pending_decomposition_store is not None:
                await pending_decomposition_store.set_pending(
                    user_id=actor_user_id,
                    pending=PendingDecomposition(
                        segments=tuple(segment_texts[index + 1 :]),
                        resolved=resolved,
                        expense_categories=tuple(expense_categories) if expense_categories else None,
                        built_events=tuple(built_events),
                        pending_event=event,
                    ),
                )
            return gate_reply
        built_events.append(event)

    return built_events


async def _finish_with_events(
    events: list[CanonicalEventV2],
    *,
    plan_store: PlanStore,
    correlation_id: str,
) -> ReplySpec | None:
    """Turn a fully-gated event list into a Plan and send the §8 preview --
    the shared tail of the fresh-message path and every resume leg below,
    once _process_remaining_segments has nothing left to pause on."""
    # WA-07: steps for a module the company hasn't switched on are dropped
    # here, before anything is persisted, and the preview says so. If every
    # step needs a switched-off module, the user gets the same polite reply
    # a single request would.
    kept: list[CanonicalEventV2] = []
    skipped_modules: list[str] = []
    for event in events:
        module = workflow_registry.module_for_event(
            WORKFLOW_KEY_BY_EVENT.get(event.event_type), event.fields
        )
        if workflow_registry.module_is_enabled(module):
            kept.append(event)
        else:
            skipped_modules.append(str(module))
    if skipped_modules and not kept:
        return ReplySpec(text=render_module_disabled_reply(skipped_modules[0]))
    events = kept

    result = build_plan_from_segments(events, plan_id=new_id("plan"))
    if result.plan is None:
        return None
    try:
        await plan_store.start_plan(plan=result.plan)
        preview = render_plan_preview(result.plan)
        note = render_skipped_parts_note(result.skipped)
        if note:
            preview = f"{preview}\n\n{note}"
        if skipped_modules:
            n = len(skipped_modules)
            preview = (
                f"{n} part{'' if n == 1 else 's'} of your message "
                f"{'needs' if n == 1 else 'need'} a feature that isn't switched on "
                "for your company, so I left "
                f"{'it' if n == 1 else 'them'} out.\n\n{preview}"
            )
        return render_plan_preview_reply(preview)
    except Exception:  # noqa: BLE001 -- see module docstring: never let a
        # plan-persist failure take down the message.
        _log.exception("plan.persist_failed correlation_id=%s", correlation_id)
        return None


async def _resolve_project_and_site(
    *,
    actor: ActorIdentity | None,
    resolved: ResolvedContextV2,
    segments: tuple[str, ...],
    expense_categories: list[str] | None,
    pending_decomposition_store: PendingDecompositionStore | None,
    user_id: str,
) -> ResolvedContextV2 | ReplySpec:
    """Resolve project_id/site_id ONCE for the whole decomposition, or hold
    and ask. Returns the (possibly patched) context to proceed with, or a
    ReplySpec to send instead (a picker, or "you have no projects").

    Mirrors _run_project_gate/_run_site_gate's own single-project/single-site
    auto-resolve and fail-open/fail-closed reasoning, but reads from `actor`
    directly rather than a CanonicalEventV2 -- project/site membership is the
    same for every segment of one message, so there is nothing per-segment
    to read it off here.

    Falls through UNRESOLVED (no gate at all) when `actor` is None or
    `pending_decomposition_store` was never wired -- the same degrade every
    other optional dependency in this layer uses, not a new failure mode.
    """
    if resolved.project_id is None and actor is not None:
        if not actor.projects:
            return ReplySpec(text=render_no_projects_reply())
        if len(actor.projects) == 1:
            p = actor.projects[0]
            resolved = resolved.model_copy(update={"project_id": p.id, "context_project_id": p.id})
        elif pending_decomposition_store is not None:
            await pending_decomposition_store.set_pending(
                user_id=user_id,
                pending=PendingDecomposition(
                    segments=segments,
                    resolved=resolved,
                    expense_categories=tuple(expense_categories) if expense_categories else None,
                ),
            )
            return render_project_picker([(p.id, p.name, p.location) for p in actor.projects])
        # else: no store wired -- fall through unresolved.

    if resolved.project_id is not None and resolved.site_id is None and actor is not None:
        sites = [s for s in actor.sites if s.project_id == resolved.project_id]
        if len(sites) == 1:
            s = sites[0]
            resolved = resolved.model_copy(update={"site_id": s.id, "context_site_id": s.id})
        elif len(sites) > 1 and pending_decomposition_store is not None:
            await pending_decomposition_store.set_pending(
                user_id=user_id,
                pending=PendingDecomposition(
                    segments=segments,
                    resolved=resolved,
                    expense_categories=tuple(expense_categories) if expense_categories else None,
                ),
            )
            return render_site_picker([(s.id, s.name) for s in sites], allow_combined=False)
        # else: zero sites (fail open, nothing to choose from) or no store
        # wired -- fall through with site_id still unresolved either way.

    return resolved


async def _build_and_preview_plan(
    *,
    segments: list[str] | tuple[str, ...],
    resolved: ResolvedContextV2,
    pipeline: UnderstandingPipeline,
    expense_categories: list[str] | None,
    plan_store: PlanStore,
    correlation_id: str,
    source_message_id: str,
    actor: ActorIdentity | None = None,
    actor_user_id: str = "",
    catalog_query: MaterialCatalogQueryService | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    org_settings_query: OrganizationSettingsQueryService | None = None,
    pending_decomposition_store: PendingDecompositionStore | None = None,
) -> ReplySpec | None:
    """Per-segment extract -> canonicalize -> gate -> entity-link -> persist
    all-PENDING -> the §8 preview. Shared by the fresh-message path
    (try_start_decomposed_plan) and every picker resume below, so a picker
    tap runs the exact same segment-building logic a message that never
    needed one does."""
    result = await _process_remaining_segments(
        segment_texts=tuple(segments),
        built_events=[],
        resolved=resolved,
        pipeline=pipeline,
        expense_categories=expense_categories,
        correlation_id=correlation_id,
        source_message_id=source_message_id,
        actor=actor,
        actor_user_id=actor_user_id,
        catalog_query=catalog_query,
        inventory_query=inventory_query,
        org_settings_query=org_settings_query,
        pending_decomposition_store=pending_decomposition_store,
    )
    if isinstance(result, ReplySpec):
        return result
    return await _finish_with_events(result, plan_store=plan_store, correlation_id=correlation_id)


async def try_start_decomposed_plan(
    *,
    message_modality: InputModality,
    understanding: UnderstandingResult,
    resolved: ResolvedContextV2,
    pipeline: UnderstandingPipeline,
    decomposition: DecompositionProvider | None,
    plan_store: PlanStore | None,
    expense_categories: list[str] | None,
    correlation_id: str,
    actor: ActorIdentity | None = None,
    actor_user_id: str = "",
    pending_decomposition_store: PendingDecompositionStore | None = None,
    catalog_query: MaterialCatalogQueryService | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    org_settings_query: OrganizationSettingsQueryService | None = None,
) -> ReplySpec | None:
    """Attempt to turn an UNKNOWN-classified message into a multi-step Plan.

    Persists the plan (every step PENDING -- see planning/preview.py's
    docstring on why an all-PENDING plan is inert to every other advance
    call) and returns the whole-plan preview (§8, P3) with its own Yes/No --
    nothing is started yet. The Yes tap is handled by
    resume_pending_plan_confirmation, which calls
    runtime/plan_executor.py's begin_plan once the user actually confirms.
    No WorkflowRuntime is needed here for exactly that reason: this function
    never starts a workflow, only persists and describes one.

    Returns None for the caller to fall through to today's behaviour
    unchanged. Never raises.
    """
    if decomposition is None or plan_store is None:
        return None
    if message_modality not in _DECOMPOSABLE_MODALITIES:
        return None
    # normalized_text is, for both text and voice, exactly the text the
    # primary extract()/understand_voice() call was given -- the original
    # message for text, the translated transcript for voice (see
    # understanding/pipeline.py's _handle_text/_handle_voice). Decomposition
    # must see the same text extraction already failed to classify as one
    # thing, not some other derived field.
    text = (understanding.normalized_text or "").strip()
    if not text:
        return None

    try:
        decomposed = await decomposition.decompose(text, correlation_id=correlation_id)
    except Exception:  # noqa: BLE001 -- a provider outage here must fall through
        # to the ordinary unrecognized-message reply, not fail the message.
        _log.warning("plan.decompose_failed correlation_id=%s", correlation_id, exc_info=True)
        return None
    if not decomposed.is_multi_intent:
        return None

    resolved_or_reply = await _resolve_project_and_site(
        actor=actor,
        resolved=resolved,
        segments=tuple(decomposed.segments),
        expense_categories=expense_categories,
        pending_decomposition_store=pending_decomposition_store,
        user_id=actor_user_id,
    )
    if isinstance(resolved_or_reply, ReplySpec):
        return resolved_or_reply
    resolved = resolved_or_reply

    return await _build_and_preview_plan(
        segments=decomposed.segments,
        resolved=resolved,
        pipeline=pipeline,
        expense_categories=expense_categories,
        plan_store=plan_store,
        correlation_id=correlation_id,
        source_message_id=understanding.source_message_id,
        actor=actor,
        actor_user_id=actor_user_id,
        catalog_query=catalog_query,
        inventory_query=inventory_query,
        org_settings_query=org_settings_query,
        pending_decomposition_store=pending_decomposition_store,
    )


async def resume_pending_decomposition_with_project(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_decomposition_store: PendingDecompositionStore,
    plan_store: PlanStore,
    pipeline: UnderstandingPipeline,
    actor: ActorIdentity | None = None,
    catalog_query: MaterialCatalogQueryService | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    org_settings_query: OrganizationSettingsQueryService | None = None,
) -> ReplySpec | None:
    """A tap on the project picker _resolve_project_and_site sent while
    holding a decomposition. Resolves site next (the project just picked may
    still have more than one site) before finally building the plan."""
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = str(message.metadata.get("interactive_reply_id") or "")
    if not row_id.startswith(_PROJECT_ROW_PREFIX):
        return None

    pending = await pending_decomposition_store.pop_pending(user_id=actor_user_id)
    if pending is None:
        return ReplySpec(text="That selection expired — please resend your request.")

    project_id = row_id.removeprefix(_PROJECT_ROW_PREFIX)
    # Re-checked against the authorized set the picker was built from, the
    # same defence resume_pending_report_with_project applies to its own
    # tap -- an interactive reply id is untrusted client input.
    authorized_ids = {p.id for p in actor.projects} if actor is not None else set()
    if project_id not in authorized_ids:
        return ReplySpec(text="That project isn't available to you — please resend your request.")

    resolved = pending.resolved.model_copy(
        update={"project_id": project_id, "context_project_id": project_id}
    )
    expense_categories = list(pending.expense_categories) if pending.expense_categories else None

    resolved_or_reply = await _resolve_project_and_site(
        actor=actor,
        resolved=resolved,
        segments=pending.segments,
        expense_categories=expense_categories,
        pending_decomposition_store=pending_decomposition_store,
        user_id=actor_user_id,
    )
    if isinstance(resolved_or_reply, ReplySpec):
        return resolved_or_reply
    resolved = resolved_or_reply

    return await _build_and_preview_plan(
        segments=pending.segments,
        resolved=resolved,
        pipeline=pipeline,
        expense_categories=expense_categories,
        plan_store=plan_store,
        correlation_id=resolved.correlation_id,
        source_message_id=resolved.source_message_id,
        actor=actor,
        actor_user_id=actor_user_id,
        catalog_query=catalog_query,
        inventory_query=inventory_query,
        org_settings_query=org_settings_query,
        pending_decomposition_store=pending_decomposition_store,
    )


async def resume_pending_decomposition_with_site(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_decomposition_store: PendingDecompositionStore,
    plan_store: PlanStore,
    pipeline: UnderstandingPipeline,
    actor: ActorIdentity | None = None,
    catalog_query: MaterialCatalogQueryService | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    org_settings_query: OrganizationSettingsQueryService | None = None,
) -> ReplySpec | None:
    """A tap on the site picker _resolve_project_and_site sent once project
    was already settled. Project is fixed by this point, so this only ever
    fills in site_id and moves straight to building the plan."""
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = str(message.metadata.get("interactive_reply_id") or "")
    if not row_id.startswith(_SITE_ROW_PREFIX):
        return None

    pending = await pending_decomposition_store.pop_pending(user_id=actor_user_id)
    if pending is None:
        return ReplySpec(text="That selection expired — please resend your request.")

    site_id = row_id.removeprefix(_SITE_ROW_PREFIX)
    authorized_ids = (
        {s.id for s in actor.sites if s.project_id == pending.resolved.project_id}
        if actor is not None
        else set()
    )
    if site_id not in authorized_ids:
        return ReplySpec(text="That site isn't available to you — please resend your request.")

    resolved = pending.resolved.model_copy(update={"site_id": site_id, "context_site_id": site_id})
    expense_categories = list(pending.expense_categories) if pending.expense_categories else None

    return await _build_and_preview_plan(
        segments=pending.segments,
        resolved=resolved,
        pipeline=pipeline,
        expense_categories=expense_categories,
        plan_store=plan_store,
        correlation_id=resolved.correlation_id,
        source_message_id=resolved.source_message_id,
        actor=actor,
        actor_user_id=actor_user_id,
        catalog_query=catalog_query,
        inventory_query=inventory_query,
        org_settings_query=org_settings_query,
        pending_decomposition_store=pending_decomposition_store,
    )


async def _pop_gate_pending(
    pending_decomposition_store: PendingDecompositionStore, actor_user_id: str
) -> PendingDecomposition | None:
    """Shared guard for every material/unit/stock resume leg below: pop, and
    treat "nothing held" or "held, but not a gate pause" (pending_event is
    None -- e.g. a stale project/site pause somehow still present) the same
    way -- expired, never a crash."""
    pending = await pending_decomposition_store.pop_pending(user_id=actor_user_id)
    if pending is None or pending.pending_event is None:
        return None
    return pending


async def _continue_after_segment_resolved(
    event: CanonicalEventV2,
    pending: PendingDecomposition,
    *,
    pipeline: UnderstandingPipeline,
    plan_store: PlanStore,
    actor: ActorIdentity | None,
    actor_user_id: str,
    catalog_query: MaterialCatalogQueryService | None,
    inventory_query: MaterialInventoryQueryService | None,
    org_settings_query: OrganizationSettingsQueryService | None,
    pending_decomposition_store: PendingDecompositionStore | None,
) -> ReplySpec | None:
    """Re-gate `event` (resolving one field, e.g. material_id, can surface a
    LATER gate on the same segment, e.g. a Stock Unit mismatch -- exactly
    the re-run every single-message resume leg in resume.py already does)
    and, once it fully passes, continue processing whatever segments were
    still queued behind it."""
    expense_categories = list(pending.expense_categories) if pending.expense_categories else None

    gate_reply = await _run_segment_gates(
        event,
        actor=actor,
        actor_user_id=actor_user_id,
        catalog_query=catalog_query,
        inventory_query=inventory_query,
        org_settings_query=org_settings_query,
    )
    if gate_reply is not None:
        if pending_decomposition_store is not None:
            await pending_decomposition_store.set_pending(
                user_id=actor_user_id,
                pending=PendingDecomposition(
                    segments=pending.segments,
                    resolved=pending.resolved,
                    expense_categories=tuple(expense_categories) if expense_categories else None,
                    built_events=pending.built_events,
                    pending_event=event,
                ),
            )
        return gate_reply

    result = await _process_remaining_segments(
        segment_texts=pending.segments,
        built_events=[*pending.built_events, event],
        resolved=pending.resolved,
        pipeline=pipeline,
        expense_categories=expense_categories,
        correlation_id=pending.resolved.correlation_id,
        source_message_id=pending.resolved.source_message_id,
        actor=actor,
        actor_user_id=actor_user_id,
        catalog_query=catalog_query,
        inventory_query=inventory_query,
        org_settings_query=org_settings_query,
        pending_decomposition_store=pending_decomposition_store,
    )
    if isinstance(result, ReplySpec):
        return result
    return await _finish_with_events(
        result, plan_store=plan_store, correlation_id=pending.resolved.correlation_id
    )


async def resume_pending_decomposition_with_material(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_decomposition_store: PendingDecompositionStore,
    plan_store: PlanStore,
    pipeline: UnderstandingPipeline,
    actor: ActorIdentity | None = None,
    catalog_query: MaterialCatalogQueryService | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    org_settings_query: OrganizationSettingsQueryService | None = None,
) -> ReplySpec | None:
    """A tap on the material picker a decomposition segment's own material-
    unit gate held (mirrors resume_pending_report_with_material). "None of
    these" falls through to the create offer (when the sender's role
    allows) or a plain not-found reply, exactly as the single-message leg
    does -- see _may_create_material_for_segment."""
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = str(message.metadata.get("interactive_reply_id") or "")
    if not row_id.startswith(_MATERIAL_ROW_PREFIX):
        return None

    pending = await _pop_gate_pending(pending_decomposition_store, actor_user_id)
    if pending is None:
        return ReplySpec(text="That selection expired — please resend your request.")
    event = pending.pending_event
    assert event is not None  # guaranteed by _pop_gate_pending

    from channel.replies import MATERIAL_CANDIDATE_NONE_ROW_ID, render_material_not_found_reply

    if row_id == MATERIAL_CANDIDATE_NONE_ROW_ID:
        name = str(event.fields.get("material_name") or "")
        if catalog_query is not None and await _may_create_material_for_segment(
            event, actor=actor, org_settings_query=org_settings_query
        ):
            if pending_decomposition_store is not None:
                await pending_decomposition_store.set_pending(
                    user_id=actor_user_id,
                    pending=PendingDecomposition(
                        segments=pending.segments,
                        resolved=pending.resolved,
                        expense_categories=pending.expense_categories,
                        built_events=pending.built_events,
                        pending_event=event,
                    ),
                )
            return render_material_create_offer(name)
        return ReplySpec(text=render_material_not_found_reply(name))

    event.fields["material_id"] = row_id.removeprefix(_MATERIAL_ROW_PREFIX)

    return await _continue_after_segment_resolved(
        event,
        pending,
        pipeline=pipeline,
        plan_store=plan_store,
        actor=actor,
        actor_user_id=actor_user_id,
        catalog_query=catalog_query,
        inventory_query=inventory_query,
        org_settings_query=org_settings_query,
        pending_decomposition_store=pending_decomposition_store,
    )


async def resume_pending_decomposition_with_material_create(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_decomposition_store: PendingDecompositionStore,
    plan_store: PlanStore,
    pipeline: UnderstandingPipeline,
    actor: ActorIdentity | None = None,
    catalog_query: MaterialCatalogQueryService | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    org_settings_query: OrganizationSettingsQueryService | None = None,
) -> ReplySpec | None:
    """A tap on the material-create offer (mirrors
    resume_pending_report_with_material_create). On Yes with a usable unit
    already in the report's own words, creates the catalog entry inline; on
    Yes without one, asks a unit picker instead (matunit_ prefix, answered
    by resume_pending_decomposition_with_material_unit_choice)."""
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = str(message.metadata.get("interactive_reply_id") or "")
    if row_id not in (_MATERIAL_CREATE_YES_ROW_ID, _MATERIAL_CREATE_NO_ROW_ID):
        return None

    pending = await _pop_gate_pending(pending_decomposition_store, actor_user_id)
    if pending is None:
        return ReplySpec(text="That selection expired — please resend your request.")
    event = pending.pending_event
    assert event is not None

    name = str(event.fields.get("material_name") or "")
    if row_id == _MATERIAL_CREATE_NO_ROW_ID:
        return ReplySpec(text=render_material_create_declined_reply(name))

    if catalog_query is None:
        return ReplySpec(text="Sorry, I couldn't add that material — please try again, or ask your admin.")

    unit_text = event.fields.get("unit")
    resolved_unit: dict | None = None
    if unit_text:
        try:
            resolved_unit = await catalog_query.resolve_unit(str(unit_text))
        except Exception:  # noqa: BLE001 -- degrade to the unit picker below
            _log.exception(
                "plan.material_create_unit_lookup_failed correlation_id=%s", event.correlation_id
            )

    if resolved_unit is not None:
        confirmation = await _create_material_for_segment(
            event,
            unit_id=str(resolved_unit["id"]),
            unit_display=resolved_unit.get("display_name") or str(unit_text),
            actor_user_id=actor_user_id,
            catalog_query=catalog_query,
        )
        if confirmation is None:
            return ReplySpec(text="Sorry, I couldn't add that material — please try again, or ask your admin.")
        reply = await _continue_after_segment_resolved(
            event,
            pending,
            pipeline=pipeline,
            plan_store=plan_store,
            actor=actor,
            actor_user_id=actor_user_id,
            catalog_query=catalog_query,
            inventory_query=inventory_query,
            org_settings_query=org_settings_query,
            pending_decomposition_store=pending_decomposition_store,
        )
        if reply is None:
            return ReplySpec(text=confirmation)
        return ReplySpec(
            text=f"{confirmation}\n\n{reply.text}",
            list_button_label=reply.list_button_label,
            list_rows=reply.list_rows,
            buttons=reply.buttons,
        )

    try:
        units = await catalog_query.list_units()
    except Exception:  # noqa: BLE001
        _log.exception("plan.material_create_unit_list_failed correlation_id=%s", event.correlation_id)
        units = []
    if not units:
        return ReplySpec(text="Sorry, I couldn't load the units list — please try again, or ask your admin.")

    if pending_decomposition_store is not None:
        await pending_decomposition_store.set_pending(
            user_id=actor_user_id,
            pending=PendingDecomposition(
                segments=pending.segments,
                resolved=pending.resolved,
                expense_categories=pending.expense_categories,
                built_events=pending.built_events,
                pending_event=event,
            ),
        )
    return render_material_create_unit_picker(name, [(str(u["id"]), u["display_name"]) for u in units])


async def resume_pending_decomposition_with_material_unit_choice(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_decomposition_store: PendingDecompositionStore,
    plan_store: PlanStore,
    pipeline: UnderstandingPipeline,
    actor: ActorIdentity | None = None,
    catalog_query: MaterialCatalogQueryService | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    org_settings_query: OrganizationSettingsQueryService | None = None,
) -> ReplySpec | None:
    """A tap on the new-material unit picker (mirrors
    resume_pending_report_with_material_unit_choice) -- creates the catalog
    entry in the chosen unit and continues."""
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = str(message.metadata.get("interactive_reply_id") or "")
    if not row_id.startswith(_MATERIAL_CREATE_UNIT_PREFIX):
        return None

    pending = await _pop_gate_pending(pending_decomposition_store, actor_user_id)
    if pending is None:
        return ReplySpec(text="That selection expired — please resend your request.")
    event = pending.pending_event
    assert event is not None

    if catalog_query is None:
        return ReplySpec(text="Sorry, I couldn't add that material — please try again, or ask your admin.")

    unit_id = row_id.removeprefix(_MATERIAL_CREATE_UNIT_PREFIX)
    try:
        unit = await catalog_query.get_unit(unit_id)
    except Exception:  # noqa: BLE001
        _log.exception("plan.material_create_unit_lookup_failed correlation_id=%s", event.correlation_id)
        unit = None

    confirmation = await _create_material_for_segment(
        event,
        unit_id=unit_id,
        unit_display=(unit or {}).get("display_name") or "",
        actor_user_id=actor_user_id,
        catalog_query=catalog_query,
    )
    if confirmation is None:
        return ReplySpec(text="Sorry, I couldn't add that material — please try again, or ask your admin.")

    reply = await _continue_after_segment_resolved(
        event,
        pending,
        pipeline=pipeline,
        plan_store=plan_store,
        actor=actor,
        actor_user_id=actor_user_id,
        catalog_query=catalog_query,
        inventory_query=inventory_query,
        org_settings_query=org_settings_query,
        pending_decomposition_store=pending_decomposition_store,
    )
    if reply is None:
        return ReplySpec(text=confirmation)
    return ReplySpec(
        text=f"{confirmation}\n\n{reply.text}",
        list_button_label=reply.list_button_label,
        list_rows=reply.list_rows,
        buttons=reply.buttons,
    )


async def resume_pending_decomposition_with_unit(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_decomposition_store: PendingDecompositionStore,
    plan_store: PlanStore,
    pipeline: UnderstandingPipeline,
    actor: ActorIdentity | None = None,
    catalog_query: MaterialCatalogQueryService | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    org_settings_query: OrganizationSettingsQueryService | None = None,
) -> ReplySpec | None:
    """A tap on the Stock Unit mismatch clarification for an EXISTING
    material (mirrors resume_pending_report_with_unit -- distinct from the
    new-material unit picker above, same as the single-message legs are
    kept distinct)."""
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = str(message.metadata.get("interactive_reply_id") or "")
    if row_id == _UNIT_NO_ROW_ID:
        popped = await _pop_gate_pending(pending_decomposition_store, actor_user_id)
        if popped is None:
            return ReplySpec(text="That selection expired — please resend your request.")
        return ReplySpec(text="No problem — please resend the report with the correct unit.")
    if not row_id.startswith(_UNIT_YES_ROW_PREFIX):
        return None

    pending = await _pop_gate_pending(pending_decomposition_store, actor_user_id)
    if pending is None:
        return ReplySpec(text="That selection expired — please resend your request.")
    event = pending.pending_event
    assert event is not None

    event.fields["unit_id"] = row_id.removeprefix(_UNIT_YES_ROW_PREFIX)

    return await _continue_after_segment_resolved(
        event,
        pending,
        pipeline=pipeline,
        plan_store=plan_store,
        actor=actor,
        actor_user_id=actor_user_id,
        catalog_query=catalog_query,
        inventory_query=inventory_query,
        org_settings_query=org_settings_query,
        pending_decomposition_store=pending_decomposition_store,
    )


async def resume_pending_decomposition_with_stock_choice(
    message: NormalizedMessage,
    actor_user_id: str,
    *,
    pending_decomposition_store: PendingDecompositionStore,
    plan_store: PlanStore,
    pipeline: UnderstandingPipeline,
    actor: ActorIdentity | None = None,
    catalog_query: MaterialCatalogQueryService | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
    org_settings_query: OrganizationSettingsQueryService | None = None,
) -> ReplySpec | None:
    """A tap on the over-stock usage choice (mirrors
    resume_pending_report_with_stock_choice): cap at available, treat as an
    arrival instead, or cancel this one segment -- the rest of the
    decomposition, if any, still continues either way."""
    if message.modality is not InputModality.INTERACTIVE:
        return None
    row_id = str(message.metadata.get("interactive_reply_id") or "")
    if row_id not in (_STOCK_CAP_ROW_ID, _STOCK_ARRIVAL_ROW_ID, _STOCK_CANCEL_ROW_ID):
        return None

    pending = await _pop_gate_pending(pending_decomposition_store, actor_user_id)
    if pending is None:
        return ReplySpec(text="That selection expired — please resend your request.")
    event = pending.pending_event
    assert event is not None

    if row_id == _STOCK_CANCEL_ROW_ID:
        # Drop just this one segment (never attempted) and continue with
        # whatever else was queued -- mirrors a decomposed segment that
        # turned out unroutable (build_plan_from_segments' own "skipped"
        # handling), not a whole-message failure.
        result = await _process_remaining_segments(
            segment_texts=pending.segments,
            built_events=list(pending.built_events),
            resolved=pending.resolved,
            pipeline=pipeline,
            expense_categories=list(pending.expense_categories) if pending.expense_categories else None,
            correlation_id=pending.resolved.correlation_id,
            source_message_id=pending.resolved.source_message_id,
            actor=actor,
            actor_user_id=actor_user_id,
            catalog_query=catalog_query,
            inventory_query=inventory_query,
            org_settings_query=org_settings_query,
            pending_decomposition_store=pending_decomposition_store,
        )
        if isinstance(result, ReplySpec):
            return result
        return await _finish_with_events(
            result, plan_store=plan_store, correlation_id=pending.resolved.correlation_id
        )

    if row_id == _STOCK_ARRIVAL_ROW_ID:
        event.event_type = CanonicalEventType.MATERIAL_RECEIPT_REQUESTED
    else:  # _STOCK_CAP_ROW_ID
        available = event.fields.get("available_stock")
        if available is not None:
            event.fields["quantity"] = available

    return await _continue_after_segment_resolved(
        event,
        pending,
        pipeline=pipeline,
        plan_store=plan_store,
        actor=actor,
        actor_user_id=actor_user_id,
        catalog_query=catalog_query,
        inventory_query=inventory_query,
        org_settings_query=org_settings_query,
        pending_decomposition_store=pending_decomposition_store,
    )
