"""Slot-seeding helpers: the `_seed_*` / `_run_*_gate` functions that resolve
fields against repositories before a workflow's graph runs, plus the material/
unit/project/site/stock gates and the worker-promotion follow-up flow."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from backend.ports import ActorIdentity
from canonicalization.occurred_date import today_for
from channel.replies import (
    ReplySpec,
)
from interactions.handler import InteractionHandled
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.canonical_event import IntentCompleteness as _IntentCompleteness
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import PlannerDecisionType, WorkflowKey
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from mesiri_contracts.common.ids import new_id as _new_id
from runtime.activity_query import ActivityQueryService
from runtime.activity_search_service import ActivitySearchService
from runtime.duplicate_expense_query import DuplicateExpenseQueryService
from runtime.expense_query_service import ExpenseQueryService, resolve_date_range
from runtime.inbound_journey._shared import _log
from runtime.inbound_journey.reply import _safe
from runtime.inventory_query import MaterialInventoryQueryService
from runtime.labour_query_service import (
    LabourQueryService,
)
from runtime.money_account_query import MoneyAccountQueryService
from runtime.org_settings_query import OrganizationSettingsQueryService
from runtime.project_detail_query import ProjectDetailQueryService
from runtime.reversal_query import (
    ADVANCE_ACCOUNT_TYPE,
    ReversalTargetQueryService,
    ReversalTransferTarget,
    advance_holder_name,
)
from runtime.save_first import company_saves_first
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








#: Marks which audience name the picker currently on screen is about, so the
#: resume leg can patch the right entry without re-deriving it. Only ever
#: present on a held event -- cleared before the automation is drafted, so it
#: never reaches CreateAutomationCommand.
AUDIENCE_PENDING_NAME_FIELD = "_audience_pending_name"












async def _add_period(
    event: CanonicalEventV2,
    inventory_query: MaterialInventoryQueryService,
    timezone_name: str | None,
) -> None:
    """MAT-03: "cement used today?", "received yesterday?", "this week?" are
    answered from the movements of that period (project zone), not from the
    all-time totals: each stock row gets ``period_received`` / ``period_used``
    and the event ``inventory_period`` (its label)."""
    from runtime.agent.project_day import project_zone_name, resolve_period

    zone = project_zone_name(timezone_name)
    period = resolve_period(event.fields.get("date_range"), event.fields.get("date"), zone)
    if period is None or not hasattr(inventory_query, "period_totals"):
        return
    start, end, label = period
    totals = await inventory_query.period_totals(
        organization_id=event.organization_id,
        project_id=event.project_id,
        site_id=event.site_id,
        start_date=start,
        end_date=end,
        timezone_name=zone,
    )
    for level in event.fields.get("inventory_levels") or []:
        moved = totals.pop((str(level["material_name"]).lower(), str(level["unit"])), None) or {}
        level["period_received"] = moved.get("received", 0.0)
        level["period_used"] = moved.get("used", 0.0)
    event.fields["inventory_period"] = {"label": label, "start": start.isoformat(), "end": end.isoformat()}


async def _inject_inventory_context(
    event: CanonicalEventV2,
    inventory_query: MaterialInventoryQueryService | None,
    timezone_name: str | None = None,
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
        await _add_period(event, inventory_query, timezone_name)
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
            # WA-77: the hint compares with what was reported, saved or not.
            include_unsaved=True,
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
    # Request 127 (P2): the day or period is the project's own, and the figures
    # come from the one read helper (runtime/agent/project_day.py), the same
    # one "what was done today?" and the "today so far" line read through.
    from runtime.agent.project_day import period_for, read_period, resolve_period

    today = today_for(timezone_name)
    period = resolve_period(event.fields.get("date_range"), event.fields.get("date"), timezone_name, today=today)
    period = period or period_for("today", today)
    read = await read_period(
        organization_id=actor.organization_id,
        project_id=event.project_id,
        site_id=event.site_id,
        period=period,
        labour_query=labour_query_service,
        trade=event.fields.get("trade"),
    )
    event.fields["labour_results"] = read["labour"]


async def _seed_activity_search(
    event: CanonicalEventV2,
    decision: PlannerDecisionV2,
    activity_search_service: ActivitySearchService | None,
    actor: ActorIdentity | None,
    timezone_name: str | None,
    labour_query_service: LabourQueryService | None = None,
    inventory_query: MaterialInventoryQueryService | None = None,
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

    # WRK-03: a named day or period ("yesterday") is the project's own.
    # Request 127 (P2): read through the one helper (project_day.read_period),
    # which also brings the day's labour -- "what was done today?" left out
    # the 8 workers counted for the day. Not when the question is about one
    # kind of work: labour is not part of that answer.
    from runtime.agent.project_day import period_for, project_zone_name, read_period, resolve_period

    today = today_for(timezone_name)
    period = resolve_period(event.fields.get("date_range"), event.fields.get("date"), timezone_name, today=today)
    period = period or period_for("today", today)
    work_type = event.fields.get("work_type")
    read = await read_period(
        organization_id=actor.organization_id,
        project_id=event.project_id,
        site_id=event.site_id,
        period=period,
        activity_search=activity_search_service,
        labour_query=None if work_type else labour_query_service,
        work_type=work_type,
    )
    results = read["work"]
    if read["labour"] and read["labour"].get("headcount"):
        results["labour"] = read["labour"]
    if not work_type and inventory_query is not None and hasattr(inventory_query, "period_totals"):
        # Request 136: the day's materials too, counted as the DPR counts them
        # (``period_totals``): "innu enthokke cheythu?" said "no work" over a card
        # that saved 30 bags of cement used.
        start, end, _label = period
        try:
            moved = await inventory_query.period_totals(
                organization_id=actor.organization_id,
                project_id=event.project_id,
                site_id=event.site_id,
                start_date=start,
                end_date=end,
                timezone_name=project_zone_name(timezone_name),
            )
        except Exception:  # noqa: BLE001 -- the answer stands without them
            _log.warning("activity_search.materials_failed", exc_info=True)
            moved = {}
        materials = [
            {"material": name, "unit": unit, "received": totals.get("received", 0.0), "used": totals.get("used", 0.0)}
            for (name, unit), totals in sorted(moved.items())
            if totals.get("received") or totals.get("used")
        ]
        if materials:
            results["materials"] = materials
    event.fields["activity_search_results"] = results


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
    from mesiri.authorization.roles import may_view_expenses

    # SEC-01: the money line follows the expense rule (it hid it from site
    # engineers only; a supervisor saw it).
    if expense_query_service is not None and may_view_expenses(actor.role):
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
    team_query: Any | None = None,
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
    alone: bool | None = None
    if stage == "member" and team_query is not None:
        # [111]: count who is on the project before saying anything about its
        # team; with someone besides the sender there is nothing to offer.
        others = await team_query.count_other_members(project_id=project_id, user_id=user_id)
        if others:
            return False
        alone = True if others == 0 else None
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
        else render_project_member_offer(alone)
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




def _within_own_projects(expenses: list[Any], actor: ActorIdentity) -> list[Any]:
    """SEC-01: only the expenses of the sender's own projects. A company-wide
    expense (no project) only for someone who reaches every project."""
    from mesiri.authorization.roles import role_is_org_wide

    own = {str(project.id) for project in actor.projects or []}
    org_wide = role_is_org_wide(actor.role)
    return [
        expense
        for expense in expenses
        if (str(expense.project_id) in own if expense.project_id is not None else org_wide)
    ]


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
        from mesiri.authorization.roles import may_view_expenses

        if not may_view_expenses(actor.role):
            # SEC-01: the same rule as the dashboard's expense pages.
            event.fields["expense_denied"] = True
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
        expenses = _within_own_projects(expenses, actor)
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


#: Column widths (mm) of each table's PDF; the image card sizes its own.
_PDF_COLUMN_WIDTHS: dict[WorkflowKey, list[float]] = {
    WorkflowKey.ACCOUNT_BALANCE_QUERY: [100, 80],
    WorkflowKey.EXPENSE_QUERY: [35, 35, 110],
    WorkflowKey.MATERIAL_INVENTORY_QUERY: [60, 30, 30, 35, 25],
    WorkflowKey.ACTIVITY_QUERY: [30, 35, 80, 25],
    WorkflowKey.LABOUR_QUERY: [28, 45, 32, 25, 30],
}


def _query_table(
    workflow_key: WorkflowKey, fields: dict[str, Any]
) -> tuple[str, str | None, list[str], list[list[Any]], str, str] | None:
    """The one table a read-only lookup shows as a PDF or an image:
    ``(title, subtitle, columns, rows, empty_message, filename_stem)``, or None
    when the workflow has no flat table (the project detail is its own
    layout). Pure -- reads only the *_results/*_levels keys the _seed_*
    functions already put in ``fields``. Both renderers (``_build_query_pdf``
    and the image cards) call this, so they always show the same rows."""
    if workflow_key is WorkflowKey.ACCOUNT_BALANCE_QUERY:
        balances = fields.get("balance_results") or []
        return (
            "Account Balances",
            None,
            ["Account", "Balance"],
            [[b.get("name"), b.get("balance")] for b in balances],
            "No matching accounts found.",
            "Account_Balances",
        )

    if workflow_key is WorkflowKey.EXPENSE_QUERY:
        expense_results = fields.get("expense_results") or {}
        items = expense_results.get("items") or []
        label = expense_results.get("date_range_label") or "All Time"
        return (
            "Expenses",
            (
                f"{label}  |  {expense_results.get('count', 0)} expenses  |  "
                f"Total: {expense_results.get('total', '0')}"
            ),
            ["Date", "Amount", "Description"],
            [[i.get("occurred_date"), i.get("amount"), i.get("description")] for i in items],
            "No matching expenses found.",
            "Expenses",
        )

    if workflow_key is WorkflowKey.MATERIAL_INVENTORY_QUERY:
        levels = fields.get("inventory_levels") or []
        return (
            "Material Inventory",
            None,
            ["Material", "Received", "Used", "Current Stock", "Unit"],
            [
                [lvl.get("material_name"), lvl.get("received"), lvl.get("used"), lvl.get("current_stock"), lvl.get("unit")]
                for lvl in levels
            ],
            "No recorded material stock found.",
            "Material_Inventory",
        )

    if workflow_key is WorkflowKey.ACTIVITY_QUERY:
        results = fields.get("activity_search_results") or {}
        activities = results.get("activities") or []
        open_issues = results.get("open_issues") or []
        label = results.get("date_range_label") or "All Time"
        # Activities only, not open_issues: one flat table; the issue count
        # still appears in the subtitle, and the text reply already lists them.
        return (
            "Site Activity Log",
            (
                f"{label}  |  {results.get('activity_count', 0)} activities logged  |  "
                f"{results.get('open_issue_count', len(open_issues))} open issues"
            ),
            ["Date", "Work Type", "Narrative", "Status"],
            [[a.get("activity_date"), a.get("work_type"), a.get("narrative"), a.get("status")] for a in activities],
            "No activities logged for this period.",
            "Site_Activity_Log",
        )

    if workflow_key is WorkflowKey.LABOUR_QUERY:
        labour_results = fields.get("labour_results") or {}
        rows = labour_results.get("rows") or []
        label = labour_results.get("date_range_label") or "All Time"
        return (
            "Labour Attendance",
            (
                f"{label}  |  {labour_results.get('headcount', 0)} worker-days  |  "
                f"Cost: {labour_results.get('total_cost', '0')}"
            ),
            ["Date", "Worker", "Trade", "Headcount", "Daily Wage"],
            [
                [r.get("occurred_date"), r.get("worker_name"), r.get("trade"), r.get("headcount"), r.get("daily_wage")]
                for r in rows
            ],
            "No attendance recorded for this period.",
            "Labour_Attendance",
        )
    return None


def _build_query_pdf(workflow_key: WorkflowKey, fields: dict[str, Any]) -> tuple[bytes, str] | None:
    """Build (pdf_bytes, filename) for any read-only query's output_format=
    "pdf" request, or None if `workflow_key` isn't one of the query
    workflows this covers. The table comes from ``_query_table`` (shared with
    the image cards); see domains/reports/pdf_table.py (backend, imported
    in-process -- same convention runtime/dpr_request_query.py and friends use
    for their own repository calls) for the rendering."""
    if workflow_key not in _QUERY_PDF_WORKFLOW_KEYS:
        return None

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

    from mesiri.domains.reports.pdf_table import render_table_pdf

    table = _query_table(workflow_key, fields)
    if table is None:
        return None
    title, subtitle, columns, rows, empty_message, stem = table
    pdf_bytes = render_table_pdf(
        title=title,
        subtitle=subtitle,
        columns=columns,
        rows=rows,
        column_widths=_PDF_COLUMN_WIDTHS[workflow_key],
        empty_message=empty_message,
    )
    return pdf_bytes, f"{stem}.pdf"
