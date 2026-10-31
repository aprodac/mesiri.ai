"""Maps a confirmed workflow action into a typed Material Application Command (M8).

Shape-mapping only — no business validation here (that's domains/materials/
validation.py, run separately by the Handler).

occurred_date/occurred_date_source are decided upstream, in canonicalization
(canonicalization/occurred_date.py) — that is the only point holding both
what the message said and the sender's timezone. This mapper only reads the
answer. Backported from Labour (STA-166): until this changed, a stated
"yesterday" was silently overwritten with today, and "today" meant the
server's UTC today rather than the site's -- for a site in India, any report
before 05:30 local landed on the wrong date. The `date.today()` fallback
below exists only so a draft persisted before this shipped (still sitting at
AWAITING_CONFIRMATION, never having passed through the new canonicalization
path) stays confirmable rather than failing on a field it never carried.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from mesiri_contracts.application.commands.material import (
    RecordMaterialReceiptCommand,
    RecordMaterialTransferCommand,
    RecordMaterialUsageCommand,
)
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
from mesiri_contracts.common.ids import new_id


def _decimal(value: object) -> Decimal:
    """Coerce a JSON-sourced numeric value (int/float/str) to Decimal safely."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _occurred_date(fields: dict) -> date:
    """The day the material moved, as decided upstream. See this module's
    docstring -- falls back to today only for a draft that predates
    canonicalization owning this decision."""
    raw = fields.get("occurred_date")
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if raw:
        try:
            return date.fromisoformat(str(raw))
        except ValueError:
            pass
    return date.today()


def build_command(
    confirmed: ConfirmedActionV2,
) -> RecordMaterialReceiptCommand | RecordMaterialUsageCommand | RecordMaterialTransferCommand:
    """Map a ConfirmedActionV2 into the typed command its action_type calls for."""
    draft = confirmed.draft_action
    fields = draft.fields
    common = {
        "command_id": new_id("cmd"),
        "idempotency_key": confirmed.workflow_instance_id,
        "correlation_id": confirmed.correlation_id,
        "organization_id": draft.organization_id,
        "project_id": draft.project_id,
        "site_id": draft.site_id,
        "material_name": str(fields.get("material_name", "")),
        "quantity": _decimal(fields.get("quantity")),
        "unit": str(fields.get("unit", "")),
        "material_id": fields.get("material_id"),
        "unit_id": fields.get("unit_id"),
        "occurred_date": _occurred_date(fields),
        "occurred_date_source": str(fields.get("occurred_date_source") or "inferred_at_confirmation"),
        "created_by": confirmed.confirmed_by_user_id,
    }

    if draft.action_type is DraftActionType.RECORD_MATERIAL_RECEIPT:
        return RecordMaterialReceiptCommand(
            **common,
            supplier=fields.get("supplier"),
            total_cost=_decimal(fields["total_cost"]) if fields.get("total_cost") not in (None, "") else None,
            unit_cost=_decimal(fields["unit_cost"]) if fields.get("unit_cost") not in (None, "") else None,
            movement_reason=fields.get("movement_reason"),
            notes=fields.get("notes") or None,
            media_object_key=str(fields["media_object_key"]) if fields.get("media_object_key") else None,
        )
    if draft.action_type is DraftActionType.TRANSFER_MATERIAL:
        return RecordMaterialTransferCommand(
            **common,
            to_project_id=fields.get("to_project_id"),
            to_site_id=fields.get("to_site_id"),
        )
    return RecordMaterialUsageCommand(
        **common,
        work_item=fields.get("work_item"),
        movement_reason=fields.get("movement_reason"),
        notes=fields.get("notes") or None,
    )
