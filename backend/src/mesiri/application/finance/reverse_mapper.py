"""Maps a confirmed workflow action into a ReverseTransactionCommand.

Shape-mapping only — no business validation here (that's
reverse_validation.py, run separately by the Handler). Mirrors
application/finance/transfer_mapper.py.
"""

from __future__ import annotations

from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2

from .reverse_commands import ReverseTransactionCommand


def build_command(confirmed: ConfirmedActionV2) -> ReverseTransactionCommand:
    draft = confirmed.draft_action
    fields = draft.fields
    return ReverseTransactionCommand(
        idempotency_key=confirmed.workflow_instance_id,
        organization_id=draft.organization_id,
        created_by=confirmed.confirmed_by_user_id,
        created_by_role=fields.get("created_by_role"),
        target_kind=str(fields.get("target_kind", "")),
        expense_id=fields.get("expense_id"),
        money_transaction_id=fields.get("money_transaction_id"),
        activity_id=fields.get("activity_id"),
        attendance_report_id=fields.get("attendance_report_id"),
        correlation_id=confirmed.correlation_id,
    )
