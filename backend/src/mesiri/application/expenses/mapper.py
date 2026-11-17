"""Maps a confirmed workflow action into a RecordExpenseCommand (M8-style).

Shape-mapping only — no business validation here (that's validation.py, run
separately by the Handler).

occurred_date is decided upstream, in canonicalization
(canonicalization/occurred_date.py) — the only point holding both what the
message said and the sender's timezone. Backported from Labour (STA-166):
until this changed, a stated "yesterday" was silently overwritten with
today, and "today" meant the server's UTC today rather than the site's. The
`date.today()` fallback below exists only so a draft persisted before this
shipped stays confirmable.

Unlike Material, RecordExpenseCommand carries no occurred_date_source field
at all -- there is no `expenses` table column for it (checked before adding
one; none exists) and the "(assumed today)" wording only ever needs to reach
the confirmation preview, which reads `occurred_date_source` straight off
`draft.fields` before this mapper ever runs. Adding an unused column would
be schema change for no reader.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from mesiri.domains.shared import clock
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2

from .commands import RecordExpenseCommand


def _decimal(value: object) -> Decimal:
    """Coerce a JSON-sourced numeric value (int/float/str) to Decimal safely."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _optional_decimal(value: object) -> Decimal | None:
    """Same coercion as _decimal, but absent/unparseable stays None rather
    than defaulting to 0 -- tax_rate/tax_amount are genuinely optional
    (most expenses have no stated tax), unlike amount, which every expense
    must have."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


def _occurred_date(fields: dict) -> date:
    """The day the expense happened, as decided upstream. See this module's
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
    return clock.today()


def build_command(confirmed: ConfirmedActionV2) -> RecordExpenseCommand:
    """Map a ConfirmedActionV2 into a RecordExpenseCommand.

    `category_id` is left unset — the draft only ever carries free-text
    `category` collected in conversation, resolved server-side by
    application/expenses/resolution.py before persistence.

    `account_id`/`paid_from_own_pocket` come from the draft's collected
    fields the same way — nothing populates them yet (Finance Module Slice 1
    wires the "which account?" slot-fill that sets them), so today they are
    always absent and the command defaults to payment_status='unpaid'.
    """
    draft = confirmed.draft_action
    fields = draft.fields
    return RecordExpenseCommand(
        idempotency_key=confirmed.workflow_instance_id,
        organization_id=draft.organization_id,
        project_id=draft.project_id or "",
        site_id=draft.site_id,
        amount=_decimal(fields.get("amount")),
        category_text=str(fields.get("category", "")).strip() or None,
        vendor_text=str(fields.get("vendor", "")).strip() or None,
        account_id=fields.get("account_id"),
        paid_from_own_pocket=bool(fields.get("paid_from_own_pocket", False)),
        media_object_key=fields.get("media_object_key"),
        description=fields.get("description"),
        occurred_date=_occurred_date(fields),
        source="whatsapp",
        correlation_id=confirmed.correlation_id,
        created_by=confirmed.confirmed_by_user_id,
        tax_rate=_optional_decimal(fields.get("tax_rate")),
        tax_amount=_optional_decimal(fields.get("tax_amount")),
        is_tax_inclusive=bool(fields.get("is_tax_inclusive", True)),
    )
