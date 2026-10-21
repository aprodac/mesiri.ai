"""Slot-seeding helpers: the `_seed_*` / `_run_*_gate` functions that resolve
fields against repositories before a workflow's graph runs, plus the material/
unit/project/site/stock gates and the worker-promotion follow-up flow."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from backend.ports import ActorIdentity
from canonicalization.occurred_date import parse_stated_date, today_for
from channel.replies import (
    ReplySpec,
    render_audience_candidate_picker,
    render_audience_not_found_reply,
    render_material_create_offer,
    render_material_not_found_reply,
    render_material_picker,
    render_member_candidate_picker,
    render_member_create_offer,
    render_member_not_found_reply,
    render_no_projects_reply,
    render_petty_cash_recipient_not_found_reply,
    render_petty_cash_recipient_picker,
    render_project_picker,
    render_site_picker,
    render_unit_mismatch_reply,
    render_usage_exceeds_stock_reply,
)
from interactions.handler import InteractionHandled
from interactions.pending_report import PendingReportStore
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.canonical_event import IntentCompleteness as _IntentCompleteness
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import PlannerDecisionType, WorkflowKey
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from mesiri_contracts.common.ids import new_id as _new_id
from mesiri_contracts.common.storage import ObjectStoragePort
from runtime.activity_query import ActivityQueryService
from runtime.activity_search_service import ActivitySearchService
from runtime.dpr_request_query import DprRequestQueryService
from runtime.duplicate_expense_query import DuplicateExpenseQueryService
from runtime.entity_resolution.material_resolution import classify_material_matches
from runtime.entity_resolution.member_resolution import MemberNameResolutionService
from runtime.expense_query_service import ExpenseQueryService, resolve_date_range
from runtime.inbound_journey._shared import _log
from runtime.inbound_journey.reply import _safe
from runtime.inventory_query import MaterialInventoryQueryService
from runtime.labour_query_service import (
    LabourQueryService,
)
from runtime.labour_query_service import (
    resolve_date_range as resolve_labour_date_range,
)
from runtime.material_catalog_query import MaterialCatalogQueryService
from runtime.money_account_query import MoneyAccountQueryService
from runtime.org_settings_query import OrganizationSettingsQueryService
from runtime.petty_cash_query import PettyCashRecipientQueryService
from runtime.project_detail_query import ProjectDetailQueryService
from runtime.reversal_query import (
    ADVANCE_ACCOUNT_TYPE,
    ReversalTargetQueryService,
    ReversalTransferTarget,
    advance_holder_name,
)
from runtime.save_first import company_saves_first
from runtime.site_issue_query import SiteIssueTargetQueryService
from runtime.vendor_query import VendorQueryService
from runtime.workforce_query import WorkforceQueryService
from workflows import (
    WorkflowResumeResult,
    WorkflowResumeStatus,
    WorkflowRunResult,
    WorkflowRunStatus,
    WorkflowRuntime,
)
from workflows.site_update.nodes import UNCLEAR_TARGET_IS_NEW_KEY

_MATERIAL_EVENT_TYPES = frozenset(
    {
        CanonicalEventType.MATERIAL_RECEIPT_REQUESTED,
        CanonicalEventType.MATERIAL_USAGE_REQUESTED,
    }
)

# Both legs name a person: an issue credits their advance account, a return
# debits it -- so both need the recipient resolved before a draft is built.
_PETTY_CASH_EVENT_TYPES = frozenset(
    {
        CanonicalEventType.PETTY_CASH_ISSUE_REQUESTED,
        CanonicalEventType.PETTY_CASH_RETURN_REQUESTED,
    }
)

# Mirrors domains/organizations/settings.py's constant of the same name --
# duplicated as a literal rather than imported at module scope so this
# module keeps its "backend imports stay inside function bodies" shape (see
# runtime/material_catalog_query.py's deferred imports).
_WHATSAPP_MATERIAL_CREATE_ROLES = "whatsapp_material_create_roles"


async def _may_create_material(
    canonical_event: CanonicalEventV2,
    *,
    actor_role: str | None,
    org_settings_query: OrganizationSettingsQueryService | None,
) -> bool:
    """Whether this sender's role may add a catalog entry from WhatsApp, per
    the org's own whatsapp_material_create_roles setting (STA-139).

    Denies when there's no settings service wired or no role resolved rather
    than falling back to the spec default -- an unknown actor must not get a
    capability the org may not have granted. The service itself already
    degrades to the default on a lookup failure.
    """
    if org_settings_query is None or not actor_role:
        return False
    allowed = await org_settings_query.get(
        organization_id=canonical_event.organization_id,
        key=_WHATSAPP_MATERIAL_CREATE_ROLES,
    )
    from mesiri.domains.organizations.settings import role_allowed

    return role_allowed(actor_role, allowed)


async def _run_material_unit_gates(
    canonical_event: CanonicalEventV2,
    *,
    catalog_query: MaterialCatalogQueryService,
    pending_report_store: PendingReportStore,
    actor_user_id: str,
    actor_role: str | None = None,
    org_settings_query: OrganizationSettingsQueryService | None = None,
    ask_amount: bool = False,
) -> ReplySpec | None:
    """Resolve material_id/unit_id against materials_catalog/units_of_measure
    before the report can proceed to the project gate or planner.

    Mutates `canonical_event.fields` in place once resolved. Returns a
    ReplySpec (and holds the event in `pending_report_store`) when the report
    must pause for a clarifying tap -- ambiguous or unmatched material, or a
    reported unit that doesn't match the material's Stock Unit. Returns None
    once both resolve (or if there's nothing to resolve, e.g. no material_name
    at all -- canonicalization's own missing-field check already covers that
    case with CLARIFICATION_REQUIRED).

    Never raises: a lookup failure degrades to "let it through unresolved"
    (None) rather than dropping the reply entirely, same principle as the
    project-selection gate below.
    """
    # Function-level, mirroring _run_member_name_gate's own import of the
    # same vocabulary below.
    from workflows.entities import Ambiguous, Resolved

    material_id = canonical_event.fields.get("material_id")
    material: dict | None = None

    if material_id is None:
        name = canonical_event.fields.get("material_name")
        if not name:
            return None
        try:
            matches = await catalog_query.find_materials(
                organization_id=canonical_event.organization_id, name=name
            )
        except Exception:
            _log.exception(
                "material_gate.lookup_failed correlation_id=%s", canonical_event.correlation_id
            )
            return None

        # Phase 3 (ENTITY_RESOLUTION_PLAN.md §5): the same
        # Resolved/Ambiguous/Missing vocabulary _run_member_name_gate speaks,
        # over the catalog's own SQL matching rather than difflib scoring --
        # see runtime/entity_resolution/material_resolution.py for why
        # materials need only that half of the layer.
        outcome = classify_material_matches(str(name), matches)

        if isinstance(outcome, Resolved):
            # The full row, not just the outcome's id/name -- the unit gate
            # below needs default_unit_id, which the shared Resolved
            # deliberately does not carry (it is entity-agnostic).
            material = next(m for m in matches if str(m["id"]) == outcome.entity_id)
            canonical_event.fields["material_id"] = outcome.entity_id
        elif isinstance(outcome, Ambiguous):
            await pending_report_store.set_pending(user_id=actor_user_id, event=canonical_event)
            return render_material_picker(
                [(c.entity_id, c.display_name) for c in outcome.candidates]
            )
        else:
            # The reported name matched nothing. Offering to add it is
            # checked BEFORE the whole-catalog fallback picker below: once
            # the sender is allowed to create, "add Fevicol" is a far better
            # answer than a list of 20 unrelated materials to pick the wrong
            # one from.
            if await _may_create_material(
                canonical_event, actor_role=actor_role, org_settings_query=org_settings_query
            ):
                await pending_report_store.set_pending(
                    user_id=actor_user_id, event=canonical_event
                )
                return render_material_create_offer(str(name))

            # Not allowed to create -- keep the pre-STA-139 behaviour: offer
            # the org's active catalog so there's still something to pick
            # (the reported name may just be phrased differently), and only
            # dead-end when the catalog is genuinely empty.
            try:
                candidates = await catalog_query.list_active_materials(
                    organization_id=canonical_event.organization_id
                )
            except Exception:
                _log.exception(
                    "material_gate.lookup_failed correlation_id=%s",
                    canonical_event.correlation_id,
                )
                return None
            if not candidates:
                return ReplySpec(text=render_material_not_found_reply(str(name)))
            await pending_report_store.set_pending(user_id=actor_user_id, event=canonical_event)
            return render_material_picker([(str(c["id"]), c["name"]) for c in candidates])
    else:
        try:
            material = await catalog_query.get_material(
                organization_id=canonical_event.organization_id, material_id=material_id
            )
        except Exception:
            _log.exception(
                "material_gate.lookup_failed correlation_id=%s", canonical_event.correlation_id
            )
            return None
        if material is None or not material["is_active"]:
            return ReplySpec(
                text="That material is no longer available — please resend your report."
            )

    stock_unit_id = material.get("default_unit_id")
    if stock_unit_id is None:
        # No Stock Unit configured on this material yet -- nothing to enforce
        # against (pre-migration catalog entries, or a not-yet-fully-set-up
        # material). Let it through rather than blocking every report.
        return None

    unit_id = canonical_event.fields.get("unit_id")
    if unit_id is not None:
        return None  # already resolved (e.g. a resumed "yes" tap)

    unit_text = canonical_event.fields.get("unit")
    if not unit_text:
        # Omitted entirely -- default to the material's Stock Unit and let the
        # normal confirmation prompt surface it as a field the user can still
        # reject via "NO", rather than adding another clarifying turn.
        canonical_event.fields["unit_id"] = str(stock_unit_id)
        return None

    try:
        resolved_unit = await catalog_query.resolve_unit(unit_text)
    except Exception:
        _log.exception("unit_gate.lookup_failed correlation_id=%s", canonical_event.correlation_id)
        return None

    if resolved_unit is not None and str(resolved_unit["id"]) == str(stock_unit_id):
        canonical_event.fields["unit_id"] = str(stock_unit_id)
        return None

    # Either the reported unit text didn't resolve to anything, or it resolved
    # to a real-but-different unit -- both are a Stock Unit mismatch. Ask,
    # scoped to this material's one valid unit only (never a global picker
    # that would let an incompatible unit through).
    try:
        stock_unit = await catalog_query.get_unit(str(stock_unit_id))
    except Exception:
        _log.exception("unit_gate.lookup_failed correlation_id=%s", canonical_event.correlation_id)
        return None
    if ask_amount:
        unit_display = stock_unit["display_name"] if stock_unit else "its stock unit"
        # WA-39, under the agent: "40 bags sand" against sand counted in m³.
        # Yes ("record this as m³?") would save 40 m³ and No dropped the
        # entry, so nothing is held: the model is told the fact and asks for
        # the amount in the stock unit; the answer comes back as a new save.
        qty = canonical_event.fields.get("quantity")
        said = " ".join(p for p in (str(qty) if qty is not None else "", str(unit_text)) if p)
        return ReplySpec(
            text=(
                f"Not saved yet: {material['name']} is counted in {unit_display} here, so "
                f"{said} can't be saved as it is. How much is that in {unit_display}?"
            )
        )
    await pending_report_store.set_pending(user_id=actor_user_id, event=canonical_event)
    return render_unit_mismatch_reply(
        material_name=material["name"],
        unit_id=str(stock_unit_id),
        unit_display=stock_unit["display_name"] if stock_unit else "the correct unit",
    )


def _actor_may_create_user(actor_role: str | None) -> bool:
    """Whether this sender's role may create a new user, per CREATE_USER's
    own `allowed_roles` declaration in the registry (ENTITY_RESOLUTION_PLAN.md
    ADR-E5). A lookup, not a branch -- if CREATE_USER's allowed_roles changes,
    or a different workflow ever becomes the USER provider, this needs no
    edit. Reuses `allowed_roles` for the purpose it was built for (discovery/
    offer filtering); this is not a promotion of the field to an enforcement
    gate -- see registry.py's field comment, and
    ENTITY_RESOLUTION_PLAN.md §8.2's objection to doing that."""
    if not actor_role:
        return False
    from workflows.entities import EntityType
    from workflows.registry import get_definition, workflow_that_provides

    provider_key = workflow_that_provides(EntityType.USER)
    if provider_key is None:
        return False
    definition = get_definition(provider_key)
    if definition is None or definition.allowed_roles is None:
        return True
    return actor_role.upper() in definition.allowed_roles


async def _run_member_name_gate(
    canonical_event: CanonicalEventV2,
    *,
    member_resolver: MemberNameResolutionService,
    pending_report_store: PendingReportStore,
    actor_user_id: str,
    actor_role: str | None,
) -> ReplySpec | None:
    """Resolve ADD_PROJECT_MEMBER's member_name against the org's real active
    users BEFORE a draft is ever built (ENTITY_RESOLUTION_PLAN.md ADR-E1) --
    today the name is only resolved by the backend Handler at execution time
    (application/projects/handlers.py), so a user confirms a draft that was
    never capable of succeeding: "Yes" -> "couldn't find an active user
    named X." That backend resolver is untouched and stays authoritative at
    execution (ADR-E2) -- this gate's only job is to catch the two cases
    that would otherwise dead-end, before confirmation:

    - Resolved: an exact match exists. Falls through with `member_name`
      untouched -- the backend's own exact-match resolver will find the
      same row again at execution, so nothing needs to be written here.
    - Ambiguous: one or more near-matches (e.g. a Malayalam transliteration
      like "Hysam" against a real "Hisham" -- the live bug this fixes), none
      certain enough to use silently. Holds the event and offers a tappable
      picker; see runtime/entity_resolution/member_resolution.py's module
      docstring for why this uses real near-match scoring where
      workforce/matching.py's match_worker explicitly does not.
    - Missing: nothing matched. Offers to create the user inline (chaining
      into a real CREATE_USER workflow, then resuming this request) when the
      sender's role allows it (ADR-E5); otherwise a plain "ask your admin"
      reply, same as the disallowed-role path for material creation.

    Never raises: a lookup failure degrades to "let it through unresolved"
    (None), same posture as every other gate in this module -- the backend's
    own resolver still runs at execution and will reject honestly if the
    name really doesn't exist.
    """
    if canonical_event.event_type is not CanonicalEventType.ADD_PROJECT_MEMBER_REQUESTED:
        return None
    name_hint = canonical_event.fields.get("member_name")
    if not name_hint:
        return None

    from workflows.entities import Ambiguous, Missing, Resolved

    try:
        outcome = await member_resolver.resolve(
            organization_id=canonical_event.organization_id, name_hint=str(name_hint)
        )
    except Exception:
        _log.exception(
            "member_name_gate.lookup_failed correlation_id=%s", canonical_event.correlation_id
        )
        return None

    if isinstance(outcome, Resolved):
        return None
    if isinstance(outcome, Ambiguous):
        await pending_report_store.set_pending(user_id=actor_user_id, event=canonical_event)
        return render_member_candidate_picker(str(name_hint), outcome.candidates)
    assert isinstance(outcome, Missing)
    if _actor_may_create_user(actor_role):
        await pending_report_store.set_pending(user_id=actor_user_id, event=canonical_event)
        return render_member_create_offer(str(name_hint))
    return ReplySpec(text=render_member_not_found_reply(str(name_hint)))


#: Marks which audience name the picker currently on screen is about, so the
#: resume leg can patch the right entry without re-deriving it. Only ever
#: present on a held event -- cleared before the automation is drafted, so it
#: never reaches CreateAutomationCommand.
AUDIENCE_PENDING_NAME_FIELD = "_audience_pending_name"


async def _run_audience_name_gate(
    canonical_event: CanonicalEventV2,
    *,
    member_resolver: MemberNameResolutionService,
    pending_report_store: PendingReportStore,
    actor_user_id: str,
) -> ReplySpec | None:
    """Resolve an automation's `audience_names` against real active users
    BEFORE the draft -- Phase 4 of ENTITY_RESOLUTION_PLAN.md §5, same ADR-E1
    move as the member and petty-cash gates.

    Until now these names travelled untouched all the way to
    application/automations/handlers.py, which resolved them via
    `find_by_full_name_active` (exact) at persist time and rejected the whole
    command listing any it missed. So "remind Ilan and Hysam every Monday"
    against an org whose real user is "Hisham" showed a confirmation, took a
    Yes, and only then answered "couldn't find: Hysam" -- another doomed
    confirmation, and the §1 bug once more.

    Resolves in order and stops at the first name that isn't settled, asking
    about that one alone; answering it re-enters this gate, which asks about
    the next or lets the automation through. One question per unknown name
    rather than one summary of all of them: the summary would be fewer
    messages but would send the user back to retyping the whole sentence,
    and a name they can tap is worth more on a phone at a site than a name
    they have to spell correctly on the second attempt.

    Names that DO resolve are rewritten to their exact stored spelling, so
    the Handler's own exact lookup finds the same rows at persist time.

    Never raises: a lookup failure degrades to letting it through
    unresolved, same posture as every other gate here -- the Handler still
    rejects honestly if a name really is unknown.
    """
    if canonical_event.event_type is not CanonicalEventType.AUTOMATION_SETUP_REQUESTED:
        return None
    names = canonical_event.fields.get("audience_names")
    if not isinstance(names, list) or not names:
        return None

    from workflows.entities import Ambiguous, Missing, Resolved

    resolved: list[str] = []
    for index, raw in enumerate(names):
        name = str(raw or "").strip()
        if not name:
            continue
        try:
            outcome = await member_resolver.resolve(
                organization_id=canonical_event.organization_id, name_hint=name
            )
        except Exception:
            _log.exception(
                "audience_name_gate.lookup_failed correlation_id=%s",
                canonical_event.correlation_id,
            )
            return None

        if isinstance(outcome, Resolved):
            resolved.append(outcome.display_name)
            continue

        # Unsettled. Persist what resolved so far so answering this question
        # doesn't re-ask about the names already agreed on.
        canonical_event.fields["audience_names"] = [
            *resolved,
            name,
            *[str(n) for n in names[index + 1 :]],
        ]
        canonical_event.fields[AUDIENCE_PENDING_NAME_FIELD] = name

        if isinstance(outcome, Ambiguous):
            await pending_report_store.set_pending(
                user_id=actor_user_id, event=canonical_event
            )
            return render_audience_candidate_picker(name, outcome.candidates)

        assert isinstance(outcome, Missing)
        canonical_event.fields.pop(AUDIENCE_PENDING_NAME_FIELD, None)
        return ReplySpec(text=render_audience_not_found_reply(name))

    canonical_event.fields["audience_names"] = resolved
    canonical_event.fields.pop(AUDIENCE_PENDING_NAME_FIELD, None)
    return None


async def _run_petty_cash_recipient_gate(
    canonical_event: CanonicalEventV2,
    *,
    member_resolver: MemberNameResolutionService,
    pending_report_store: PendingReportStore,
    actor_user_id: str,
) -> ReplySpec | None:
    """Resolve PETTY_CASH's `recipient_name` against the org's real active
    users BEFORE a draft is built -- Phase 4 of ENTITY_RESOLUTION_PLAN.md §5,
    and the same ADR-E1 move _run_member_name_gate makes for
    ADD_PROJECT_MEMBER.

    Until now the only lookup was `find_by_full_name_active` (exact,
    case-insensitive) inside _seed_petty_cash_recipient. A near-miss --
    exactly §1's ഹൈസം/Hysam against a real "Hisham" -- resolved to nothing,
    so `recipient_account_id` stayed unset, build_draft produced a draft
    missing that leg of the transfer, and transfer_validation.py rejected it
    *after* the user had already confirmed. A doomed confirmation, for the
    one workflow where the thing being confirmed is money leaving an
    account.

    - Resolved: rewrite `recipient_name` to that user's exact stored name so
      _seed_petty_cash_recipient's own exact lookup finds the same row, then
      fall through unchanged.
    - Ambiguous: hold the event and ask, never auto-pick -- a wrong pick
      credits the wrong person's advance account.
    - Missing: stop honestly here rather than building a draft that cannot
      succeed. Deliberately NOT an offer to create the user the way the
      member gate's Missing case is: issuing cash to someone is a poor
      moment to also be creating their account, and unlike a project
      membership there is no harmless "add them, then continue" -- the
      created user would immediately be the destination of a money movement.

    Never raises: a lookup failure degrades to letting it through
    unresolved, same posture as every other gate in this module -- the
    pre-existing validation still rejects honestly downstream.
    """
    if canonical_event.event_type not in _PETTY_CASH_EVENT_TYPES:
        return None
    name_hint = canonical_event.fields.get("recipient_name")
    if not name_hint:
        return None

    from workflows.entities import Ambiguous, Missing, Resolved

    try:
        outcome = await member_resolver.resolve(
            organization_id=canonical_event.organization_id, name_hint=str(name_hint)
        )
    except Exception:
        _log.exception(
            "petty_cash_recipient_gate.lookup_failed correlation_id=%s",
            canonical_event.correlation_id,
        )
        return None

    if isinstance(outcome, Resolved):
        canonical_event.fields["recipient_name"] = outcome.display_name
        return None
    if isinstance(outcome, Ambiguous):
        await pending_report_store.set_pending(user_id=actor_user_id, event=canonical_event)
        return render_petty_cash_recipient_picker(str(name_hint), outcome.candidates)
    assert isinstance(outcome, Missing)
    return ReplySpec(text=render_petty_cash_recipient_not_found_reply(str(name_hint)))


async def _run_project_gate(
    canonical_event: CanonicalEventV2,
    *,
    actor: ActorIdentity | None,
    actor_user_id: str,
    pending_report_store: PendingReportStore,
) -> ReplySpec | None:
    """Ask which project a report belongs to, when it's otherwise ACTIONABLE
    but has no project_id -- factored out of process_inbound_message so the
    material/unit resume functions below can re-run this same gate after
    they resolve their own field, instead of assuming project must already
    be fine (see module docstring on gate re-running)."""
    if canonical_event.completeness is not _IntentCompleteness.ACTIONABLE:
        return None
    if canonical_event.project_id is not None:
        return None
    try:
        if actor is not None and actor.projects:
            await pending_report_store.set_pending(user_id=actor_user_id, event=canonical_event)
            return render_project_picker([(p.id, p.name, p.location) for p in actor.projects])
        return ReplySpec(text=render_no_projects_reply())
    except Exception:
        # Must fail CLOSED, not open: project_id is required by domain
        # validation (validation.py's "project is not resolved"), unlike the
        # material/unit gates above where letting an unresolved field through
        # is safe. Silently proceeding here would let the user tap Yes on a
        # confirmation that's guaranteed to fail two steps later instead of
        # failing honestly right now.
        _log.exception(
            "project_selection_gate.failed correlation_id=%s", canonical_event.correlation_id
        )
        return ReplySpec(
            text="Sorry, something went wrong picking your project — please resend your report."
        )


async def _run_site_gate(
    canonical_event: CanonicalEventV2,
    *,
    actor: ActorIdentity | None,
    actor_user_id: str,
    pending_report_store: PendingReportStore,
    allow_combined: bool,
) -> ReplySpec | None:
    """Ask which site a report/query belongs to, once its project is settled
    but site_id still isn't and the project has more than one site.

    Mirrors _run_project_gate's shape: a single site under the resolved
    project auto-resolves (no ask, no picker) the same way a single
    authorized project already does in context/resolver.py; zero sites lets
    the report through site-less rather than blocking on nothing to choose
    from. Unlike project, site_id is not required by domain validation
    (domains/materials/validation.py never checks it) -- so a failure here
    fails OPEN (let it through unresolved), the same safe degrade the
    material/unit gates use, not the fail-closed project gate needs.

    ``allow_combined`` is only ever True for an inventory query -- asking
    "how much cement" can meaningfully span every site, so its picker offers
    an "All Sites Combined" row; a material report being recorded always
    has to land on one real site, so recording never offers that option."""
    if canonical_event.completeness is not _IntentCompleteness.ACTIONABLE:
        return None
    if canonical_event.site_id is not None:
        return None
    if canonical_event.project_id is None:
        return None  # site only makes sense once a project is settled
    if actor is None:
        return None
    try:
        sites = [s for s in actor.sites if s.project_id == canonical_event.project_id]
        if not sites:
            return None
        if len(sites) == 1:
            canonical_event.site_id = sites[0].id
            return None
        await pending_report_store.set_pending(user_id=actor_user_id, event=canonical_event)
        return render_site_picker(
            [(s.id, s.name) for s in sites], allow_combined=allow_combined
        )
    except Exception:
        _log.exception(
            "site_selection_gate.failed correlation_id=%s", canonical_event.correlation_id
        )
        return None


async def _run_stock_gate(
    canonical_event: CanonicalEventV2,
    *,
    pending_report_store: PendingReportStore,
    actor_user_id: str,
    org_settings_query: OrganizationSettingsQueryService | None = None,
) -> ReplySpec | None:
    """Block a usage report whose quantity exceeds what's in stock, instead
    of the old cosmetic-only warning (workflows/material/nodes.py's
    _low_stock_warning showed "Only X in stock" on the confirmation prompt
    but a Yes tap still saved the full over-limit quantity, driving stock
    negative -- the real-world bug this fixes).

    Must run after _inject_inventory_context has populated available_stock
    on the event's fields, and after every other gate (material/unit/
    project/site) has already resolved -- mirrors their "hold + ask" shape,
    offering three explicit choices (cap at available / this was actually an
    arrival / cancel) rather than guessing which one the user meant. Returns
    None when there's nothing to check (not a usage report, not yet
    actionable, or no stock figure available to compare against) or when the
    requested quantity is within stock.

    WA-03: a company that saves first (the default) is not asked: the usage
    is saved as a draft, flagged on the DPR (BE-12) and the saved reply says
    so. `org_settings_query` None counts as the default.
    """
    if canonical_event.event_type is not CanonicalEventType.MATERIAL_USAGE_REQUESTED:
        return None
    if canonical_event.completeness is not _IntentCompleteness.ACTIONABLE:
        return None
    available = canonical_event.fields.get("available_stock")
    if available is None:
        return None
    try:
        requested = float(canonical_event.fields.get("quantity"))
        available = float(available)
    except (TypeError, ValueError):
        return None
    if requested <= available:
        return None
    if await company_saves_first(org_settings_query, canonical_event.organization_id):
        return None

    await pending_report_store.set_pending(user_id=actor_user_id, event=canonical_event)
    return render_usage_exceeds_stock_reply(
        material_name=str(canonical_event.fields.get("material_name") or "this material"),
        unit=str(canonical_event.fields.get("unit") or ""),
        requested=requested,
        available=available,
    )


async def _inject_inventory_context(
    event: CanonicalEventV2, inventory_query: MaterialInventoryQueryService | None
) -> None:
    """Populate inventory_levels (for INVENTORY_QUERY_ASKED) / available_stock
    (for MATERIAL_USAGE_REQUESTED's low-stock warning) on the event's fields.

    Must only run after every material/unit/project/site gate has already
    resolved project_id/site_id -- project_id/site_id can still change up to
    that point, and computing this any earlier would silently answer for
    the wrong scope once the user picked a different project/site than
    whatever was resolved at canonicalization time. Called from both the
    first-pass journey (inline, right before the planner stage) and
    _plan_and_run (used by every resume_pending_report_with_* function),
    since the first pass has its own inline planner/workflow telemetry and
    doesn't route through _plan_and_run."""
    if inventory_query is None:
        return
    if event.event_type is CanonicalEventType.INVENTORY_QUERY_ASKED:
        event.fields["inventory_levels"] = await inventory_query.query(
            organization_id=event.organization_id,
            project_id=event.project_id,
            site_id=event.site_id,
            material_name=event.fields.get("material_name"),
        )
    elif (
        event.event_type is CanonicalEventType.MATERIAL_USAGE_REQUESTED
        and event.fields.get("material_name")
    ):
        # A usage report's quantity can't be validated against stock until
        # the confirmation prompt itself (the Domain layer only checks
        # quantity > 0, never sufficiency -- see domains/materials/
        # validation.py). This hint lets workflows/material/nodes.py warn
        # "only X in stock" without querying the database itself.
        levels = await inventory_query.query(
            organization_id=event.organization_id,
            project_id=event.project_id,
            site_id=event.site_id,
            material_name=event.fields.get("material_name"),
        )
        if levels:
            event.fields["available_stock"] = levels[0]["current_stock"]


async def _seed_account_candidates(
    event: CanonicalEventV2,
    decision: PlannerDecisionV2,
    money_account_query: MoneyAccountQueryService | None,
    actor: ActorIdentity | None,
) -> None:
    """Feed the org's eligible money accounts into the event's fields so
    expense_capture's resolve_account node (Finance Module Slice 1) and
    transfer's resolve_from_account/resolve_to_account nodes (Slice 3) can
    decide whether to auto-fill, ask "which account?", or proceed unset --
    a node must never query a repository itself (see workflows/runtime.py's
    docstring), so this is the seeding point, same principle as
    _inject_inventory_context above. Only ever runs for EXPENSE_SUBMIT and
    TRANSFER; every other workflow key's fields are left untouched.

    TRANSFER additionally gets `created_by_role` seeded here -- it travels
    through the draft the same way amount/from/to do, so
    application/finance/transfer_validation.py can enforce who may transfer
    money without threading actor identity through the ExecutionDispatcher
    protocol for every domain (see transfer_commands.py's docstring).
    """
    if money_account_query is None or actor is None or not actor.organization_id:
        return
    if decision.workflow_key not in (
        WorkflowKey.EXPENSE_SUBMIT,
        WorkflowKey.TRANSFER,
        WorkflowKey.PETTY_CASH,
    ):
        return
    accounts = await money_account_query.list_accounts(
        organization_id=actor.organization_id, created_by=actor.user_id
    )
    event.fields["account_candidates"] = [
        {"id": str(account.id), "name": account.name} for account in accounts
    ]
    if decision.workflow_key in (WorkflowKey.TRANSFER, WorkflowKey.PETTY_CASH):
        event.fields["created_by_role"] = actor.role


async def _seed_petty_cash_recipient(
    event: CanonicalEventV2,
    decision: PlannerDecisionV2,
    petty_cash_query: PettyCashRecipientQueryService | None,
    actor: ActorIdentity | None,
) -> None:
    """Resolve `recipient_name` (e.g. "Alan") into their employee-advance
    money account, auto-created on first issuance -- Finance Module Slice 5.
    A node must never query a repository itself, so this is the seeding
    point, same principle as _seed_account_candidates above. Only ever runs
    for PETTY_CASH; an unresolved recipient (no matching active user) simply
    leaves `recipient_account_id` unset -- workflows/petty_cash/nodes.py's
    build_draft then produces a draft missing that leg of the transfer,
    which the existing transfer_validation.py rejects rather than this
    seeding step guessing who was meant."""
    if petty_cash_query is None or actor is None or not actor.organization_id:
        return
    if decision.workflow_key is not WorkflowKey.PETTY_CASH:
        return
    recipient_name = event.fields.get("recipient_name")
    if not recipient_name:
        return
    account = await petty_cash_query.resolve_or_create_advance_account(
        organization_id=actor.organization_id,
        recipient_name=str(recipient_name),
        created_by=actor.user_id,
    )
    if account is not None:
        event.fields["recipient_account_id"] = str(account.id)
        event.fields["recipient_account_name"] = account.name


def _apply_transfer_target(event: CanonicalEventV2, target: ReversalTransferTarget) -> None:
    """Seed a resolved `transfer` row onto the event, letting the ROW decide
    whether it was really a petty cash movement.

    Petty cash writes the same `transfer` row a plain transfer does (see
    find_latest_reversible_petty_cash), so "reverse my last transfer" can
    legitimately land on an advance. Rather than treat that as the user's
    mistake, the target_kind is corrected to match what was actually found,
    which is what stops the confirmation reading "Reverse transfer •
    Company Account -> Alan Usman — Petty Cash" for something the user
    thinks of as "the ₹20,000 I gave Alan".

    Direction is derived rather than stored: money moving INTO an advance
    account is an issuance, out of it a return."""
    event.fields["money_transaction_id"] = target["money_transaction_id"]
    event.fields["reversal_amount"] = target["amount"]
    event.fields["reversal_from_account_name"] = target["from_account_name"]
    event.fields["reversal_to_account_name"] = target["to_account_name"]

    to_is_advance = target.get("to_account_type") == ADVANCE_ACCOUNT_TYPE
    from_is_advance = target.get("from_account_type") == ADVANCE_ACCOUNT_TYPE
    if not (to_is_advance or from_is_advance):
        return

    event.fields["target_kind"] = "petty_cash"
    # An advance-to-advance row has no meaningful direction; treating it as
    # an issuance to the receiving side is the reading that names the person
    # who ended up holding the money.
    event.fields["reversal_petty_cash_direction"] = "issue" if to_is_advance else "return"
    event.fields["reversal_petty_cash_holder"] = advance_holder_name(
        target["to_account_name"] if to_is_advance else target["from_account_name"]
    )


async def _seed_reversal_target(
    event: CanonicalEventV2,
    decision: PlannerDecisionV2,
    reversal_query: ReversalTargetQueryService | None,
    actor: ActorIdentity | None,
    *,
    remembered_activity_id: str | None = None,
) -> None:
    """Resolve "the most recent expense/transfer" (or, per ADR-D15, "the
    Activity this conversation just touched") into a concrete id --
    Finance Module Slice 7 + Daily Reporting's undo. A node must never
    query a repository itself, so this is the seeding point, same
    principle as _seed_account_candidates above. Only ever runs for
    REVERSE; finding nothing simply leaves the target id fields unset --
    workflows/reverse/nodes.py's build_draft then completes with a
    "nothing to reverse" reply instead of a draft (see that module's
    docstring and `WorkflowDefinition.allows_completion_without_draft` in
    workflows/registry.py).

    #6 Undo: a bare "undo"/"delete that" (mesiri_ai.undo_classifier) produces
    a REVERSAL event with no target_kind at all -- canonicalization/
    mapping.py defaults that specific case (target_kind absent, not merely
    unrecognized) to CanonicalEventType.EXPENSE_REVERSAL_REQUESTED purely so
    routing has a type to dispatch on; the REAL kind is resolved here, by
    reversal_query.find_latest_of_either_kind, and written back onto
    target_kind so workflows/reverse/nodes.py's confirmation prompt and
    "nothing to reverse" message render for whichever kind actually won.
    Deliberately scoped to expense/transfer only -- a bare "undo" never
    arbitrates in an Activity too, since that would need a materially
    different signal (same-session memory, not recency) than the one this
    arbitration already uses; an explicit "undo my last site update" is
    required to reach the activity branch below."""
    if reversal_query is None or actor is None or not actor.organization_id:
        return
    if decision.workflow_key is not WorkflowKey.REVERSE:
        return
    event.fields["created_by_role"] = actor.role
    target_kind = str(event.fields.get("target_kind", "")).strip().lower()

    if target_kind == "activity":
        activity = await reversal_query.find_latest_activity(
            organization_id=actor.organization_id,
            reported_by_user_id=actor.user_id,
            remembered_activity_id=remembered_activity_id,
        )
        if activity is not None:
            event.fields["activity_id"] = activity["activity_id"]
            summary_bits = [b for b in (activity.get("work_type"), activity.get("narrative")) if b]
            if summary_bits:
                event.fields["reversal_activity_summary"] = " — ".join(summary_bits)
            event.fields["reversal_occurred_date"] = activity["activity_date"]
        return

    if target_kind == "attendance":
        attendance = await reversal_query.find_latest_attendance(
            organization_id=actor.organization_id,
            reported_by_user_id=actor.user_id,
        )
        if attendance is not None:
            event.fields["attendance_report_id"] = attendance["attendance_report_id"]
            event.fields["reversal_occurred_date"] = attendance["occurred_date"]
            event.fields["reversal_attendance_headcount"] = attendance["total_headcount"]
            event.fields["reversal_amount"] = attendance["total_cost"]
            # The site is the point: this undo exists for a report filed
            # against the wrong one, so the confirmation has to name it.
            event.fields["reversal_attendance_site"] = (
                attendance.get("site_name") or attendance.get("project_name") or "your site"
            )
        return

    if not target_kind:
        found = await reversal_query.find_latest_of_either_kind(
            organization_id=actor.organization_id,
            project_id=event.project_id,
            site_id=event.site_id,
        )
        if found is None:
            # Deliberately leave target_kind unset (not "expense" or
            # "transfer") -- workflows/reverse/nodes.py's build_draft falls
            # through to its generic "Nothing found to reverse." message for
            # any unrecognized target_kind, which is the honest answer here:
            # neither kind had anything, so naming one would be misleading.
            return
        target_kind, target = found
        event.fields["target_kind"] = target_kind
        if target_kind == "transfer":
            # May re-label itself petty_cash -- see _apply_transfer_target.
            _apply_transfer_target(event, target)
        else:
            event.fields["expense_id"] = target["expense_id"]
            event.fields["reversal_amount"] = target["amount"]
            event.fields["reversal_description"] = target["description"]
            event.fields["reversal_occurred_date"] = target["occurred_date"]
        return

    if target_kind in ("transfer", "petty_cash"):
        transfer = (
            await reversal_query.find_latest_petty_cash(organization_id=actor.organization_id)
            if target_kind == "petty_cash"
            else await reversal_query.find_latest_transfer(organization_id=actor.organization_id)
        )
        if transfer is not None:
            _apply_transfer_target(event, transfer)
        return

    expense = await reversal_query.find_latest_expense(
        organization_id=actor.organization_id, project_id=event.project_id, site_id=event.site_id
    )
    if expense is not None:
        event.fields["expense_id"] = expense["expense_id"]
        event.fields["reversal_amount"] = expense["amount"]
        event.fields["reversal_description"] = expense["description"]
        event.fields["reversal_occurred_date"] = expense["occurred_date"]


#: An issue that has not yet reached a terminal state.
_LIVE_STATUSES = ("OPEN", "ACKNOWLEDGED")

#: Which statuses each close-out action may target when looking for "the
#: issue the user means." Must stay in step with progress_execution.py's
#: _ALLOWED_CURRENT_STATUS_BY_ACTION, which re-checks the same rule against
#: the row's CURRENT status at confirm time -- this one decides which issue
#: to *offer*, that one decides whether the transition is still legal once
#: the user replies YES. They are deliberately separate literals in separate
#: layers (a read service must not import the executor), so a drift between
#: them shows up as "nothing to reopen" rather than as a bad write.
_CLOSE_TARGET_STATUSES: dict[str, tuple[str, ...]] = {
    # Mirrors progress.py's acknowledge_issue WHERE clause.
    "acknowledge": ("OPEN",),
    "resolve": _LIVE_STATUSES,
    "wont_fix": _LIVE_STATUSES,
    "cancel": _LIVE_STATUSES,
    # The only action that looks at closed issues -- and the only one that
    # can pick up an ACKNOWLEDGED one from the other direction. CANCELLED is
    # excluded: a withdrawn report is not reopenable, it is re-reportable.
    "reopen": ("ACKNOWLEDGED", "RESOLVED", "WONT_FIX"),
}


async def _seed_site_issue_close_target(
    event: CanonicalEventV2,
    decision: PlannerDecisionV2,
    site_issue_query: SiteIssueTargetQueryService | None,
    actor: ActorIdentity | None,
) -> None:
    """Resolve "my last reported issue" into a concrete site_issue_id --
    same "most recent record of a kind" pattern as _seed_reversal_target
    above, with `action` playing the role target_kind plays there: it picks
    both which statuses are eligible (_CLOSE_TARGET_STATUSES) and, for
    `reopen`, what "most recent" even means. Only ever runs for
    SITE_ISSUE_CLOSE; finding nothing simply leaves site_issue_id unset --
    workflows/site_issue_close/nodes.py's build_draft then completes with a
    "nothing to close" reply instead of a draft (see that module's
    docstring and `WorkflowDefinition.allows_completion_without_draft` in
    workflows/registry.py)."""
    if site_issue_query is None or actor is None or not actor.organization_id:
        return
    if decision.workflow_key is not WorkflowKey.SITE_ISSUE_CLOSE:
        return

    action = str(event.fields.get("action", "")).strip().lower()
    statuses = _CLOSE_TARGET_STATUSES.get(action, _LIVE_STATUSES)
    target = await site_issue_query.find_latest(
        organization_id=actor.organization_id,
        project_id=event.project_id,
        site_id=event.site_id,
        statuses=statuses,
        # "Reopen that" means the issue most recently closed, not the one
        # most recently reported -- see find_latest_by_status.
        by_transition_time=action == "reopen",
    )
    if target is None:
        return
    event.fields["site_issue_id"] = target["site_issue_id"]
    event.fields["site_issue_type"] = target["issue_type"]
    event.fields["site_issue_severity"] = target["severity"]
    event.fields["site_issue_narrative"] = target["narrative"]


def _seed_account_admin_role(event: CanonicalEventV2, decision: PlannerDecisionV2, actor: ActorIdentity | None) -> None:
    """Feed the sender's role into the draft the same way
    _seed_account_candidates does for TRANSFER/PETTY_CASH -- defense-in-depth
    for application/finance/validation.py's role check. Not the primary
    gate: _account_admin_role_denied_reply (called before workflow_runtime.
    start(), see process_inbound_message) already refuses a disallowed role
    before a draft is ever built, so this only matters if that earlier gate
    is ever bypassed. Only ever runs for ACCOUNT_ADMIN. No I/O -- actor.role
    is already resolved, same as _seed_account_candidates's created_by_role."""
    if actor is None or decision.workflow_key is not WorkflowKey.ACCOUNT_ADMIN:
        return
    event.fields["created_by_role"] = actor.role


def _seed_project_create_role(
    event: CanonicalEventV2, decision: PlannerDecisionV2, actor: ActorIdentity | None
) -> None:
    """Feed the sender's role into the draft, same reasoning as
    _seed_account_admin_role -- defense-in-depth for
    application/projects/create_validation.py's, create_site_validation.
    py's, add_member_validation.py's, and application/users/
    create_user_validation.py's role checks (PROJECT_CREATE, SITE_CREATE,
    ADD_PROJECT_MEMBER, and CREATE_USER all share it, same as the gate
    below). Not the primary gate: the _PROJECT_CREATE_ROLES check below
    (before workflow_runtime.start()) already refuses a disallowed role
    before a draft is ever built."""
    if actor is None or decision.workflow_key not in (
        WorkflowKey.PROJECT_CREATE,
        WorkflowKey.SITE_CREATE,
        WorkflowKey.ADD_PROJECT_MEMBER,
        WorkflowKey.CREATE_USER,
    ):
        return
    event.fields["created_by_role"] = actor.role


def _seed_automation_setup_role(
    event: CanonicalEventV2, decision: PlannerDecisionV2, actor: ActorIdentity | None
) -> None:
    """Feed the sender's role into the draft, same reasoning as
    _seed_project_create_role -- defense-in-depth for
    application/automations/create_validation.py's role check (an
    automation targeting anyone other than SELF requires ADMIN/
    PROJECT_MANAGER). Not the primary gate: the audience-aware role check
    in process.py (before workflow_runtime.start()) already refuses a
    disallowed role before a draft is ever built for a non-SELF audience."""
    if actor is None or decision.workflow_key is not WorkflowKey.AUTOMATION_SETUP:
        return
    event.fields["created_by_role"] = actor.role


async def _seed_labour_query(
    event: CanonicalEventV2,
    decision: PlannerDecisionV2,
    labour_query_service: LabourQueryService | None,
    actor: ActorIdentity | None,
    timezone_name: str | None,
) -> None:
    """Answer the attendance question before the graph runs -- a node must
    never query a repository itself, same principle as
    _seed_finance_query_context above. Only ever runs for LABOUR_QUERY.

    The date range defaults to *today* rather than expense's "this month":
    the question a supervisor actually asks is "how many workers today", and
    attendance is a daily rhythm in a way spending is not.
    """
    if labour_query_service is None or actor is None or not actor.organization_id:
        return
    if decision.workflow_key is not WorkflowKey.LABOUR_QUERY:
        return

    # The sender's today, not the server's -- same UTC-vs-site-timezone trap
    # canonicalization/occurred_date.py exists to close. Asking "how many
    # workers today" at 2am in India must not answer for yesterday. The
    # timezone comes from resolved context (ActorIdentity doesn't carry one).
    today = today_for(timezone_name)
    start_date, end_date, date_range_label = resolve_labour_date_range(
        event.fields.get("date_range"), today=today
    )
    results = await labour_query_service.summarize_attendance(
        organization_id=actor.organization_id,
        project_id=event.project_id,
        site_id=event.site_id,
        start_date=start_date,
        end_date=end_date,
        trade=event.fields.get("trade"),
    )
    results["date_range_label"] = date_range_label
    event.fields["labour_results"] = results


async def _seed_activity_search(
    event: CanonicalEventV2,
    decision: PlannerDecisionV2,
    activity_search_service: ActivitySearchService | None,
    actor: ActorIdentity | None,
    timezone_name: str | None,
) -> None:
    """Answer #17 "what did I log / any open issues" before the graph runs --
    same shape and reasoning as _seed_labour_query above. Only ever runs for
    ACTIVITY_QUERY.

    Defaults to *today*, same reasoning as labour_query's default: the
    question a supervisor asks about their own site log is almost always
    about the current day, not a rolling window.
    """
    if activity_search_service is None or actor is None or not actor.organization_id:
        return
    if decision.workflow_key is not WorkflowKey.ACTIVITY_QUERY:
        return

    today = today_for(timezone_name)
    start_date, end_date, date_range_label = resolve_labour_date_range(
        event.fields.get("date_range"), today=today
    )
    results = await activity_search_service.search(
        organization_id=actor.organization_id,
        project_id=event.project_id,
        site_id=event.site_id,
        start_date=start_date,
        end_date=end_date,
        work_type=event.fields.get("work_type"),
    )
    results["date_range_label"] = date_range_label
    event.fields["activity_search_results"] = results


def _dpr_scope(event: CanonicalEventV2, actor: ActorIdentity) -> tuple[str | None, str | None]:
    """The project and site whose report to look up. A bare "send me today's
    report" names neither, and the request has no required fields, so no gate
    resolves them: fall back to the sender's own access -- a lone project, and
    a lone site under it. With several sites nothing is guessed and the
    project roll-up is looked up."""
    project_id = event.project_id
    site_id = event.site_id
    projects = getattr(actor, "projects", None) or []
    sites = getattr(actor, "sites", None) or []
    if project_id is None and len(projects) == 1:
        project_id = projects[0].id
    if site_id is None:
        under = [s for s in sites if project_id is None or s.project_id == project_id]
        if len(under) == 1:
            site_id = under[0].id
            if project_id is None:
                project_id = under[0].project_id
    return project_id, site_id


async def _seed_dpr_request(
    event: CanonicalEventV2,
    decision: PlannerDecisionV2,
    dpr_request_query: DprRequestQueryService | None,
    actor: ActorIdentity | None,
    timezone_name: str | None,
    object_storage: ObjectStoragePort | None = None,
) -> None:
    """Resolve today's DPR status before the graph runs -- same shape and
    reasoning as _seed_labour_query above. Only ever runs for DPR_REQUEST.

    Only ever checks *today* -- see runtime/dpr_request_query.py's module
    docstring for why a date range isn't extracted for this V1 trigger.
    Writes `dpr_object_key` even though the node itself never reads it
    (workflows/dpr_request/nodes.py only reads `dpr_status`/`dpr_code`) --
    the post-reply delivery step below (in process_inbound_message) is what
    actually fetches and sends the PDF, and it reads the field straight off
    `canonical_event.fields` rather than threading a third value through
    the node's return dict.
    """
    if decision.workflow_key is not WorkflowKey.DPR_REQUEST:
        return
    if dpr_request_query is None or actor is None or not actor.organization_id:
        # Not "no report exists": the lookup could not be made at all.
        event.fields["dpr_status"] = "unavailable"
        event.fields["dpr_object_key"] = None
        event.fields["dpr_code"] = None
        return

    project_id, site_id = _dpr_scope(event, actor)
    today = today_for(timezone_name)
    report_date = today
    stated = event.fields.get("report_date") or event.fields.get("occurred_on")
    if stated not in (None, ""):
        # Any day, not only today (request 57, A4). A day that cannot be read
        # ("last Friday", tomorrow) is asked about, never answered with
        # today's report.
        report_date = parse_stated_date(stated, today=today)
        if report_date is None:
            event.fields["dpr_status"] = "bad_date"
            event.fields["dpr_object_key"] = None
            event.fields["dpr_code"] = None
            return
    event.fields["dpr_day"] = "" if report_date == today else f"{report_date:%d %b %Y}".lstrip("0")
    try:
        result = await dpr_request_query.find_report(
            organization_id=actor.organization_id,
            project_id=project_id,
            site_id=site_id,
            report_date=report_date,
        )
    except Exception:  # noqa: BLE001 -- an honest "can't check" beats a failed run
        _log.exception(
            "dpr_request.lookup_failed correlation_id=%s user=%s",
            event.correlation_id,
            getattr(actor, "user_id", None),
        )
        event.fields["dpr_status"] = "unavailable"
        event.fields["dpr_object_key"] = None
        event.fields["dpr_code"] = None
        return
    if result["status"] == "not_generated" and report_date == today and project_id and site_id:
        # WA-40: today's report is only built at the evening cutoff; asked for
        # during the day, the sender gets what the day holds so far, marked
        # as a draft (nothing is stored or sent to the report's recipients).
        try:
            lines = await dpr_request_query.preview_lines(
                organization_id=actor.organization_id,
                project_id=project_id,
                site_id=site_id,
                report_date=today,
            )
        except Exception:  # noqa: BLE001 -- the plain "not generated" still answers
            _log.warning("dpr_request.preview_failed correlation_id=%s", event.correlation_id, exc_info=True)
            lines = []
        if lines:
            result = {**result, "status": "preview"}
            event.fields["dpr_preview"] = "\n".join(lines)
    event.fields["dpr_status"] = result["status"]
    event.fields["dpr_object_key"] = result["object_key"]
    event.fields["dpr_code"] = result["code"]
    event.fields["dpr_confirmed"] = result.get("confirmed", True)
    event.fields["dpr_update_count"] = result.get("update_count", 0)
    event.fields["dpr_site_name"] = next(
        (getattr(s, "name", None) for s in getattr(actor, "sites", None) or [] if s.id == site_id),
        None,
    )
    if result["status"] == "ready" and object_storage is not None:
        # The reply says a PDF is attached: be sure it can be fetched before
        # saying so (the send itself comes after the reply).
        try:
            await object_storage.head_object(result["object_key"])
        except Exception:  # noqa: BLE001 -- say so rather than promise a PDF
            _log.warning(
                "dpr_request.pdf_unavailable correlation_id=%s object_key=%s",
                event.correlation_id,
                result["object_key"],
                exc_info=True,
            )
            event.fields["dpr_status"] = "pdf_unavailable"
            event.fields["dpr_object_key"] = None


async def _seed_project_detail_query(
    event: CanonicalEventV2,
    decision: PlannerDecisionV2,
    activity_search_service: ActivitySearchService | None,
    labour_query_service: LabourQueryService | None,
    expense_query_service: ExpenseQueryService | None,
    inventory_query: MaterialInventoryQueryService | None,
    project_detail_query: ProjectDetailQueryService | None,
    actor: ActorIdentity | None,
    timezone_name: str | None,
) -> None:
    """Compose "give me all details of this project/site" before the graph
    runs -- same shape and reasoning as _seed_activity_search above. Only
    ever runs for PROJECT_DETAIL_QUERY.

    Record-card fields (name/code/location/status, the site list) come from
    `actor.projects`/`.sites` -- already resolved once per inbound message
    (see backend/postgres/actor.py), not a new query. Operational rollups
    reuse the same runtime query services ACTIVITY_QUERY/LABOUR_QUERY/
    MATERIAL_INVENTORY_QUERY already seed from. The financial section is
    visibility-gated by role, not refused outright: a SITE_ENGINEER still
    gets a full reply, just without the "finance" key (see enums.py's
    SemanticType.PROJECT_DETAIL_QUERY docstring) -- unlike PROJECT_CREATE/
    SITE_CREATE, which refuse the whole workflow for a disallowed role,
    this is a read, so nothing is ever denied here, only withheld.
    """
    if actor is None or not actor.organization_id:
        return
    if decision.workflow_key is not WorkflowKey.PROJECT_DETAIL_QUERY:
        return

    project_id = event.project_id
    site_id = event.site_id
    if not project_id and not site_id:
        # Context resolution came up with nothing specific (the sender
        # belongs to more than one project and didn't name one) -- every
        # downstream query service below treats a null project/site as
        # "don't narrow", which would silently answer for the whole
        # organization. "Give me all details" implies one specific target,
        # so ask instead (see workflows/project_detail_query/nodes.py).
        event.fields["project_detail_unresolved"] = True
        return

    site = next((s for s in actor.sites if s.id == site_id), None) if site_id else None
    project = next((p for p in actor.projects if p.id == project_id), None) if project_id else None
    level = "site" if site is not None else "project"

    result: dict[str, Any] = {
        "level": level,
        "project": (
            {
                "id": project.id,
                "name": project.name,
                "code": project.code,
                "location": project.location,
                "status": project.status,
            }
            if project is not None
            else None
        ),
        "site": {"id": site.id, "name": site.name} if site is not None else None,
        "sites": None,
        "member_count": None,
    }
    if level == "project" and project_id:
        result["sites"] = [{"id": s.id, "name": s.name} for s in actor.sites if s.project_id == project_id]
        if project_detail_query is not None:
            result["member_count"] = await project_detail_query.count_members(project_id=project_id)

    today = today_for(timezone_name)
    activity_results: dict[str, Any] = {}
    labour_results: dict[str, Any] = {}
    stock_levels: list[dict[str, Any]] = []
    if activity_search_service is not None:
        activity_results = await activity_search_service.search(
            organization_id=actor.organization_id,
            project_id=project_id,
            site_id=site_id,
            start_date=today,
            end_date=today,
        )
    if labour_query_service is not None:
        labour_results = await labour_query_service.summarize_attendance(
            organization_id=actor.organization_id,
            project_id=project_id,
            site_id=site_id,
            start_date=today,
            end_date=today,
        )
    if inventory_query is not None:
        stock_levels = await inventory_query.query(
            organization_id=actor.organization_id,
            project_id=project_id,
            site_id=site_id,
            material_name=None,
        )

    result["activity_count"] = activity_results.get("activity_count", 0)
    result["open_issue_count"] = activity_results.get("open_issue_count", 0)
    result["open_issues"] = activity_results.get("open_issues") or []
    result["headcount"] = labour_results.get("headcount", 0)
    result["labour_cost"] = labour_results.get("total_cost", "0")
    result["stock_levels"] = stock_levels

    # Financial visibility: withheld entirely for SITE_ENGINEER -- a read,
    # not a write, so the reply is never refused, only the money line.
    if expense_query_service is not None and str(actor.role or "").strip().upper() != "SITE_ENGINEER":
        start_date, end_date, date_range_label = resolve_date_range(None)
        expenses = await expense_query_service.list_expenses(
            organization_id=actor.organization_id,
            project_id=project_id,
            site_id=site_id,
            start_date=start_date,
            end_date=end_date,
        )
        result["finance"] = {
            "total": str(ExpenseQueryService.total(expenses)),
            "count": len(expenses),
            "date_range_label": date_range_label,
        }

    event.fields["project_detail_results"] = result


async def _seed_worker_candidates(
    event: CanonicalEventV2,
    decision: PlannerDecisionV2,
    workforce_query: WorkforceQueryService | None,
    actor: ActorIdentity | None,
) -> None:
    """Feed the workforce register into the event so labour_update's
    match_workers node can decide whether a reported "Ravi" is someone
    already known -- a node must never query a repository itself (see
    workflows/runtime.py), same principle as _seed_account_candidates above.
    Only ever runs for LABOUR_ATTENDANCE.

    Skipped entirely when the report names nobody: an attendance of pure
    headcount groups ("12 helpers, 4 masons") has nothing to match, so
    reading the register would be work done to answer a question no one
    asked. This is the common case on many sites (principle P10), and it is
    also the fastest one -- keeping it free matters (P9).

    An empty register is a normal, correct outcome, not a failure: every
    named worker then resolves to a temporary worker and the workflow asks
    nothing (P3). The register is only ever read here -- attendance must
    never write it (P1).
    """
    if workforce_query is None or actor is None or not actor.organization_id:
        return
    if decision.workflow_key is not WorkflowKey.LABOUR_ATTENDANCE:
        return

    lines = event.fields.get("lines")
    if not isinstance(lines, list):
        return
    names_reported = any(
        isinstance(line, dict) and str(line.get("worker_name") or "").strip() for line in lines
    )
    if not names_reported:
        return

    candidates = await workforce_query.list_worker_candidates(
        organization_id=actor.organization_id,
        project_id=event.project_id,
        site_id=event.site_id,
    )
    if candidates:
        event.fields["worker_candidates"] = candidates


async def _seed_existing_attendance(
    event: CanonicalEventV2,
    decision: PlannerDecisionV2,
    workforce_query: WorkforceQueryService | None,
    actor: ActorIdentity | None,
    org_settings_query: OrganizationSettingsQueryService | None = None,
) -> None:
    """Flag that this site and day already has a report, before the graph runs
    (a node must never query a repository itself -- same principle as
    _seed_worker_candidates above). Only ever runs for LABOUR_ATTENDANCE.

    Attendance cannot be edited (P5), so a supervisor who forgets someone
    re-sends the whole list. Until now nothing noticed: the second report was
    stored as an independent row and both counted, which is how a day of 18
    workers reads as 16 + 18 = 34 man-days with cost inflated to match. This
    is the read that lets the workflow ask which one the supervisor meant.

    Needs a project and a date to ask a meaningful question; without either,
    silence is correct -- "is this a duplicate of something?" cannot be
    answered against an unresolved day.

    BE-10: for a company that saves first, the question is not asked. Labour
    is a snapshot per site and day (latest per contractor + trade, or per
    named worker), so a re-send replaces only the figures it repeats and a
    second crew still adds on. What the day counts so far is seeded as
    `day_counted_lines` instead, for the saved reply to say what changed.
    """
    if workforce_query is None or actor is None or not actor.organization_id:
        return
    if decision.workflow_key is not WorkflowKey.LABOUR_ATTENDANCE:
        return
    if not event.project_id:
        return

    occurred_date = str(event.fields.get("occurred_date") or "").strip()
    if not occurred_date:
        return

    # Never let this cost the message. `_plan_and_run`'s seeding gather has no
    # return_exceptions, so anything raised here propagates all the way to the
    # journey's catch-all and the supervisor is told "nothing was recorded" --
    # which is exactly what happened when this shipped passing an ISO string
    # where asyncpg wanted a date. Not asking the duplicate question is a
    # small loss; losing the attendance is not, and this check is an
    # enhancement to recording, never a precondition for it.
    try:
        existing = await workforce_query.find_existing_report_for_day(
            organization_id=actor.organization_id,
            project_id=event.project_id,
            site_id=event.site_id,
            occurred_date=occurred_date,
        )
    except Exception:  # noqa: BLE001 -- see above; degrade to not asking
        _log.exception(
            "labour.duplicate_day_check_failed org=%s project=%s date=%s",
            actor.organization_id,
            event.project_id,
            occurred_date,
        )
        return

    if existing and existing.get("report_id"):
        try:
            saves_first = await company_saves_first(org_settings_query, str(actor.organization_id))
        except Exception:  # noqa: BLE001 -- same reason as above; the default
            _log.exception("labour.capture_mode_read_failed org=%s", actor.organization_id)
            saves_first = True
        if saves_first:
            event.fields["day_counted_lines"] = existing.get("counted_lines") or []
        else:
            event.fields["existing_report"] = existing


async def _maybe_trigger_worker_promotion(
    handled: InteractionHandled,
    workflow_runtime: WorkflowRuntime,
    workforce_query: WorkforceQueryService | None,
    actor: Any,
    wa_id: str,
    send_text_fn: Callable[[str, str], Awaitable[Any]],
    send_spec_fn: Callable[[Any, str], Awaitable[Any]] | None = None,
) -> bool:
    """After a confirmed RECORD_LABOUR_ATTENDANCE execution, send a follow-up
    offer to add named temporary workers to the Worker Register.

    Returns True when an offer was actually put on screen. The caller uses
    that to decide whether the team-photo prompt follows now or waits for the
    promotion answer -- two prompts arriving together would read as one
    confusing wall of text.

    Fires only when:
    - The confirmed action type is RECORD_LABOUR_ATTENDANCE
    - The domain execution succeeded
    - At least one attendance line has a non-empty worker_name AND worker_id=None

    Nothing in the attendance workflow is changed. This is the optional second
    step (plan principle P1 + P9): attendance first, register management later.
    """
    # Every early return below logs why. This has now silently declined to
    # fire twice for different reasons, each time indistinguishable from the
    # feature simply not existing -- there is no way to tell from the outside
    # whether the offer was skipped deliberately or a guard rejected it. One
    # INFO line per decision makes the next report answerable from the logs
    # instead of from guesswork.
    def _skip(reason: str, **detail: Any) -> None:
        _log.info(
            "worker_promotion.skipped reason=%s %s",
            reason,
            " ".join(f"{k}={v}" for k, v in detail.items()),
        )

    # Guard: only after a successful RECORD_LABOUR_ATTENDANCE execution.
    if not isinstance(handled.result, WorkflowResumeResult):
        _skip("not_a_resume", got=type(handled.result).__name__)
        return False
    if handled.result.status is not WorkflowResumeStatus.CONFIRMED:
        _skip("not_confirmed", status=handled.result.status.value)
        return False
    confirmed = handled.result.confirmed_action
    if confirmed is None:
        _skip("no_confirmed_action")
        return False
    if confirmed.draft_action.action_type is not DraftActionType.RECORD_LABOUR_ATTENDANCE:
        _skip("not_attendance", action=confirmed.draft_action.action_type.value)
        return False
    if handled.execution_result is None:
        _skip("no_execution_result")
        return False
    # Import here to avoid circular dependency at module load time.
    from mesiri_contracts.application.results.execution_result import ExecutionStatus
    if handled.execution_result.status is not ExecutionStatus.SUCCEEDED:
        # ALREADY_EXECUTED lands here on a genuine replay -- a resend of the
        # same confirmation. Worth seeing, because it also means the offer for
        # that report was already made once.
        _skip("execution_not_succeeded", status=handled.execution_result.status.value)
        return False

    org_id = str(getattr(actor, "organization_id", None) or "")
    if not org_id:
        _skip("no_organization_on_actor", actor=type(actor).__name__)
        return False

    # Extract named temporary workers from the confirmed attendance lines.
    lines = confirmed.draft_action.fields.get("lines") or []
    promotable: list[dict] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        name = str(line.get("worker_name") or "").strip()
        if not name:
            continue  # Headcount-only worker — never promote directly.
        if line.get("worker_id") is not None:
            continue  # Already matched to a registered worker — nothing to promote.
        promotable.append({
            "name": name,
            "trade": line.get("trade"),
            "daily_wage": line.get("daily_wage"),
        })

    if not promotable:
        _skip("no_new_named_workers", lines=len(lines))
        return False

    # Seed the register so the promotion node can screen each chosen worker
    # against it (name + trade + contractor) before writing. A node must never
    # query a repository itself -- same principle as _seed_worker_candidates.
    # Read fresh rather than reusing the attendance run's copy: this one has to
    # include anyone added since, or the check would miss exactly the duplicate
    # it exists to catch.
    register: list[dict] = []
    if workforce_query is not None:
        try:
            register = await workforce_query.list_worker_candidates(
                organization_id=org_id,
                project_id=str(confirmed.draft_action.project_id or "") or None,
                site_id=str(confirmed.draft_action.site_id or "") or None,
            )
        except Exception:  # noqa: BLE001 — promotion never blocks attendance
            register = []

    # Synthetic decision + event to drive the promotion workflow through the
    # WorkflowRuntime (which handles COLLECTING_FIELDS persistence, provide_input
    # resume, and the single-active gate bypass for informational workflows).
    promotion_correlation_id = _new_id("promo")
    promotion_decision = PlannerDecisionV2(
        correlation_id=promotion_correlation_id,
        source_message_id=promotion_correlation_id,
        decision_type=PlannerDecisionType.START_WORKFLOW,
        workflow_key=WorkflowKey.WORKER_PROMOTION,
        reason=CanonicalEventType.LABOUR_ATTENDANCE_REQUESTED,
        organization_id=confirmed.draft_action.organization_id,
        user_id=confirmed.draft_action.user_id,
        project_id=confirmed.draft_action.project_id,
        site_id=confirmed.draft_action.site_id,
    )
    promotion_event = CanonicalEventV2(
        event_id=promotion_correlation_id,
        correlation_id=promotion_correlation_id,
        source_message_id=promotion_correlation_id,
        event_type=CanonicalEventType.LABOUR_ATTENDANCE_REQUESTED,
        completeness=_IntentCompleteness.ACTIONABLE,
        organization_id=confirmed.draft_action.organization_id,
        user_id=confirmed.draft_action.user_id,
        project_id=confirmed.draft_action.project_id,
        site_id=confirmed.draft_action.site_id,
        fields={
            "promotable_workers": promotable,
            "_register": register,
        },
    )

    # Replace any offer still open from an earlier report rather than adding
    # a second one. The list a supervisor is looking at must describe the
    # report they just filed -- with two offers outstanding, the answer goes
    # to whichever row is newest and the older list silently persists, which
    # is how a newly named worker appeared to "never show up".
    await _safe(workflow_runtime.abandon_optional_question(str(confirmed.draft_action.user_id)))

    try:
        promo_run = await workflow_runtime.start(promotion_decision, promotion_event)
    except Exception:  # noqa: BLE001 — promotion failure never blocks or retries
        _log.exception("worker_promotion.start_failed org=%s", org_id)
        return False

    # Pass 1 result: the promotion node ran, built the offer message, and
    # saved the state as COLLECTING_FIELDS waiting for the user's choice.
    if promo_run.pending_prompt:
        _log.info(
            "worker_promotion.offered org=%s workers=%d status=%s",
            org_id,
            len(promotable),
            promo_run.status.value,
        )
        if send_spec_fn is not None and promo_run.slot_options:
            # The offer comes with its buttons (Add both / Choose / Not now);
            # the caller folds it into the one reply (request [45]/[51]).
            from runtime.inbound_journey.reply import render_workflow_run_reply_spec

            await _safe(send_spec_fn(render_workflow_run_reply_spec(promo_run), wa_id))
        else:
            await _safe(send_text_fn(wa_id, promo_run.pending_prompt))
        return True
    else:
        # The run produced no message -- the offer exists nowhere the user can
        # see. Loud, because this is indistinguishable from the feature being
        # switched off, and is exactly how it went unnoticed before.
        _log.error(
            "worker_promotion.no_prompt org=%s status=%s workers=%d",
            org_id,
            promo_run.status.value,
            len(promotable),
        )
    return False


def _recorded_attendance_report_id(handled: InteractionHandled) -> str | None:
    """The attendance report just written, or None if this wasn't one.

    material_row_id is the shared "the thing you created" field on
    ExecutionResult; for labour it carries the attendance report id (see
    repositories/labour_execution.py). Read here rather than threaded through
    the promotion trigger so the team-photo offer does not depend on whether
    promotion ran at all.
    """
    from mesiri_contracts.application.results.execution_result import ExecutionStatus

    result = handled.result
    if not isinstance(result, WorkflowResumeResult):
        return None
    if result.status is not WorkflowResumeStatus.CONFIRMED:
        return None
    confirmed = result.confirmed_action
    if confirmed is None:
        return None
    if confirmed.draft_action.action_type is not DraftActionType.RECORD_LABOUR_ATTENDANCE:
        return None
    execution = handled.execution_result
    if execution is None or execution.status is not ExecutionStatus.SUCCEEDED:
        return None
    return execution.material_row_id


def _promotion_just_finished(result: WorkflowRunResult | WorkflowResumeResult) -> bool:
    """True when this slot answer completed the worker-promotion workflow.

    The slot-answer path carries every workflow's answers, so the team-photo
    offer has to identify its own cue rather than firing on any completed
    question.
    """
    return (
        isinstance(result, WorkflowRunResult)
        and result.workflow_key is WorkflowKey.WORKER_PROMOTION
        and result.status is WorkflowRunStatus.COMPLETED
    )


async def _offer_team_photo(
    report_id: str,
    actor: Any,
    wa_id: str,
    team_photo_hint_store: Any,
    send_reply: Callable[..., Awaitable[Any]],
) -> None:
    """Offer to attach a photo of the crew, once the record is safely saved.

    Sent after the promotion step is settled rather than beside it, so the
    supervisor is answering one question at a time.

    The report id is parked in Redis rather than asked for again: the next
    photo this user sends is plainly the answer to the question just asked,
    and making them re-state which day it belongs to would be absurd. The
    hint is pop-once and expires -- see interactions/team_photo_hint.py for
    why a photo sent an hour later must not silently land on a closed day.

    Recommended, never required. Attendance is already recorded by the time
    this is sent, and nothing here can undo that.
    """
    from channel.replies import render_team_photo_offer

    user_id = str(getattr(actor, "user_id", None) or "")
    if not user_id or not report_id:
        return
    # At most once a day: the second and third labour save of the day must not
    # each ask for the same crew photo (request [43]).
    claim = getattr(team_photo_hint_store, "claim_daily_offer", None)
    if claim is not None:
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
            if not await claim(user_id=user_id, today=today):
                return
        except Exception:  # noqa: BLE001 -- a failed check offers, as before
            _log.warning("team_photo.daily_check_failed user=%s", user_id)
    try:
        await team_photo_hint_store.set_hint(user_id=user_id, report_id=report_id)
    except Exception:  # noqa: BLE001 -- a hint is never worth failing a reply over
        _log.warning("team_photo.hint_failed user=%s", user_id)
        return
    _log.info("team_photo.offered user=%s report=%s", user_id, report_id)
    await _safe(send_reply(render_team_photo_offer(), wa_id))


def _project_setup_offer_target(
    handled: InteractionHandled,
) -> tuple[str, str, str | None] | None:
    """Which setup offer (if any) follows this confirmed action, as
    ``(stage, project_id, project_name)`` -- or None if this confirmation
    isn't one the chain reacts to.

    CREATE_PROJECT -> offer stage "site": the new project's id comes off the
    execution result (material_row_id is the shared "id of the thing just
    created" field, same as _recorded_attendance_report_id reads it for
    labour), since draft_action.project_id is None for a project that didn't
    exist until this execution. project_name comes off the draft's own
    fields (it was in the confirmation the user just approved).

    CREATE_SITE -> offer stage "member": unlike CREATE_PROJECT, the site's
    draft already carries project_id directly (workflows/site_create/
    nodes.py resolves it from context before the draft is ever built), so no
    execution-result lookup is needed here. No project_name is threaded
    through -- render_project_member_offer doesn't use one.
    """
    from mesiri_contracts.application.results.execution_result import ExecutionStatus

    result = handled.result
    if not isinstance(result, WorkflowResumeResult):
        return None
    if result.status is not WorkflowResumeStatus.CONFIRMED:
        return None
    confirmed = result.confirmed_action
    if confirmed is None:
        return None
    execution = handled.execution_result
    if execution is None or execution.status is not ExecutionStatus.SUCCEEDED:
        return None
    action_type = confirmed.draft_action.action_type
    if action_type is DraftActionType.CREATE_PROJECT:
        if not execution.material_row_id:
            return None
        name = confirmed.draft_action.fields.get("name")
        return ("site", execution.material_row_id, str(name) if name else None)
    if action_type is DraftActionType.CREATE_SITE:
        project_id = confirmed.draft_action.project_id
        if not project_id:
            return None
        return ("member", str(project_id), None)
    return None


async def _offer_project_setup(
    handled: InteractionHandled,
    project_setup_offer_store: Any,
    actor: Any,
    wa_id: str,
    send_reply: Callable[..., Awaitable[Any]],
) -> bool:
    """After a confirmed CREATE_PROJECT or CREATE_SITE execution, send the
    chained setup offer (tappable "Add a Site now?" / "Add a Teammate
    now?") -- see channel/replies.py's render_project_site_offer/
    render_project_member_offer and interactions/project_setup_offer.py's
    ProjectSetupOfferStore docstring for the full chain.

    Returns True when an offer was actually put on screen, same contract as
    _maybe_trigger_worker_promotion, though nothing here currently reads the
    return value the way the team-photo sequencing does -- kept for
    parity/testability.
    """
    target = _project_setup_offer_target(handled)
    if target is None:
        return False
    stage, project_id, project_name = target
    user_id = str(getattr(actor, "user_id", None) or "")
    if not user_id:
        return False
    try:
        await project_setup_offer_store.set_offer(
            user_id=user_id, stage=stage, project_id=project_id
        )
    except Exception:  # noqa: BLE001 -- an offer is never worth failing a reply over
        _log.warning("project_setup.offer_store_failed user=%s stage=%s", user_id, stage)
        return False
    from channel.replies import render_project_member_offer, render_project_site_offer

    spec = (
        render_project_site_offer(project_name)
        if stage == "site"
        else render_project_member_offer()
    )
    _log.info("project_setup.offered user=%s stage=%s project=%s", user_id, stage, project_id)
    await _safe(send_reply(spec, wa_id))
    return True


async def start_project_setup_followup(
    *,
    stage: str,
    project_id: str,
    actor: Any,
    workflow_runtime: WorkflowRuntime,
) -> ReplySpec | None:
    """Start SITE_CREATE (stage "site") or ADD_PROJECT_MEMBER (stage
    "member") directly, with `project_id` already known -- called when the
    user taps "Add a Site now" / "Add a Teammate now" on the offer built by
    _offer_project_setup (see runtime/message_journey.py's tap handler).

    Mirrors _maybe_trigger_worker_promotion's "hand-build a PlannerDecisionV2
    + CanonicalEventV2, then call the same workflow_runtime.start() the
    normal Planner path uses" pattern -- there is no lower-level shortcut.
    `fields={}` leaves the new workflow's own build_draft to ask for
    whatever it still needs (the site's name, or who to add) exactly as it
    would for an ordinary message, except the project question is already
    answered. `created_by_role` is seeded the same way runtime/
    inbound_journey/seeding.py's _seed_project_create_role does for the
    ordinary path, since the tapper already passed that same role gate to
    create the project/site this offer follows -- skipping it here would
    make create_site_validation.py's/add_member_validation.py's role check
    reject the eventual confirm with no created_by_role to check.

    Returns a ReplySpec for the question the new workflow is now asking, or
    None if nothing could be started -- the caller falls back to a generic
    "please try again" reply. A ReplySpec, not a bare string: SITE_CREATE and
    ADD_PROJECT_MEMBER can both build a real confirmable draft here, and the
    account-admin/CREATE_USER fixes for the same "plain text instead of
    Yes/No buttons" bug apply here too -- see
    runtime/inbound_journey/reply.py's render_workflow_run_reply_spec, the
    one place that decides plain text vs Yes/No buttons vs a tappable list
    for a WorkflowRunResult.
    """
    workflow_key = WorkflowKey.SITE_CREATE if stage == "site" else WorkflowKey.ADD_PROJECT_MEMBER
    reason = (
        CanonicalEventType.SITE_CREATE_REQUESTED
        if stage == "site"
        else CanonicalEventType.ADD_PROJECT_MEMBER_REQUESTED
    )
    org_id = str(getattr(actor, "organization_id", None) or "")
    user_id = str(getattr(actor, "user_id", None) or "")
    if not org_id or not user_id:
        return None

    corr_id = _new_id("setup")
    decision = PlannerDecisionV2(
        correlation_id=corr_id,
        source_message_id=corr_id,
        decision_type=PlannerDecisionType.START_WORKFLOW,
        workflow_key=workflow_key,
        reason=reason,
        organization_id=org_id,
        user_id=user_id,
        project_id=project_id,
    )
    event = CanonicalEventV2(
        event_id=corr_id,
        correlation_id=corr_id,
        source_message_id=corr_id,
        event_type=reason,
        completeness=_IntentCompleteness.ACTIONABLE,
        organization_id=org_id,
        user_id=user_id,
        project_id=project_id,
        fields={"created_by_role": getattr(actor, "role", None)},
    )

    await _safe(workflow_runtime.abandon_optional_question(user_id))

    try:
        run = await workflow_runtime.start(decision, event)
    except Exception:  # noqa: BLE001 -- never raise into the tap handler
        _log.exception("project_setup.start_failed org=%s stage=%s", org_id, stage)
        return None
    if not run.pending_prompt:
        _log.error(
            "project_setup.no_prompt org=%s stage=%s status=%s", org_id, stage, run.status.value
        )
        return None

    from runtime.inbound_journey.reply import render_workflow_run_reply_spec

    return render_workflow_run_reply_spec(run)


async def _create_promoted_workers(
    result: WorkflowRunResult | WorkflowResumeResult,
    workforce_query: WorkforceQueryService | None,
    actor: Any,
    wa_id: str,
    send_text_fn: Callable[[str, str], Awaitable[Any]],
) -> None:
    """Perform the register writes the promotion node decided on.

    The node is pure and cannot write (see workflows/worker_promotion/nodes.py
    for why a seeded callable is not an option here), so it lists whoever it
    concluded should be added under WORKERS_TO_CREATE and leaves the inserts
    to this side, which is holding the database.

    The confirmation text the user already saw names those workers, so a
    failure here has to correct itself out loud rather than fail silently --
    the attendance record is safe either way, but a register entry the user
    believes exists and doesn't is worse than an error message.
    """
    from workflows.worker_promotion.nodes import WORKERS_TO_CREATE

    fields = getattr(result, "collected_fields", None)
    if not isinstance(fields, dict):
        return
    queued = fields.get(WORKERS_TO_CREATE)
    if not isinstance(queued, list) or not queued:
        return
    if workforce_query is None:
        _log.error("worker_promotion.no_workforce_query queued=%d", len(queued))
        return

    org_id = str(getattr(actor, "organization_id", None) or "")
    if not org_id:
        _log.error("worker_promotion.no_organization queued=%d", len(queued))
        return
    # created_by is NOT NULL on workforce_workers, so a missing user id makes
    # every insert fail. Say so once, clearly, rather than reporting each
    # worker individually as a mystery failure.
    created_by = str(getattr(actor, "user_id", None) or "") or None
    if created_by is None:
        _log.error("worker_promotion.no_user_id org=%s queued=%d", org_id, len(queued))

    failed: list[str] = []
    for worker in queued:
        if not isinstance(worker, dict) or not str(worker.get("name") or "").strip():
            continue
        try:
            await workforce_query.create_worker(
                organization_id=org_id,
                name=str(worker["name"]),
                trade=worker.get("trade"),
                daily_wage=worker.get("daily_wage"),
                created_by=created_by,
            )
        except Exception:  # noqa: BLE001 — a failed promotion never disturbs attendance
            # exception(), not warning(): "some workers wouldn't save" is not
            # diagnosable without the reason, and this is the only place it
            # exists.
            _log.exception(
                "worker_promotion.create_failed org=%s name=%s", org_id, worker.get("name")
            )
            failed.append(str(worker["name"]))

    _log.info(
        "worker_promotion.created org=%s requested=%d failed=%d",
        org_id,
        len(queued),
        len(failed),
    )
    if failed:
        await _safe(
            send_text_fn(
                wa_id,
                f"⚠️ I couldn't add {', '.join(failed)} to the Worker Register after all "
                "— please add them from the dashboard. Today's attendance is saved and "
                "unaffected.",
            )
        )


async def _seed_duplicate_check(
    event: CanonicalEventV2,
    decision: PlannerDecisionV2,
    duplicate_expense_query: DuplicateExpenseQueryService | None,
    actor: ActorIdentity | None,
) -> None:
    """Finance Module Slice 8: flag a likely-duplicate expense before the
    graph runs (a node must never query a repository itself, same principle
    as _seed_account_candidates above). Only ever runs for EXPENSE_SUBMIT.
    No signal beyond amount+date alone is strong enough, so this is skipped
    entirely when neither vendor nor category was extracted -- see
    runtime/duplicate_expense_query.py."""
    if duplicate_expense_query is None or actor is None or not actor.organization_id:
        return
    if decision.workflow_key is not WorkflowKey.EXPENSE_SUBMIT:
        return
    amount = event.fields.get("amount")
    vendor_name = event.fields.get("vendor")
    category_name = event.fields.get("category")
    if amount is None or not (vendor_name or category_name):
        return
    is_duplicate = await duplicate_expense_query.find_potential_duplicate(
        organization_id=actor.organization_id,
        project_id=event.project_id,
        amount=amount,
        vendor_name=vendor_name,
        category_name=category_name,
    )
    if is_duplicate:
        event.fields["is_potential_duplicate"] = True


async def _seed_vendor_check(
    event: CanonicalEventV2,
    decision: PlannerDecisionV2,
    vendor_query: VendorQueryService | None,
    actor: ActorIdentity | None,
) -> None:
    """Resolve a reported vendor name against the org's active vendors before
    the graph runs (a node must never query a repository itself, same
    principle as _seed_account_candidates above). Only ever runs for
    EXPENSE_SUBMIT, and only when a vendor was actually extracted --
    otherwise there is nothing to confirm and expense_capture's build_draft
    proceeds vendor-less exactly as before. See workflows/expense_capture/
    nodes.py's `resolve_vendor`.

    Phase 4 (ENTITY_RESOLUTION_PLAN.md §5) moved this onto the shared
    Resolved/Ambiguous/Missing vocabulary. The three outcomes:

    - Resolved: rewrite `vendor` to the matched vendor's *exact stored name*.
      This is the fix for the duplicate-row bug -- the backend resolver
      re-matches on exactly this string and creates a row when it misses, so
      handing it the canonical spelling is what stops "Sharma Traders"
      becoming a second vendor alongside "Sharma Trading Co".
    - Ambiguous: hand the near-matches to the node as `vendor_candidates` so
      it can ask, instead of the old unconditional "add it as new?".
    - Missing: `vendor_needs_confirmation`, exactly as before.

    Never raises: a lookup failure degrades to the pre-Phase-4 behaviour
    (ask whether to add it) rather than losing the expense, same posture as
    every other gate in this module.
    """
    if vendor_query is None or actor is None or not actor.organization_id:
        return
    if decision.workflow_key is not WorkflowKey.EXPENSE_SUBMIT:
        return
    vendor_name = event.fields.get("vendor")
    if not vendor_name:
        return

    from workflows.entities import Ambiguous, Resolved

    try:
        outcome = await vendor_query.resolve(
            organization_id=actor.organization_id, vendor_name=str(vendor_name)
        )
    except Exception:
        _log.exception("vendor_gate.lookup_failed correlation_id=%s", event.correlation_id)
        event.fields["vendor_needs_confirmation"] = True
        return

    if isinstance(outcome, Resolved):
        event.fields["vendor"] = outcome.display_name
        return
    if isinstance(outcome, Ambiguous):
        event.fields["vendor_candidates"] = [
            {"value": c.entity_id, "label": c.display_name} for c in outcome.candidates
        ]
    event.fields["vendor_needs_confirmation"] = True


async def _seed_open_activity(
    event: CanonicalEventV2,
    decision: PlannerDecisionV2,
    activity_query: ActivityQueryService | None,
    actor: ActorIdentity | None,
    *,
    remembered_activity_id: str | None = None,
    org_settings_query: OrganizationSettingsQueryService | None = None,
) -> None:
    """Resolve which Activity (if any) a site update message
    ("finished plastering", "completed another 40 sqm") might be about,
    before the graph runs (a node must never query a repository itself,
    same principle as _seed_account_candidates above). Only ever runs for
    WorkflowKey.SITE_UPDATE -- the single merged workflow that now handles
    both "start a new Activity" and "append a Progress Update to an
    existing one" (docs/execution/ACTIVITY_RESOLUTION_AND_CORRECTION_PLAN.md;
    the separate WorkflowKey.ACTIVITY_CONTINUATION this used to gate on is
    retired).

    ``remembered_activity_id`` (memory/conversation_scope.py's
    CurrentActivityStore -- the activity THIS conversation most recently
    touched) is tried first and, if it's still open, wins outright: it is
    strictly better evidence than any content-based comparison, since it
    reflects what THIS user was just doing. It is revalidated against
    Postgres before use (a memory hint is never authoritative -- see
    memory/requirements.py) and falls through to the candidate-list lookup
    below on any miss.

    Otherwise seeds `_open_activity_candidates` with every open activity on
    this site for this reporter (not just the most recent one -- that
    recency-only selection was F1's root cause, see
    workflows/site_update/matching.py). `workflows/site_update/nodes.py`'s
    `resolve_target` is what actually decides create-vs-continue from this
    list; this function only supplies the candidates, never the decision.
    For a company that saves first it also tells `resolve_target` to treat
    an unclear match as new work rather than ask (WA-03).
    """
    if activity_query is None or actor is None or not actor.organization_id:
        return
    if decision.workflow_key is not WorkflowKey.SITE_UPDATE:
        return

    if remembered_activity_id:
        found = await activity_query.get_activity_if_open(
            organization_id=actor.organization_id, activity_id=remembered_activity_id
        )
        if found is not None:
            event.fields["activity_id"] = found["activity_id"]
            summary_bits = [b for b in (found.get("work_type"), found.get("narrative")) if b]
            if summary_bits:
                event.fields["activity_summary"] = " — ".join(summary_bits)
            return

    candidates = await activity_query.find_open_activities(
        organization_id=actor.organization_id,
        site_id=event.site_id,
        reported_by_user_id=actor.user_id,
    )
    if candidates:
        event.fields["_open_activity_candidates"] = [
            {
                "activity_id": c["activity_id"],
                "work_type": c.get("work_type"),
                "narrative": c.get("narrative"),
            }
            for c in candidates
        ]
        if await company_saves_first(org_settings_query, str(actor.organization_id)):
            event.fields[UNCLEAR_TARGET_IS_NEW_KEY] = True


async def _seed_correction_target(
    event: CanonicalEventV2,
    decision: PlannerDecisionV2,
    activity_query: ActivityQueryService | None,
    actor: ActorIdentity | None,
    *,
    remembered_activity_id: str | None = None,
) -> None:
    """Resolve "make that 180 sqm" into a concrete progress_update_id
    (ADR-D14, docs/execution/ACTIVITY_RESOLUTION_AND_CORRECTION_PLAN.md).
    Only ever runs for WorkflowKey.ACTIVITY_CORRECTION.

    Deliberately scoped to the Activity THIS conversation just touched
    (memory/conversation_scope.py's CurrentActivityStore) only -- same
    same-session reasoning as undo (ADR-D15) and continuation
    (_seed_open_activity above), not a broader "most recent in the org"
    search: correcting a number makes sense only in reference to a number
    just stated in this same exchange. No remembered activity -> nothing
    seeded -> workflows/activity_correction/nodes.py's build_draft
    completes with an honest "nothing to correct" reply and no draft.

    Within that activity, targets its most recent quantity-bearing Progress
    Update (`ActivityQueryService.get_latest_quantity_update`) -- never the
    Activity's own initial quantity (stored in activity_quantities, a
    different table this correction path does not touch; see that
    method's docstring on why that's out of scope for V1)."""
    if activity_query is None or actor is None or not actor.organization_id:
        return
    if decision.workflow_key is not WorkflowKey.ACTIVITY_CORRECTION:
        return
    if not remembered_activity_id:
        return

    target = await activity_query.get_latest_quantity_update(
        organization_id=actor.organization_id, activity_id=remembered_activity_id
    )
    if target is None:
        return

    event.fields["progress_update_id"] = target["progress_update_id"]
    event.fields["old_quantity"] = str(target["quantity"])
    event.fields["old_unit_id"] = target.get("unit_id")
    event.fields["old_unit"] = target.get("unit")
    summary_bits = [b for b in (target.get("work_type"), target.get("narrative")) if b]
    if summary_bits:
        event.fields["correction_activity_summary"] = " — ".join(summary_bits)


async def _seed_finance_query_context(
    event: CanonicalEventV2,
    decision: PlannerDecisionV2,
    money_account_query: MoneyAccountQueryService | None,
    expense_query_service: ExpenseQueryService | None,
    actor: ActorIdentity | None,
) -> None:
    """Feed resolved balance/expense data into the event's fields for
    Finance Module Slice 2's read-only query workflows -- same principle as
    _seed_account_candidates above: a node must never query a repository
    itself, so this is the seeding point. Runs only for
    ACCOUNT_BALANCE_QUERY / EXPENSE_QUERY; every other workflow key's
    fields are left untouched."""
    if actor is None or not actor.organization_id:
        return

    if decision.workflow_key is WorkflowKey.ACCOUNT_BALANCE_QUERY:
        if money_account_query is None:
            return
        account_name = event.fields.get("account_name")
        accounts = await money_account_query.find_matching_accounts(
            organization_id=actor.organization_id,
            created_by=actor.user_id,
            account_name=account_name,
        )
        balances = await money_account_query.get_balances(
            organization_id=actor.organization_id, accounts=accounts
        )
        event.fields["balance_results"] = [
            {"name": account.name, "balance": str(balances[account.id])} for account in accounts
        ]
        return

    if decision.workflow_key is WorkflowKey.EXPENSE_QUERY:
        if expense_query_service is None:
            return
        category_name = event.fields.get("category_name")
        missing_receipts_only = bool(event.fields.get("missing_receipts"))
        start_date, end_date, date_range_label = resolve_date_range(event.fields.get("date_range"))
        expenses = await expense_query_service.list_expenses(
            organization_id=actor.organization_id,
            project_id=event.project_id,
            site_id=event.site_id,
            start_date=start_date,
            end_date=end_date,
            category_name=category_name,
            missing_receipts_only=missing_receipts_only,
        )
        event.fields["expense_results"] = {
            "total": str(ExpenseQueryService.total(expenses)),
            "count": len(expenses),
            "date_range_label": date_range_label,
            "items": [
                {
                    "amount": str(expense.amount),
                    "description": expense.description,
                    "occurred_date": expense.occurred_date.isoformat(),
                }
                for expense in expenses
            ],
        }


_QUERY_PDF_WORKFLOW_KEYS = (
    WorkflowKey.ACCOUNT_BALANCE_QUERY,
    WorkflowKey.EXPENSE_QUERY,
    WorkflowKey.MATERIAL_INVENTORY_QUERY,
    WorkflowKey.ACTIVITY_QUERY,
    WorkflowKey.LABOUR_QUERY,
    WorkflowKey.PROJECT_DETAIL_QUERY,
)


def _build_query_pdf(workflow_key: WorkflowKey, fields: dict[str, Any]) -> tuple[bytes, str] | None:
    """Build (pdf_bytes, filename) for any read-only query's output_format=
    "pdf" request, or None if `workflow_key` isn't one of the five query
    workflows this covers. Pure -- reads only the *_results/*_levels keys
    the relevant _seed_* function already seeded into `fields`, so this is
    testable without constructing a full inbound journey. See
    domains/reports/pdf_table.py (backend, imported in-process -- same
    convention runtime/dpr_request_query.py and friends use for their own
    repository calls) for the actual rendering."""
    if workflow_key not in _QUERY_PDF_WORKFLOW_KEYS:
        return None

    from mesiri.domains.reports.pdf_table import render_table_pdf

    if workflow_key is WorkflowKey.ACCOUNT_BALANCE_QUERY:
        balances = fields.get("balance_results") or []
        pdf_bytes = render_table_pdf(
            title="Account Balances",
            subtitle=None,
            columns=["Account", "Balance"],
            rows=[[b.get("name"), b.get("balance")] for b in balances],
            column_widths=[100, 80],
            empty_message="No matching accounts found.",
        )
        return pdf_bytes, "Account_Balances.pdf"

    if workflow_key is WorkflowKey.EXPENSE_QUERY:
        expense_results = fields.get("expense_results") or {}
        items = expense_results.get("items") or []
        label = expense_results.get("date_range_label") or "All Time"
        pdf_bytes = render_table_pdf(
            title="Expenses",
            subtitle=(
                f"{label}  |  {expense_results.get('count', 0)} expenses  |  "
                f"Total: {expense_results.get('total', '0')}"
            ),
            columns=["Date", "Amount", "Description"],
            rows=[
                [item.get("occurred_date"), item.get("amount"), item.get("description")]
                for item in items
            ],
            column_widths=[35, 35, 110],
            empty_message="No matching expenses found.",
        )
        return pdf_bytes, "Expenses.pdf"

    if workflow_key is WorkflowKey.MATERIAL_INVENTORY_QUERY:
        levels = fields.get("inventory_levels") or []
        pdf_bytes = render_table_pdf(
            title="Material Inventory",
            subtitle=None,
            columns=["Material", "Received", "Used", "Current Stock", "Unit"],
            rows=[
                [
                    lvl.get("material_name"),
                    lvl.get("received"),
                    lvl.get("used"),
                    lvl.get("current_stock"),
                    lvl.get("unit"),
                ]
                for lvl in levels
            ],
            column_widths=[60, 30, 30, 35, 25],
            empty_message="No recorded material stock found.",
        )
        return pdf_bytes, "Material_Inventory.pdf"

    if workflow_key is WorkflowKey.ACTIVITY_QUERY:
        results = fields.get("activity_search_results") or {}
        activities = results.get("activities") or []
        open_issues = results.get("open_issues") or []
        label = results.get("date_range_label") or "All Time"
        # Activities only, not open_issues -- render_table_pdf renders one
        # flat table; the issue count still appears in the subtitle, and the
        # text reply sent alongside this PDF already lists open issues.
        pdf_bytes = render_table_pdf(
            title="Site Activity Log",
            subtitle=(
                f"{label}  |  {results.get('activity_count', 0)} activities logged  |  "
                f"{results.get('open_issue_count', len(open_issues))} open issues"
            ),
            columns=["Date", "Work Type", "Narrative", "Status"],
            rows=[
                [a.get("activity_date"), a.get("work_type"), a.get("narrative"), a.get("status")]
                for a in activities
            ],
            column_widths=[30, 35, 80, 25],
            empty_message="No activities logged for this period.",
        )
        return pdf_bytes, "Site_Activity_Log.pdf"

    if workflow_key is WorkflowKey.PROJECT_DETAIL_QUERY:
        from mesiri.domains.reports.project_detail_pdf import render_project_detail_pdf_bytes

        results = fields.get("project_detail_results") or {}
        project = results.get("project") or {}
        site = results.get("site")
        finance = results.get("finance")
        pdf_bytes = render_project_detail_pdf_bytes(
            name=(site.get("name") if site else None) or project.get("name") or "Untitled",
            code=project.get("code"),
            location=project.get("location"),
            status=project.get("status"),
            sites=results.get("sites"),
            member_count=results.get("member_count"),
            open_issue_count=results.get("open_issue_count", 0),
            open_issues=results.get("open_issues") or [],
            headcount=results.get("headcount", 0),
            activity_count=results.get("activity_count", 0),
            labour_cost=results.get("labour_cost", "0"),
            expense_total=finance.get("total") if finance else None,
            expense_date_range_label=finance.get("date_range_label") if finance else None,
            stock_levels=results.get("stock_levels") or [],
        )
        filename = (site.get("name") if site else None) or project.get("name") or "Project"
        return pdf_bytes, f"{filename.replace(' ', '_')}_Details.pdf"

    labour_results = fields.get("labour_results") or {}
    rows = labour_results.get("rows") or []
    label = labour_results.get("date_range_label") or "All Time"
    pdf_bytes = render_table_pdf(
        title="Labour Attendance",
        subtitle=(
            f"{label}  |  {labour_results.get('headcount', 0)} worker-days  |  "
            f"Cost: {labour_results.get('total_cost', '0')}"
        ),
        columns=["Date", "Worker", "Trade", "Headcount", "Daily Wage"],
        rows=[
            [
                r.get("occurred_date"),
                r.get("worker_name"),
                r.get("trade"),
                r.get("headcount"),
                r.get("daily_wage"),
            ]
            for r in rows
        ],
        column_widths=[28, 45, 32, 25, 30],
        empty_message="No attendance recorded for this period.",
    )
    return pdf_bytes, "Labour_Attendance.pdf"
