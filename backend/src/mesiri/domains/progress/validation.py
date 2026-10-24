"""Progress domain validation (Daily Reporting) — pure functions, no I/O, no SQL.

Mirrors domains/workforce/validation.py and domains/materials/validation.py:
runs in the Application Handler *before* any transaction opens, returning
violation reasons rather than raising, so the Handler can choose between
persist_success and persist_rejection without exception handling around
business rules.

This validates command *shape*, not resolution — unit-text resolution and
Activity-existence checks happen in application/progress/resolution.py,
which needs a connection and therefore runs inside the transaction.
"""

from __future__ import annotations

from mesiri_contracts.application.commands.progress import (
    AddProgressUpdateCommand,
    CloseSiteIssueCommand,
    CorrectActivityQuantityCommand,
    CreateActivityCommand,
    ReportSiteIssueCommand,
)

_VALID_UPDATE_KINDS = frozenset(
    {"STARTED", "PROGRESS", "PAUSED", "RESUMED", "COMPLETED", "NOTE"}
)

# site_issue_type / site_issue_status enum members (migration 0430). Kept
# here (not imported from infrastructure/postgres/repositories/progress.py's
# identical constants) since that file is the REST-only direct-write path's
# own copy -- this validates the WhatsApp-confirmed command path instead, and
# domain validation must not import infrastructure.
_VALID_ISSUE_TYPES = frozenset(
    {
        "WEATHER",
        "MATERIAL_SHORTAGE",
        "LABOUR_SHORTAGE",
        "DRAWING_PENDING",
        "EQUIPMENT_BREAKDOWN",
        "INSPECTION_WAITING",
        "ACCESS",
        "SAFETY",
        "QUALITY",
        "OTHER",
    }
)
_VALID_ISSUE_SEVERITIES = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})


def validate_create_activity(cmd: CreateActivityCommand) -> list[str]:
    """Return violation reasons; empty list means valid."""
    reasons: list[str] = []
    if cmd.project_id is None:
        reasons.append("project is not resolved")
    if cmd.site_id is None:
        reasons.append("site is not resolved")

    # P10: a narrative-only report (zero quantities) is valid — do not
    # require quantities here. Do require that whatever quantities ARE
    # present are well-formed.
    for index, q in enumerate(cmd.quantities):
        prefix = f"quantity {index + 1}"
        if q.quantity <= 0:
            reasons.append(f"{prefix}: quantity must be positive")
        if not q.unit.strip():
            reasons.append(f"{prefix}: unit is required when a quantity is given")

    if not cmd.narrative and not cmd.quantities:
        # Not literally impossible (e.g. evidence-only), but a header with
        # nothing to say and nothing measured is not a useful Activity record.
        reasons.append("activity must have a narrative or at least one quantity")

    return reasons


def validate_add_progress_update(cmd: AddProgressUpdateCommand) -> list[str]:
    """Return violation reasons; empty list means valid."""
    reasons: list[str] = []
    if cmd.update_kind not in _VALID_UPDATE_KINDS:
        reasons.append(f"unrecognized update_kind: {cmd.update_kind}")

    if cmd.quantity is not None:
        if cmd.quantity <= 0:
            reasons.append("quantity must be positive")
        if not cmd.unit or not cmd.unit.strip():
            reasons.append("unit is required when a quantity is given")

    if not cmd.narrative and cmd.quantity is None and cmd.update_kind == "NOTE":
        reasons.append("a NOTE update needs a narrative or a quantity")

    return reasons


def validate_correct_activity_quantity(cmd: CorrectActivityQuantityCommand) -> list[str]:
    """Return violation reasons; empty list means valid. `progress_update_id`
    is a required CanonicalUuid (never an empty/missing value can reach
    here) -- existence of the *row* it names (and re-verifying it hasn't
    since been superseded by a newer correction) is DB-backed and belongs
    to the Handler/repository, same structural-vs-DB-backed split every
    other command here follows."""
    reasons: list[str] = []
    if cmd.new_quantity <= 0:
        reasons.append("quantity must be positive")
    if not cmd.new_unit or not cmd.new_unit.strip():
        reasons.append("unit is required")
    return reasons


def validate_report_site_issue(cmd: ReportSiteIssueCommand) -> list[str]:
    """Return violation reasons; empty list means valid."""
    reasons: list[str] = []
    if cmd.project_id is None:
        reasons.append("project is not resolved")
    if cmd.issue_type not in _VALID_ISSUE_TYPES:
        reasons.append(f"unrecognized issue_type: {cmd.issue_type}")
    if cmd.severity not in _VALID_ISSUE_SEVERITIES:
        reasons.append(f"unrecognized severity: {cmd.severity}")
    return reasons


#: `cancel` (withdraw a mistaken report) and `reopen` (undo a premature
#: close) are close-out actions like the other three -- they differ only in
#: which CURRENT status they may target, which is a DB-backed question and
#: so lives in progress_execution.py, not here.
_VALID_CLOSE_ACTIONS = frozenset(
    {"acknowledge", "resolve", "wont_fix", "cancel", "reopen"}
)


def validate_close_site_issue(cmd: CloseSiteIssueCommand) -> list[str]:
    """Pure structural check only -- whether the target issue's CURRENT
    status still allows this action is a DB-backed re-check, done inline by
    persist_close_site_issue_success (infrastructure/postgres/repositories/
    progress_execution.py) immediately before the UPDATE, mirroring
    reverse_resolution.py's re-verify-at-confirm-time reasoning. site_issue_
    id itself is never missing here in practice -- runtime/inbound_journey.
    py's seeding step only ever builds a draft once a target was found
    (workflows/site_issue_close/nodes.py's build_draft), but this is still
    checked structurally for defense-in-depth."""
    reasons: list[str] = []
    if cmd.action not in _VALID_CLOSE_ACTIONS:
        reasons.append(f"unknown action '{cmd.action}'")
    if not cmd.site_issue_id:
        reasons.append("no site issue to update")
    return reasons
