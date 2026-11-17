"""Maps a confirmed workflow action into a TransferMoneyCommand.

Shape-mapping only — no business validation here (that's
transfer_validation.py, run separately by the Handler). Mirrors
application/expenses/mapper.py. `occurred_date` is defaulted to today
because nothing upstream (CanonicalEvent/DraftAction) ever carries a stated
date, same reasoning as application/expenses/mapper.py.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from mesiri.domains.shared import clock
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2

from .transfer_commands import TransferMoneyCommand


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def build_command(confirmed: ConfirmedActionV2) -> TransferMoneyCommand:
    draft = confirmed.draft_action
    fields = draft.fields
    return TransferMoneyCommand(
        idempotency_key=confirmed.workflow_instance_id,
        organization_id=draft.organization_id,
        created_by=confirmed.confirmed_by_user_id,
        created_by_role=fields.get("created_by_role"),
        from_account_id=str(fields.get("from_account_id", "")),
        to_account_id=str(fields.get("to_account_id", "")),
        amount=_decimal(fields.get("amount")),
        occurred_date=clock.today(),
        description=fields.get("description"),
        correlation_id=confirmed.correlation_id,
    )
