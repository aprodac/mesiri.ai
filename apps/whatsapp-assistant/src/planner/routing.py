"""Static routing table from CanonicalEventType to WorkflowKey.

Pure data — no I/O. `GeneralQuestionAsked`, `Unrecognized`, and
`ClarificationRequired` are intentionally absent: they never start a workflow
(the Planner routes them to DIRECT_REPLY / CLARIFY instead of consulting this
table).
"""

from __future__ import annotations

from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.planner_decision import WorkflowKey

WORKFLOW_KEY_BY_EVENT: dict[CanonicalEventType, WorkflowKey] = {
    CanonicalEventType.MATERIAL_RECEIPT_REQUESTED: WorkflowKey.MATERIAL_RECEIPT,
    CanonicalEventType.MATERIAL_USAGE_REQUESTED: WorkflowKey.MATERIAL_USAGE,
    CanonicalEventType.EXPENSE_REQUESTED: WorkflowKey.EXPENSE_SUBMIT,
    CanonicalEventType.EQUIPMENT_USAGE_REQUESTED: WorkflowKey.EQUIPMENT_USAGE,
    CanonicalEventType.LABOUR_ATTENDANCE_REQUESTED: WorkflowKey.LABOUR_ATTENDANCE,
    CanonicalEventType.GENERAL_SITE_UPDATE_REQUESTED: WorkflowKey.SITE_UPDATE,
    # Routed to the same merged workflow as GENERAL_SITE_UPDATE_REQUESTED
    # (docs/execution/ACTIVITY_RESOLUTION_AND_CORRECTION_PLAN.md) -- the
    # separate WorkflowKey.ACTIVITY_CONTINUATION this used to route to is
    # retired (no registry entry any more; routing a message there would
    # silently no-op, see workflows/runtime.py's "no_graph" outcome). This
    # event type's one remaining producer is canonicalization/builder.py's
    # `_build_linked_activity_segment` (material usage naming a work_item);
    # it goes through workflows/site_update/nodes.py's resolve_target
    # exactly like any other site update.
    CanonicalEventType.ACTIVITY_CONTINUATION_REQUESTED: WorkflowKey.SITE_UPDATE,
    CanonicalEventType.ACTIVITY_CORRECTION_REQUESTED: WorkflowKey.ACTIVITY_CORRECTION,
    CanonicalEventType.SITE_ISSUE_REPORTED: WorkflowKey.SITE_ISSUE_REPORT,
    CanonicalEventType.SITE_ISSUE_ACKNOWLEDGE_REQUESTED: WorkflowKey.SITE_ISSUE_CLOSE,
    CanonicalEventType.SITE_ISSUE_RESOLVE_REQUESTED: WorkflowKey.SITE_ISSUE_CLOSE,
    CanonicalEventType.SITE_ISSUE_WONT_FIX_REQUESTED: WorkflowKey.SITE_ISSUE_CLOSE,
    CanonicalEventType.SITE_ISSUE_CANCEL_REQUESTED: WorkflowKey.SITE_ISSUE_CLOSE,
    CanonicalEventType.SITE_ISSUE_REOPEN_REQUESTED: WorkflowKey.SITE_ISSUE_CLOSE,
    CanonicalEventType.IDENTITY_LOOKUP_REQUESTED: WorkflowKey.WHO_AM_I,
    CanonicalEventType.INVENTORY_QUERY_ASKED: WorkflowKey.MATERIAL_INVENTORY_QUERY,
    CanonicalEventType.LABOUR_QUERY_ASKED: WorkflowKey.LABOUR_QUERY,
    CanonicalEventType.ACTIVITY_QUERY_ASKED: WorkflowKey.ACTIVITY_QUERY,
    CanonicalEventType.DPR_REQUESTED: WorkflowKey.DPR_REQUEST,
    CanonicalEventType.ACCOUNT_ADMIN_REQUESTED: WorkflowKey.ACCOUNT_ADMIN,
    CanonicalEventType.PROJECT_CREATE_REQUESTED: WorkflowKey.PROJECT_CREATE,
    CanonicalEventType.SITE_CREATE_REQUESTED: WorkflowKey.SITE_CREATE,
    CanonicalEventType.PROJECT_DETAIL_QUERY_ASKED: WorkflowKey.PROJECT_DETAIL_QUERY,
    CanonicalEventType.AUTOMATION_SETUP_REQUESTED: WorkflowKey.AUTOMATION_SETUP,
    CanonicalEventType.ADD_PROJECT_MEMBER_REQUESTED: WorkflowKey.ADD_PROJECT_MEMBER,
    CanonicalEventType.CREATE_USER_REQUESTED: WorkflowKey.CREATE_USER,
    CanonicalEventType.ACCOUNT_BALANCE_QUERY_ASKED: WorkflowKey.ACCOUNT_BALANCE_QUERY,
    CanonicalEventType.EXPENSE_QUERY_ASKED: WorkflowKey.EXPENSE_QUERY,
    CanonicalEventType.TRANSFER_REQUESTED: WorkflowKey.TRANSFER,
    CanonicalEventType.PETTY_CASH_ISSUE_REQUESTED: WorkflowKey.PETTY_CASH,
    CanonicalEventType.PETTY_CASH_RETURN_REQUESTED: WorkflowKey.PETTY_CASH,
    CanonicalEventType.EXPENSE_REVERSAL_REQUESTED: WorkflowKey.REVERSE,
    CanonicalEventType.TRANSFER_REVERSAL_REQUESTED: WorkflowKey.REVERSE,
    CanonicalEventType.ACTIVITY_REVERSAL_REQUESTED: WorkflowKey.REVERSE,
    CanonicalEventType.PETTY_CASH_REVERSAL_REQUESTED: WorkflowKey.REVERSE,
    CanonicalEventType.ATTENDANCE_REVERSAL_REQUESTED: WorkflowKey.REVERSE,
}
