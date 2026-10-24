"""CanonicalEvent.v1 — the normalized business-intent signal between Context and Planner.

Produced by the canonicalization layer from an ``UnderstandingResult`` +
``ResolvedContext``. A CanonicalEvent is an internal orchestration signal, not a
confirmed fact — e.g. ``MaterialReceiptRequested`` means "the assistant believes
the user wants to record a material receipt." The user may still correct it, the
workflow may reject it, authorization may fail. This is never a ``DomainEvent``
(a confirmed fact, published only after commit).

Per the architecture's layer-ownership table, CanonicalEvent normalizes AI
output into business intent but must never carry knowledge of AI providers or
confidence scores. ``completeness`` is therefore a business-level judgement
(are the required fields present?) — the raw M3 ``ConfidenceLevel`` is
deliberately not represented here.

Ownership: SHARED ARCHITECTURE — part of the M0 contract surface. Version: v1.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

CONTRACT_VERSION = "v1"


class CanonicalEventType(str, Enum):
    """The normalized business intent the assistant believes the user expressed."""

    MATERIAL_RECEIPT_REQUESTED = "MaterialReceiptRequested"
    MATERIAL_USAGE_REQUESTED = "MaterialUsageRequested"
    MATERIAL_TRANSFER_REQUESTED = "MaterialTransferRequested"
    EXPENSE_REQUESTED = "ExpenseRequested"
    EQUIPMENT_USAGE_REQUESTED = "EquipmentUsageRequested"
    LABOUR_ATTENDANCE_REQUESTED = "LabourAttendanceRequested"
    GENERAL_SITE_UPDATE_REQUESTED = "GeneralSiteUpdateRequested"
    # No longer split from GENERAL_SITE_UPDATE_REQUESTED by `update_kind`
    # (docs/execution/ACTIVITY_RESOLUTION_AND_CORRECTION_PLAN.md retired that
    # split -- see canonicalization/mapping.py's note on why). Still
    # produced by canonicalization/builder.py's `_build_linked_activity_
    # segment` (a material usage naming a work_item); both event types route
    # to the same merged WorkflowKey.SITE_UPDATE (planner/routing.py).
    ACTIVITY_CONTINUATION_REQUESTED = "ActivityContinuationRequested"
    # ADR-D14: SemanticType.ACTIVITY_CORRECTION -> "make that 180", correcting
    # a quantity already reported this conversation. Routes to its own
    # WorkflowKey.ACTIVITY_CORRECTION (planner/routing.py) -- not the merged
    # SITE_UPDATE key above, since correcting is a materially different
    # confirmation shape (old value -> new value) than creating or
    # continuing.
    ACTIVITY_CORRECTION_REQUESTED = "ActivityCorrectionRequested"
    # SemanticType.SITE_ISSUE -> a reported blocker/delay, always a new
    # site_issues row (no continuation split like GENERAL_SITE_UPDATE has --
    # each report is its own record, never appended to a prior one).
    SITE_ISSUE_REPORTED = "SiteIssueReported"
    # SemanticType.SITE_ISSUE_UPDATE split by the extracted `action` field --
    # same pattern EXPENSE_REVERSAL_REQUESTED/TRANSFER_REVERSAL_REQUESTED
    # use for `target_kind` below. All five route to the single
    # WorkflowKey.SITE_ISSUE_CLOSE (see planner/routing.py).
    SITE_ISSUE_ACKNOWLEDGE_REQUESTED = "SiteIssueAcknowledgeRequested"
    SITE_ISSUE_RESOLVE_REQUESTED = "SiteIssueResolveRequested"
    SITE_ISSUE_WONT_FIX_REQUESTED = "SiteIssueWontFixRequested"
    # The two repair directions, added after the close-out set shipped
    # one-way. CANCEL withdraws a report that should never have existed
    # ("wrong site, ignore that") -- the Site Issue equivalent of REVERSAL,
    # expressed as a status transition rather than a target_kind because an
    # issue's whole lifecycle already lives in `status` (migration 0460).
    # REOPEN undoes a premature close ("that's not actually fixed"), moving
    # a RESOLVED/WONT_FIX/ACKNOWLEDGED issue back to OPEN.
    SITE_ISSUE_CANCEL_REQUESTED = "SiteIssueCancelRequested"
    SITE_ISSUE_REOPEN_REQUESTED = "SiteIssueReopenRequested"
    GENERAL_QUESTION_ASKED = "GeneralQuestionAsked"
    IDENTITY_LOOKUP_REQUESTED = "IdentityLookupRequested"
    INVENTORY_QUERY_ASKED = "InventoryQueryAsked"
    LABOUR_QUERY_ASKED = "LabourQueryAsked"
    ACTIVITY_QUERY_ASKED = "ActivityQueryAsked"
    DPR_REQUESTED = "DprRequested"
    ACCOUNT_BALANCE_QUERY_ASKED = "AccountBalanceQueryAsked"
    EXPENSE_QUERY_ASKED = "ExpenseQueryAsked"
    TRANSFER_REQUESTED = "TransferRequested"
    PETTY_CASH_ISSUE_REQUESTED = "PettyCashIssueRequested"
    PETTY_CASH_RETURN_REQUESTED = "PettyCashReturnRequested"
    EXPENSE_REVERSAL_REQUESTED = "ExpenseReversalRequested"
    TRANSFER_REVERSAL_REQUESTED = "TransferReversalRequested"
    # Petty cash has no transaction type of its own -- an advance writes the
    # same `transfer` row a plain transfer does, distinguished only by an
    # `employee_advance` leg. So this is not a different execution path (the
    # reversal executes identically); it exists so "reverse my last petty
    # cash" resolves to the right ROW, and so the confirmation names a
    # person rather than an account pair. Seeding also promotes a
    # TRANSFER_REVERSAL that turns out to have landed on an advance into
    # this kind -- the record decides what it is, not the user's wording.
    PETTY_CASH_REVERSAL_REQUESTED = "PettyCashReversalRequested"
    # Withdrawing a labour attendance report filed against the wrong site.
    # Distinct from re-sending the day and choosing "Replace it": that
    # supersedes within one project/site/day and is the right repair for a
    # miscount, but it cannot reach a report on a site nobody worked on --
    # the duplicate-day gate never offers it. Scoped to the reporter's own
    # reports (runtime/reversal_query.py's find_latest_attendance).
    ATTENDANCE_REVERSAL_REQUESTED = "AttendanceReversalRequested"
    # ADR-D15 (docs/execution/DAILY_REPORTING_PLAN.md): undoing an Activity
    # the reporter just created, same-session only -- see
    # runtime/reversal_query.py's find_latest_activity and
    # workflows/reverse/nodes.py's activity branch.
    ACTIVITY_REVERSAL_REQUESTED = "ActivityReversalRequested"
    # "create/rename/deactivate account". Two producers as of 2026-07-26:
    # runtime/account_admin_journey.py constructs this directly (zero-token
    # fast path) when its regex parser recognizes the exact phrasing;
    # canonicalization/mapping.py's resolve_event_type also maps
    # SemanticType.ACCOUNT_ADMIN here for everything else (other phrasing,
    # voice, non-English) the AI pipeline understood. Both converge on the
    # same WorkflowKey.ACCOUNT_ADMIN graph and the same role enforcement.
    ACCOUNT_ADMIN_REQUESTED = "AccountAdminRequested"
    # SemanticType.PROJECT_CREATE -> a new project record. No candidate-field
    # split (unlike MATERIAL_UPDATE/PETTY_CASH/REVERSAL/SITE_ISSUE_UPDATE
    # above) since there is only one action (create).
    PROJECT_CREATE_REQUESTED = "ProjectCreateRequested"
    # SemanticType.SITE_CREATE -> a new site record under the project
    # resolved by context (see enums.py's docstring on that type).
    SITE_CREATE_REQUESTED = "SiteCreateRequested"
    # SemanticType.PROJECT_DETAIL_QUERY -> a read-only project/site summary.
    PROJECT_DETAIL_QUERY_ASKED = "ProjectDetailQueryAsked"
    # SemanticType.AUTOMATION_SETUP -> a new recurring schedule rule. No
    # candidate-field split -- action/audience/frequency all travel as
    # plain fields on this one event type, read by
    # workflows/automation_setup/nodes.py's build_draft, the same way
    # ACCOUNT_ADMIN_REQUESTED carries its `action` field without a split.
    AUTOMATION_SETUP_REQUESTED = "AutomationSetupRequested"
    # SemanticType.ADD_PROJECT_MEMBER -> an existing user added to the
    # project resolved by context (see enums.py's docstring on that type).
    ADD_PROJECT_MEMBER_REQUESTED = "AddProjectMemberRequested"
    # SemanticType.CREATE_USER -> a brand new user record with WhatsApp
    # access (see enums.py's docstring on that type).
    CREATE_USER_REQUESTED = "CreateUserRequested"
    CLARIFICATION_REQUIRED = "ClarificationRequired"
    UNRECOGNIZED = "Unrecognized"


class IntentCompleteness(str, Enum):
    """Business-level completeness of the intent — not an AI confidence score."""

    ACTIONABLE = "actionable"
    NEEDS_CLARIFICATION = "needs_clarification"
    NOT_ACTIONABLE = "not_actionable"


class CanonicalEvent(BaseModel):
    """The normalized business-intent signal consumed by the Planner."""

    version: str = CONTRACT_VERSION

    # -- Provenance / linkage (correlation must survive end to end) ----------
    event_id: str
    correlation_id: str
    source_message_id: str
    causation_id: str | None = None
    conversation_id: str | None = None

    # -- Normalized intent ----------------------------------------------------
    event_type: CanonicalEventType
    completeness: IntentCompleteness

    # -- Tenancy / scope (denormalized from ResolvedContext) ------------------
    organization_id: str
    user_id: str
    project_id: str | None = None
    site_id: str | None = None
    permissions: list[str] = Field(default_factory=list)

    # -- Business intent payload (provider-agnostic) --------------------------
    fields: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}
