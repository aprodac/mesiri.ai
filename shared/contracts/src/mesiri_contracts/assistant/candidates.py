"""Structured extraction candidates (M3).

These are *understanding hypotheses*, not authoritative business records. The
understanding pipeline never persists them; downstream context/planner/domain
layers decide truth. Every field is optional so missing information stays
explicitly unknown — the pipeline must never fabricate a value.

Ownership: Ilan (part of UnderstandingResult.v1). CROSS-REVIEW for shape.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .enums import SemanticType


class FieldConfidence(BaseModel):
    """Per-field confidence and provenance for a single extracted value."""

    field: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str | None = None  # provider-provided justification / source span


class Candidate(BaseModel):
    """Base for all extraction candidates.

    ``fields`` holds recognised values; ``unknown_fields`` records keys the
    provider surfaced but the schema does not model; ``missing_fields`` names
    required-but-absent keys; ``field_confidences`` and ``warnings`` carry
    quality signals.
    """

    semantic_type: SemanticType
    fields: dict[str, Any] = Field(default_factory=dict)
    unknown_fields: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    field_confidences: list[FieldConfidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExpenseCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.EXPENSE
    # Conventional keys (all optional): amount, currency, vendor, category,
    # description, paid_to, occurred_on, tax_rate, tax_amount,
    # is_tax_inclusive (pure preservation of what a bill/receipt states --
    # see backend's application/expenses/commands.py docstring, never
    # computed or validated). Kept in `fields` so the schema stays forgiving
    # while a stable shape emerges.


class EquipmentUsageCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.EQUIPMENT_USAGE
    # Conventional keys: equipment_name, duration_hours, operator, activity.


class MaterialUpdateCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.MATERIAL_UPDATE
    # Conventional keys: material_name, quantity, unit, direction(received/used),
    # work_item (usage only -- the activity the material was used for).


class LabourUpdateCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.LABOUR_UPDATE
    # Conventional keys: headcount, trade, hours, contractor.


class LabourQueryCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.LABOUR_QUERY
    # Conventional keys: date_range (today/this_week/this_month), trade
    # (optional -- absent means "all trades"). Read-only; carries no business
    # record, only a question to answer.


class GeneralSiteUpdateCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.GENERAL_SITE_UPDATE
    # Conventional keys: summary, activity, location, weather.


class SiteIssueCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.SITE_ISSUE
    # Conventional keys: issue_type (required to route -- see
    # canonicalization/mapping.py; one of WEATHER/MATERIAL_SHORTAGE/
    # LABOUR_SHORTAGE/DRAWING_PENDING/EQUIPMENT_BREAKDOWN/
    # INSPECTION_WAITING/ACCESS/SAFETY/QUALITY/OTHER), severity (LOW/MEDIUM/HIGH/CRITICAL),
    # narrative, delay_duration_minutes, occurred_on. A reported blocker/
    # delay -- never a question about existing ones (that's activity_query).


class SiteIssueUpdateCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.SITE_ISSUE_UPDATE
    # Conventional keys: action (required to route -- see
    # canonicalization/mapping.py; one of acknowledge/resolve/wont_fix/
    # cancel/reopen), resolution_notes. Always targets the most recently
    # reported issue in the right status, resolved by seeding -- never a new
    # report (that's site_issue). `cancel` withdraws a mistaken report and
    # `reopen` undoes a premature close; which statuses each may target
    # differs, so seeding picks the status filter per action.


class GeneralQuestionCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.GENERAL_QUESTION
    # Conventional keys: question, topic.


class InventoryQueryCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.INVENTORY_QUERY
    # Conventional keys: material_name (optional -- absent means "all materials").


class FinanceQueryCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.FINANCE_QUERY
    # Conventional keys: query_kind (balance/expenses, required to route --
    # see canonicalization/mapping.py), account_name, category_name,
    # date_range (today/this_week/this_month).


class TransferCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.TRANSFER
    # Conventional keys: amount, from_account_name, to_account_name,
    # description. Account names are best-effort hints -- resolved against
    # the org's real accounts by workflows/transfer/nodes.py, which asks
    # when a name doesn't resolve (see workflows/slots.py).


class PettyCashCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.PETTY_CASH
    # Conventional keys: amount, recipient_name, direction (issue/return),
    # description. recipient_name is a best-effort hint -- resolved against
    # the org's real users by runtime/petty_cash_query.py, which auto-
    # creates the recipient's employee-advance account on first issuance
    # (see workflows/petty_cash/nodes.py).


class ReversalCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.REVERSAL
    # Conventional keys: target_kind (expense/transfer, required to route --
    # see canonicalization/mapping.py). No amount/reference fields -- the
    # target is always "the most recent one of this kind", resolved by
    # runtime/reversal_query.py, not stated by the user.


class ProjectCreateCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.PROJECT_CREATE
    # Conventional keys: name (required to route -- see canonicalization/
    # mapping.py), location, client. Best-effort hints as stated -- no
    # resolution against existing records needed (unlike account_admin's
    # target_name/new_name), since this always creates a brand new row.


class ProjectDetailQueryCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.PROJECT_DETAIL_QUERY
    # Conventional keys: output_format ("pdf" to also send the summary as a
    # document, same convention every other query candidate uses). Which
    # project/site this asks about is NOT a candidate field here -- see
    # SemanticType.PROJECT_DETAIL_QUERY's docstring; resolved by context,
    # same as SITE_CREATE's project scope.


class SiteCreateCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.SITE_CREATE
    # Conventional keys: name (required to route -- see canonicalization/
    # mapping.py), location. Which project this site belongs to is
    # deliberately not a candidate field here -- see SemanticType.SITE_CREATE's
    # docstring on why that's resolved by context, not stated by the user.


class AutomationSetupCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.AUTOMATION_SETUP
    # Conventional keys: time_of_day (required to route -- "HH:MM" 24-hour,
    # see canonicalization/mapping.py), frequency (DAILY/WEEKDAYS/WEEKLY,
    # absent means DAILY), day_of_week (WEEKLY only, the English weekday
    # name), automation_action (SEND_DPR/COMPLIANCE_SUMMARY/REMINDER),
    # audience (SELF/USERS/ROLE/NON_REPORTERS), audience_names (array of
    # person names, USERS only -- best-effort hints resolved against the
    # org's real users the same way petty_cash's recipient_name is, see
    # runtime/petty_cash_query.py), audience_role (ROLE only), message
    # (REMINDER only, the sender's own words).


class AddProjectMemberCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.ADD_PROJECT_MEMBER
    # Conventional keys: member_name (required to route -- see
    # canonicalization/mapping.py), role (optional hint, e.g. "site
    # engineer"/"project manager"; absent defaults to SITE_ENGINEER, same
    # default project_members.role itself uses). Which project this adds to
    # is deliberately not a candidate field here -- see
    # SemanticType.ADD_PROJECT_MEMBER's docstring on why that's resolved by
    # context, not stated by the user. member_name is a best-effort hint as
    # stated -- resolved against the org's real active users by
    # application/projects/name_resolution.py, exactly as account_admin's
    # target_name/new_name already work.


class CreateUserCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.CREATE_USER
    # Conventional keys: full_name, whatsapp_number (both required to route
    # -- see canonicalization/mapping.py), role (optional hint, e.g. "site
    # engineer"; absent defaults to SITE_ENGINEER, same as
    # AddProjectMemberCandidate's role). whatsapp_number is stated as-is --
    # no resolution needed, since this always creates a brand new row (same
    # reasoning as ProjectCreateCandidate's docstring).


class AccountAdminCandidate(Candidate):
    semantic_type: SemanticType = SemanticType.ACCOUNT_ADMIN
    # Conventional keys: action (create/rename/deactivate, required to
    # route -- see canonicalization/mapping.py), name (create), target_name
    # (rename/deactivate), new_name (rename), account_type (create only,
    # cash/bank). target_name/new_name/name are best-effort hints as stated
    # -- resolved against the org's actual accounts by
    # application/finance/resolution.py, exactly as the deterministic
    # regex-parsed path already worked. ADMIN/FINANCE only -- see
    # runtime/inbound_journey.py and application/finance/validation.py.


# Registry so callers can build the right candidate from a semantic type.
CANDIDATE_TYPES: dict[SemanticType, type[Candidate]] = {
    SemanticType.EXPENSE: ExpenseCandidate,
    SemanticType.EQUIPMENT_USAGE: EquipmentUsageCandidate,
    SemanticType.MATERIAL_UPDATE: MaterialUpdateCandidate,
    SemanticType.LABOUR_UPDATE: LabourUpdateCandidate,
    SemanticType.GENERAL_SITE_UPDATE: GeneralSiteUpdateCandidate,
    SemanticType.SITE_ISSUE: SiteIssueCandidate,
    SemanticType.SITE_ISSUE_UPDATE: SiteIssueUpdateCandidate,
    SemanticType.GENERAL_QUESTION: GeneralQuestionCandidate,
    SemanticType.INVENTORY_QUERY: InventoryQueryCandidate,
    SemanticType.LABOUR_QUERY: LabourQueryCandidate,
    SemanticType.FINANCE_QUERY: FinanceQueryCandidate,
    SemanticType.TRANSFER: TransferCandidate,
    SemanticType.PETTY_CASH: PettyCashCandidate,
    SemanticType.REVERSAL: ReversalCandidate,
    SemanticType.ACCOUNT_ADMIN: AccountAdminCandidate,
    SemanticType.PROJECT_CREATE: ProjectCreateCandidate,
    SemanticType.SITE_CREATE: SiteCreateCandidate,
    SemanticType.PROJECT_DETAIL_QUERY: ProjectDetailQueryCandidate,
    SemanticType.AUTOMATION_SETUP: AutomationSetupCandidate,
    SemanticType.ADD_PROJECT_MEMBER: AddProjectMemberCandidate,
    SemanticType.CREATE_USER: CreateUserCandidate,
}
