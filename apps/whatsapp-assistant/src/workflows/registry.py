"""Workflow Registry — the lookup layer between Planner and LangGraph.

Planner never imports a workflow engine or a specific graph (architecture rule
#10); it returns only a workflow_key. This registry resolves that key to a
compiled graph. Graphs are compiled once and cached — a WhatsApp message must
never trigger a graph recompilation.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Any

from mesiri_contracts.assistant.planner_decision import WorkflowKey

from .account_admin.graph import build_account_admin_graph
from .account_balance_query.graph import build_account_balance_query_graph
from .activity_correction.graph import build_activity_correction_graph
from .activity_query.graph import build_activity_query_graph
from .add_project_member.graph import build_add_project_member_graph
from .automation_setup.graph import build_automation_setup_graph
from .create_user.graph import build_create_user_graph
from .dpr_request.graph import build_dpr_request_graph
from .entities import EntityType
from .expense_capture.graph import build_expense_capture_graph
from .expense_query.graph import build_expense_query_graph
from .labour_query.graph import build_labour_query_graph
from .labour_update.graph import build_labour_attendance_graph
from .material import build_material_graph
from .material_inventory_query.graph import build_material_inventory_query_graph
from .petty_cash.graph import build_petty_cash_graph
from .project_create.graph import build_project_create_graph
from .project_detail_query.graph import build_project_detail_query_graph
from .reverse.graph import build_reverse_graph
from .site_create.graph import build_site_create_graph
from .site_issue_close.graph import build_site_issue_close_graph
from .site_issue_report.graph import build_site_issue_report_graph
from .site_update.graph import build_activity_creation_graph
from .transfer.graph import build_transfer_graph
from .who_am_i.graph import build_who_am_i_graph
from .worker_promotion.graph import build_worker_promotion_graph


class WorkflowCategory(str, Enum):
    """Business domain a workflow belongs to.

    Registry-local metadata, deliberately *not* in mesiri_contracts: no
    Planner/Runtime contract crosses this boundary, so it must not become a
    wire-level enum that other services can couple to.
    """

    FINANCE = "finance"
    MATERIAL = "material"
    LABOUR = "labour"
    IDENTITY = "identity"
    PROGRESS = "progress"
    PROJECT = "project"
    AUTOMATION = "automation"


# Meta Cloud API list-row caps, duplicated from channel/whatsapp/outbound.py
# rather than imported: channel.replies imports this module to build the menu,
# so importing back into channel from here would close an import cycle. The
# transport still enforces its own limits -- these exist so a violation fails
# at import time with the offending workflow named, instead of reaching a user
# as a truncated row.
_ROW_TITLE_MAX_CHARS = 24
_ROW_DESCRIPTION_MAX_CHARS = 72


@dataclass(frozen=True)
class WorkflowDefinition:
    """Everything the system knows about one workflow, in one place.

    Fields beyond ``builder`` carry no behaviour on their own -- they are the
    single source of truth that behavioural call sites read from, so that
    adding a workflow means editing one table rather than hunting down
    per-key sets scattered across modules.
    """

    key: WorkflowKey
    builder: Callable[[], Any]
    category: WorkflowCategory
    # -- User-facing copy -----------------------------------------------
    # Every capability surface (the WhatsApp category menu, the "I can't do
    # that yet" reply, the control panel's workflow table) renders from
    # these three fields and never from its own hand-written list. Before
    # they existed, four separate lists described the same 26 workflows and
    # all four had drifted -- render_unsupported_reply() still told users
    # "I can only record material updates right now" a year after finance,
    # labour, and progress shipped.
    #
    # `title` is a WhatsApp list-row title (hard cap 24 chars) and
    # `one_liner` its description (72) -- see channel/whatsapp/outbound.py.
    # Both are validated below rather than silently truncated at send time.
    title: str
    one_liner: str
    examples: tuple[str, ...]
    # The one-shot extraction bias set when this workflow's menu row is
    # tapped (see runtime/message_journey.py's category-tap branch). None
    # for a workflow a user can never pick from the menu.
    semantic_hint: str | None = None
    # False for a workflow only the system starts, never a user -- it is
    # excluded from every discovery surface. WORKER_PROMOTION is the only
    # one today: inbound_journey.py creates its instance directly after a
    # confirmed attendance names new temporary workers.
    user_initiable: bool = True
    # Overrides the derived "wf_<key>" menu row id. Only the material pair
    # sets this, reusing the ids the Arrived/Used direction-lock handler
    # already owns (interactions/handler.py's handle_material_direction_tap)
    # so a tap from the tiered menu locks direction exactly as the old
    # two-step material tap did.
    menu_row_id_override: str | None = None
    # Roles this workflow is worth *showing* to, or None for everyone.
    #
    # Discovery metadata only -- this is NOT the enforcement gate and must
    # never be mistaken for one. The real gates live at each entry point
    # (runtime/inbound_journey/process.py's _ACCOUNT_ADMIN_ROLES and
    # _PROJECT_CREATE_ROLES, projects/router.py's _CREATE_ROLES,
    # application/*/validation.py) and are deliberately kept as independent
    # literals per module -- see process.py:96, which explains why those
    # entry points do not share one constant. This field mirrors them for
    # one purpose: not teaching a site engineer a workflow that will refuse
    # them. If it drifts, a menu row is wrong; nothing becomes permitted
    # that was not already permitted.
    #
    # AUTOMATION_SETUP is deliberately open despite having a role gate: the
    # gate is conditional (a reminder aimed at yourself is open to anyone,
    # only targeting *others* is restricted), so hiding it entirely would
    # deny everyone the half they are allowed.
    allowed_roles: frozenset[str] | None = None
    # Only answers a question; never produces a draft_action. Exempt from the
    # single-active pending-confirmation gate and completes without
    # AWAITING_CONFIRMATION. See workflows/runtime.py.
    is_informational: bool = False
    # May *sometimes* finish with no draft_action without that being a
    # failure. Implied by is_informational; also set on the mixed cases
    # (REVERSE, EXPENSE_SUBMIT, ACCOUNT_ADMIN) which still write a record most
    # of the time and so still respect the single-active gate.
    allows_completion_without_draft: bool = False
    # -- Composite-request / entity-resolution spine ---------------------
    # docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md §4.1 and
    # docs/execution/ENTITY_RESOLUTION_PLAN.md §3.2 -- one declaration, two
    # readers. The entity-resolution layer reads `provides` backwards ("a
    # USER is missing -- which workflow provides one?", workflow_that_
    # provides below). The composite-request plan layer orders steps from
    # the explicit StepRefs a decomposer emits, not from this field directly
    # (see workflows/planning/ordering.py's docstring) -- `requires` here is
    # documentation of what a bare (non-plan) run of this workflow needs
    # resolved before it can proceed, e.g. for role/capability display.
    #
    # Empty for every workflow that neither produces nor consumes a named
    # entity another workflow could supply (queries, corrections, finance
    # capture) -- most of the table leaves both at the default.
    provides: frozenset[EntityType] = frozenset()
    requires: frozenset[EntityType] = frozenset()

    @property
    def menu_row_id(self) -> str:
        """The interactive row id that selects this workflow from the menu."""
        return self.menu_row_id_override or f"wf_{self.key.value}"

    def __post_init__(self) -> None:
        if self.is_informational and not self.allows_completion_without_draft:
            raise ValueError(
                f"{self.key}: an informational workflow never produces a draft, "
                "so allows_completion_without_draft must be True"
            )
        # Caught at import time, not at send time: a row that exceeds these
        # is truncated mid-word by Meta rather than rejected, so the damage
        # is silent and user-visible.
        if len(self.title) > _ROW_TITLE_MAX_CHARS:
            raise ValueError(
                f"{self.key}: title is {len(self.title)} chars, "
                f"over WhatsApp's {_ROW_TITLE_MAX_CHARS}-char list-row limit"
            )
        if len(self.one_liner) > _ROW_DESCRIPTION_MAX_CHARS:
            raise ValueError(
                f"{self.key}: one_liner is {len(self.one_liner)} chars, "
                f"over WhatsApp's {_ROW_DESCRIPTION_MAX_CHARS}-char limit"
            )
        if self.user_initiable and not self.examples:
            raise ValueError(
                f"{self.key}: a user-pickable workflow needs at least one "
                "example message -- it is what the menu shows after the tap"
            )


def _define(
    key: WorkflowKey,
    builder: Callable[[], Any],
    category: WorkflowCategory,
    *,
    title: str,
    one_liner: str,
    examples: tuple[str, ...] = (),
    semantic_hint: str | None = None,
    user_initiable: bool = True,
    menu_row_id_override: str | None = None,
    allowed_roles: frozenset[str] | None = None,
    is_informational: bool = False,
    allows_completion_without_draft: bool = False,
    provides: frozenset[EntityType] = frozenset(),
    requires: frozenset[EntityType] = frozenset(),
) -> tuple[WorkflowKey, WorkflowDefinition]:
    """Build a (key, definition) pair, keeping the table below readable.

    ``title``/``one_liner`` are keyword-required with no default so that a
    new workflow cannot be registered without the copy every discovery
    surface needs -- the drift this table exists to prevent starts with one
    workflow that nothing knows how to describe.
    """
    return key, WorkflowDefinition(
        key=key,
        builder=builder,
        category=category,
        title=title,
        one_liner=one_liner,
        examples=examples,
        semantic_hint=semantic_hint,
        user_initiable=user_initiable,
        menu_row_id_override=menu_row_id_override,
        allowed_roles=allowed_roles,
        is_informational=is_informational,
        # Informational implies it; spelled out here so the table stays flat.
        allows_completion_without_draft=allows_completion_without_draft or is_informational,
        provides=provides,
        requires=requires,
    )


_DEFINITIONS: dict[WorkflowKey, WorkflowDefinition] = dict(
    (
        _define(
            WorkflowKey.MATERIAL_RECEIPT,
            build_material_graph,
            WorkflowCategory.MATERIAL,
            title="Material Arrived",
            one_liner="Record material delivered to site",
            examples=("50 bags of cement arrived",),
            semantic_hint="material_update",
            # See menu_row_id_override's note on WorkflowDefinition: these two
            # ids predate the tiered menu and are owned by the direction-lock
            # handler, which must keep seeing them.
            menu_row_id_override="dir_received",
        ),
        _define(
            WorkflowKey.MATERIAL_USAGE,
            build_material_graph,
            WorkflowCategory.MATERIAL,
            title="Material Used",
            one_liner="Record material consumed in work",
            examples=("20 bags of cement used for the foundation",),
            semantic_hint="material_update",
            menu_row_id_override="dir_used",
        ),
        _define(
            WorkflowKey.WHO_AM_I,
            build_who_am_i_graph,
            WorkflowCategory.IDENTITY,
            title="My Profile",
            one_liner="See who you are and what you can do here",
            examples=("Who am I?", "Which project am I on?", "Which sites do I have?"),
            semantic_hint="whoami_question",
            is_informational=True,
        ),
        _define(
            WorkflowKey.MATERIAL_INVENTORY_QUERY,
            build_material_inventory_query_graph,
            WorkflowCategory.MATERIAL,
            title="Material Stock",
            one_liner="Ask what is in stock or what moved",
            examples=("How much cement is left?", "Show current material stock"),
            semantic_hint="inventory_query",
            is_informational=True,
        ),
        _define(
            WorkflowKey.EXPENSE_SUBMIT,
            build_expense_capture_graph,
            WorkflowCategory.FINANCE,
            title="Record Expense",
            one_liner="Log money spent, with an optional receipt photo",
            examples=("Paid 1500 to ABC Hardware",),
            semantic_hint="expense",
            allows_completion_without_draft=True,
        ),
        _define(
            WorkflowKey.ACCOUNT_ADMIN,
            build_account_admin_graph,
            WorkflowCategory.FINANCE,
            title="Manage Accounts",
            one_liner="Create or rename a cash or bank account",
            examples=("Rename Main HDFC Account to Office Cash",),
            semantic_hint="account_admin",
            # Mirrors process.py's _ACCOUNT_ADMIN_ROLES.
            allowed_roles=frozenset({"ADMIN", "FINANCE"}),
            allows_completion_without_draft=True,
        ),
        _define(
            WorkflowKey.ACCOUNT_BALANCE_QUERY,
            build_account_balance_query_graph,
            WorkflowCategory.FINANCE,
            title="Account Balance",
            one_liner="Ask how much is left in an account",
            examples=("What is the balance in Site Cash?",),
            semantic_hint="finance_query",
            is_informational=True,
        ),
        _define(
            WorkflowKey.EXPENSE_QUERY,
            build_expense_query_graph,
            WorkflowCategory.FINANCE,
            title="Expense Report",
            one_liner="Ask what was spent, and on what",
            examples=("How much did we spend on diesel this month?",),
            semantic_hint="finance_query",
            is_informational=True,
        ),
        _define(
            WorkflowKey.TRANSFER,
            build_transfer_graph,
            WorkflowCategory.FINANCE,
            title="Transfer Money",
            one_liner="Move money between two of your own accounts",
            examples=("Transfer 50000 from Company Account to Site Cash",),
            semantic_hint="transfer",
        ),
        _define(
            WorkflowKey.PETTY_CASH,
            build_petty_cash_graph,
            WorkflowCategory.FINANCE,
            title="Petty Cash",
            one_liner="Issue or take back petty cash for a person",
            examples=("Give 20000 petty cash to Alan", "Alan returns 3000"),
            semantic_hint="petty_cash",
        ),
        _define(
            WorkflowKey.REVERSE,
            build_reverse_graph,
            WorkflowCategory.FINANCE,
            title="Undo a Record",
            one_liner="Reverse an expense or transfer recorded by mistake",
            examples=("Reverse my last expense",),
            semantic_hint="reversal",
            allows_completion_without_draft=True,
        ),
        _define(
            WorkflowKey.LABOUR_ATTENDANCE,
            build_labour_attendance_graph,
            WorkflowCategory.LABOUR,
            title="Labour Attendance",
            one_liner="Record headcount and who worked today",
            examples=("12 masons on site today",),
            semantic_hint="labour_update",
        ),
        _define(
            WorkflowKey.LABOUR_QUERY,
            build_labour_query_graph,
            WorkflowCategory.LABOUR,
            title="Labour Report",
            one_liner="Ask about attendance and worker history",
            examples=("How many workers came this week?",),
            semantic_hint="labour_query",
            is_informational=True,
        ),
        # Handles both "start a new Activity" and "append a Progress Update
        # to an existing one" -- the separate WorkflowKey.ACTIVITY_
        # CONTINUATION registry entry was retired when the two were merged
        # (docs/execution/ACTIVITY_RESOLUTION_AND_CORRECTION_PLAN.md): which
        # of the two a message means is now decided inside the graph itself
        # (workflows/site_update/nodes.py's resolve_target), not by routing
        # to a different WorkflowKey. The contract enum member
        # WorkflowKey.ACTIVITY_CONTINUATION still exists for old persisted
        # workflow_state rows; nothing produces it any more.
        _define(
            WorkflowKey.SITE_UPDATE,
            build_activity_creation_graph,
            WorkflowCategory.PROGRESS,
            title="Site Progress",
            one_liner="Report work done or progress on an activity",
            examples=("Concrete pour finished on the 3rd floor",),
            semantic_hint="general_site_update",
            requires=frozenset({EntityType.PROJECT, EntityType.SITE}),
            provides=frozenset({EntityType.ACTIVITY}),
        ),
        _define(
            WorkflowKey.ACTIVITY_CORRECTION,
            build_activity_correction_graph,
            WorkflowCategory.PROGRESS,
            title="Fix Last Update",
            one_liner="Correct a quantity you just reported",
            examples=("Actually it was 40 sqm, not 30",),
            semantic_hint="activity_correction",
            # "Nothing to correct" (no same-session activity to target,
            # ADR-D14/D15's shared same-session scoping) is a legitimate
            # no-draft completion, same reasoning as REVERSE.
            allows_completion_without_draft=True,
        ),
        _define(
            WorkflowKey.WORKER_PROMOTION,
            build_worker_promotion_graph,
            WorkflowCategory.LABOUR,
            title="Add to Worker Register",
            one_liner="Save newly named temporary workers to the register",
            # System-triggered only, so it carries no example and never
            # reaches a menu -- see user_initiable on WorkflowDefinition.
            user_initiable=False,
            # Never produces a DraftActionV2. Writes the Worker Register
            # directly inside the node (via a callable seeded by the caller),
            # which is intentional: the user's selection IS the confirmation.
            is_informational=True,
        ),
        _define(
            WorkflowKey.ACTIVITY_QUERY,
            build_activity_query_graph,
            WorkflowCategory.PROGRESS,
            title="Progress Report",
            one_liner="Ask what was logged, or what is still open",
            examples=("What did I log today?", "Any open issues on Block A?"),
            semantic_hint="activity_query",
            is_informational=True,
        ),
        _define(
            WorkflowKey.DPR_REQUEST,
            build_dpr_request_graph,
            WorkflowCategory.PROGRESS,
            title="Daily Report",
            one_liner="Get today's daily progress report as a document",
            examples=("Send me today's DPR",),
            semantic_hint="dpr_request",
            is_informational=True,
        ),
        _define(
            WorkflowKey.SITE_ISSUE_REPORT,
            build_site_issue_report_graph,
            WorkflowCategory.PROGRESS,
            title="Report an Issue",
            one_liner="Flag a blocker or delay that is holding up work",
            examples=("Ran out of cement, work stopped",),
            semantic_hint="site_issue",
        ),
        _define(
            WorkflowKey.SITE_ISSUE_CLOSE,
            build_site_issue_close_graph,
            WorkflowCategory.PROGRESS,
            title="Update an Issue",
            one_liner="Mark a blocker sorted, withdraw it, or reopen it",
            examples=(
                "The cement issue is sorted",
                "Ignore that issue, I reported it on the wrong site",
                "That's not fixed, reopen it",
            ),
            semantic_hint="site_issue_update",
            allows_completion_without_draft=True,
        ),
        _define(
            WorkflowKey.PROJECT_CREATE,
            build_project_create_graph,
            WorkflowCategory.PROJECT,
            title="New Project",
            one_liner="Set up a new project",
            examples=("Create a new project called Skyline Towers",),
            semantic_hint="project_create",
            # Mirrors process.py's _PROJECT_CREATE_ROLES.
            allowed_roles=frozenset({"ADMIN", "PROJECT_MANAGER"}),
            allows_completion_without_draft=True,
            provides=frozenset({EntityType.PROJECT}),
        ),
        _define(
            WorkflowKey.SITE_CREATE,
            build_site_create_graph,
            WorkflowCategory.PROJECT,
            title="New Site",
            one_liner="Add a site under an existing project",
            examples=("Create a new site called Block A",),
            semantic_hint="site_create",
            # Mirrors process.py's _PROJECT_CREATE_ROLES (same set gates both).
            allowed_roles=frozenset({"ADMIN", "PROJECT_MANAGER"}),
            allows_completion_without_draft=True,
            requires=frozenset({EntityType.PROJECT}),
            provides=frozenset({EntityType.SITE}),
        ),
        _define(
            WorkflowKey.PROJECT_DETAIL_QUERY,
            build_project_detail_query_graph,
            WorkflowCategory.PROJECT,
            title="Project Info",
            one_liner="Get the full status of a project or site",
            examples=("Give me all details of Skyline Towers",),
            semantic_hint="project_detail_query",
            is_informational=True,
        ),
        _define(
            WorkflowKey.ADD_PROJECT_MEMBER,
            build_add_project_member_graph,
            WorkflowCategory.PROJECT,
            title="Add a Teammate",
            one_liner="Give an existing teammate access to a project",
            examples=("Add Rajesh to Skyline Towers as site engineer",),
            semantic_hint="add_project_member",
            # Mirrors process.py's _PROJECT_CREATE_ROLES (same set gates all three).
            allowed_roles=frozenset({"ADMIN", "PROJECT_MANAGER"}),
            allows_completion_without_draft=True,
            requires=frozenset({EntityType.USER, EntityType.PROJECT}),
            provides=frozenset({EntityType.MEMBERSHIP}),
        ),
        _define(
            WorkflowKey.CREATE_USER,
            build_create_user_graph,
            WorkflowCategory.PROJECT,
            title="Add a New User",
            one_liner="Give a new person their own WhatsApp access",
            examples=("Add Rajesh, 9198765xxxxx, as site engineer",),
            semantic_hint="create_user",
            # Mirrors process.py's _PROJECT_CREATE_ROLES (same set gates all four).
            allowed_roles=frozenset({"ADMIN", "PROJECT_MANAGER"}),
            allows_completion_without_draft=True,
            provides=frozenset({EntityType.USER}),
        ),
        _define(
            WorkflowKey.AUTOMATION_SETUP,
            build_automation_setup_graph,
            WorkflowCategory.AUTOMATION,
            title="Set a Reminder",
            one_liner="Schedule a recurring reminder or report",
            examples=("Every day at 5pm remind me to submit the DPR",),
            semantic_hint="automation_setup",
            # "time_of_day wasn't extracted" (build_draft's own clarifying
            # reply) is a legitimate no-draft completion, same reasoning as
            # SITE_CREATE's missing-name case.
            allows_completion_without_draft=True,
        ),
    )
)


def get_definition(key: WorkflowKey) -> WorkflowDefinition | None:
    """Return the definition for ``key``, or None if the workflow isn't built yet."""
    return _DEFINITIONS.get(key)


def is_implemented(key: WorkflowKey) -> bool:
    """True when ``key`` has a graph wired up (some WorkflowKeys are declared but unbuilt)."""
    return key in _DEFINITIONS


def iter_definitions() -> Iterator[WorkflowDefinition]:
    """Every registered workflow, in registration order."""
    return iter(_DEFINITIONS.values())


def workflow_that_provides(entity_type: EntityType) -> WorkflowKey | None:
    """The workflow that creates ``entity_type``, or None if nothing does.

    Read "backwards" by the entity-resolution layer
    (docs/execution/ENTITY_RESOLUTION_PLAN.md §3.2): a workflow blocked on a
    Missing USER looks this up to find CREATE_USER, without either module
    naming the other. Assumes at most one provider per EntityType -- true for
    every member declared today; a genuine second provider would need this
    to return a tuple, not a single key, so it fails loudly rather than
    picking arbitrarily if that ever changes.
    """
    providers = [d.key for d in _DEFINITIONS.values() if entity_type in d.provides]
    if not providers:
        return None
    if len(providers) > 1:
        raise ValueError(
            f"{entity_type}: more than one workflow declares it in `provides` "
            f"({providers}) -- workflow_that_provides assumes exactly one"
        )
    return providers[0]


# Which product module (backend domains/organizations/settings.py's MODULES)
# each category belongs to, for the per-company module switch (V1 tracker
# BE-06). None = not a module: every company always has it. The strings are
# checked against the backend catalogue in tests rather than imported, so this
# lookup layer keeps depending on contracts only.
_CATEGORY_MODULES: dict[WorkflowCategory, str | None] = {
    WorkflowCategory.PROGRESS: "dpr",
    WorkflowCategory.LABOUR: "labour",
    WorkflowCategory.MATERIAL: "materials",
    WorkflowCategory.FINANCE: "finance",
    WorkflowCategory.AUTOMATION: "automations",
    WorkflowCategory.PROJECT: None,
    WorkflowCategory.IDENTITY: None,
}

# Workflows whose category doesn't say which module they act on. REVERSE is
# filed under FINANCE but also undoes attendance and activities, so gating it
# on finance would block V1 corrections; whether its *target* is available is
# for the caller to check against the record being reversed.
_MODULE_OVERRIDES: dict[WorkflowKey, str | None] = {
    WorkflowKey.REVERSE: None,
}


def module_for_workflow(key: WorkflowKey) -> str | None:
    """The module a company needs switched on to use ``key``, or None when the
    workflow is always available (or isn't registered)."""
    if key in _MODULE_OVERRIDES:
        return _MODULE_OVERRIDES[key]
    definition = _DEFINITIONS.get(key)
    if definition is None:
        return None
    return _CATEGORY_MODULES[definition.category]


def is_informational(key: WorkflowKey) -> bool:
    """True if ``key`` only answers a question and never produces a draft_action.

    False (not raise) for an unregistered key, so callers can use this as a
    plain predicate without checking is_implemented() first."""
    definition = _DEFINITIONS.get(key)
    return definition is not None and definition.is_informational


# ---------------------------------------------------------------------------
# Discovery surface
# ---------------------------------------------------------------------------

# Display copy for the top level of the tiered menu, in the order shown.
# Ordered by how often a site user needs each one, not alphabetically:
# material and progress are the daily path, identity is the rarest.
# WhatsApp caps a list at 10 rows -- with 7 categories there is room for
# exactly three more before the top level itself has to split.
_CATEGORY_DISPLAY: tuple[tuple[WorkflowCategory, str, str], ...] = (
    (WorkflowCategory.MATERIAL, "Material", "Deliveries, usage and stock"),
    (WorkflowCategory.PROGRESS, "Site Progress", "Work done, issues and daily reports"),
    (WorkflowCategory.LABOUR, "Labour", "Attendance and worker reports"),
    (WorkflowCategory.FINANCE, "Money", "Expenses, transfers, balances, petty cash"),
    (WorkflowCategory.PROJECT, "Projects & Team", "Projects, sites and who can see them"),
    (WorkflowCategory.AUTOMATION, "Reminders", "Scheduled reminders and reports"),
    (WorkflowCategory.IDENTITY, "My Profile", "Who you are and what you can do"),
)

CATEGORY_ROW_PREFIX = "cat_"


@dataclass(frozen=True, slots=True)
class MenuCategory:
    """One top-level row of the tiered capability menu."""

    category: WorkflowCategory
    row_id: str
    title: str
    one_liner: str


def _visible_to(definition: WorkflowDefinition, role: str | None) -> bool:
    """Whether ``role`` should be *shown* this workflow.

    ``role=None`` means "don't filter" -- used by the control panel and by
    any caller that has no actor in hand. An unknown role string is treated
    as restricted for gated workflows: showing too little degrades to a menu
    that is merely incomplete, showing too much degrades to teaching someone
    a workflow that will refuse them.
    """
    if not definition.user_initiable:
        return False
    if role is None or definition.allowed_roles is None:
        return True
    return role.upper() in definition.allowed_roles


def _menu_categories(role: str | None = None) -> tuple[MenuCategory, ...]:
    """Categories that have at least one workflow a user can actually pick.

    Derived, not hand-listed: a category whose workflows are all unbuilt or
    all system-triggered simply never appears. This is what keeps the menu
    from advertising a dead end -- the pre-registry menu offered an
    "Equipment & Machinery" row for a graph that was never built, so tapping
    it walked the user into the "not supported yet" reply.
    """
    return tuple(
        MenuCategory(
            category=category,
            row_id=f"{CATEGORY_ROW_PREFIX}{category.value}",
            title=title,
            one_liner=one_liner,
        )
        for category, title, one_liner in _CATEGORY_DISPLAY
        if any(d.category is category and _visible_to(d, role) for d in _DEFINITIONS.values())
    )


def iter_menu_categories(role: str | None = None) -> tuple[MenuCategory, ...]:
    """The top level of the tiered menu, in display order.

    A category with nothing ``role`` may pick simply doesn't appear -- so a
    SITE_ENGINEER never taps "Projects & Team" only to find it empty.
    """
    return _menu_categories(role)


def menu_category_by_row_id(row_id: str) -> MenuCategory | None:
    """Resolve a tapped top-level row id, or None if it isn't one.

    Deliberately unfiltered: this only says which category a row id names.
    Whether the tapper may see anything inside it is decided by
    user_initiable_in(), which takes the role.
    """
    return next((c for c in _menu_categories() if c.row_id == row_id), None)


def user_initiable_in(
    category: WorkflowCategory, role: str | None = None
) -> tuple[WorkflowDefinition, ...]:
    """Every workflow ``role`` can pick within ``category``, registration order."""
    return tuple(
        d for d in _DEFINITIONS.values() if d.category is category and _visible_to(d, role)
    )


def iter_user_initiable(role: str | None = None) -> tuple[WorkflowDefinition, ...]:
    """Every workflow ``role`` can pick, across all categories."""
    return tuple(d for d in _DEFINITIONS.values() if _visible_to(d, role))


def definition_by_menu_row_id(row_id: str) -> WorkflowDefinition | None:
    """Resolve a tapped workflow row id, or None if it isn't one.

    Unfiltered by role for the same reason menu_category_by_row_id is: this
    resolves an id to a definition. Role decides what gets *offered*; the
    real gate at the entry point decides what gets *run* (see allowed_roles).
    """
    return next(
        (d for d in _DEFINITIONS.values() if d.user_initiable and d.menu_row_id == row_id),
        None,
    )


def allows_completion_without_draft(key: WorkflowKey) -> bool:
    """True if ``key`` may legitimately finish with no draft_action."""
    definition = _DEFINITIONS.get(key)
    return definition is not None and definition.allows_completion_without_draft


class WorkflowRegistry:
    """Resolves a WorkflowKey to a compiled graph, compiling (and caching) on first use."""

    def __init__(self) -> None:
        self._compiled: dict[WorkflowKey, Any] = {}

    def get_graph(self, key: WorkflowKey) -> Any | None:
        """Return the compiled graph for ``key``, or None if unmapped.

        Compiled exactly once per key for the lifetime of this registry —
        callers must not construct a new WorkflowRegistry per message.
        """
        if key in self._compiled:
            return self._compiled[key]
        definition = _DEFINITIONS.get(key)
        if definition is None:
            return None
        graph = definition.builder()
        self._compiled[key] = graph
        return graph
