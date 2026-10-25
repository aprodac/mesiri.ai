"""Maps a confirmed workflow action into a typed Progress Application Command.

Shape-mapping only — no business validation here (that's
domains/progress/validation.py, run separately by the Handler). Mirrors
application/labour/mapper.py: `draft.fields` is JSON-shaped (not typed), so
this is the one place that turns those dicts back into typed commands.

Two mapping functions, not one, matching the two commands (see
mesiri_contracts.application.commands.progress's module docstring) — a
ConfirmedActionV2 for `activity_creation` maps to CreateActivityCommand; one
for `activity_continuation` maps to AddProgressUpdateCommand. Which mapper
runs is decided by the caller (the workflow-specific Handler), not by
inspecting the draft here.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from mesiri_contracts.application.commands.progress import (
    ActivityQuantityInput,
    AddProgressUpdateCommand,
    CloseSiteIssueCommand,
    CorrectActivityQuantityCommand,
    CreateActivityCommand,
    ReportSiteIssueCommand,
)
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
from mesiri_contracts.common.ids import new_id


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


def _build_quantity(raw: dict[str, Any]) -> ActivityQuantityInput | None:
    qty = _decimal(raw.get("quantity"))
    unit = raw.get("unit")
    if qty is None or not unit:
        return None
    return ActivityQuantityInput(
        work_type=raw.get("work_type"),
        unit=str(unit),
        unit_id=raw.get("unit_id"),
        quantity=qty,
        measurement_type=str(raw.get("measurement_type") or "ACHIEVED").upper(),
    )


def _activity_date(fields: dict[str, Any]) -> date:
    """The day the work happened. Same reasoning as Labour's
    `_occurred_date` (application/labour/mapper.py) — canonicalization
    (canonicalization/occurred_date.py) is the only point holding both what
    the message said and the sender's timezone; this only reads its output
    and falls back to today() for an older draft that never carried it.

    `occurred_date` is checked first -- it's the uniform field name
    canonicalization writes for every module. `activity_date` is accepted as
    a fallback only for a caller that already renamed it (none currently do)."""
    raw = fields.get("occurred_date") or fields.get("activity_date")
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


def build_create_activity_command(confirmed: ConfirmedActionV2) -> CreateActivityCommand:
    draft = confirmed.draft_action
    fields = draft.fields
    raw_quantities = fields.get("quantities")
    quantities = [
        q
        for q in (
            _build_quantity(entry)
            for entry in (raw_quantities if isinstance(raw_quantities, list) else [])
            if isinstance(entry, dict)
        )
        if q is not None
    ]

    return CreateActivityCommand(
        command_id=new_id("cmd"),
        idempotency_key=confirmed.workflow_instance_id,
        correlation_id=confirmed.correlation_id,
        organization_id=draft.organization_id,
        project_id=draft.project_id,
        site_id=draft.site_id,
        work_package_id=fields.get("work_package_id"),
        location_id=fields.get("location_id"),
        work_type=fields.get("work_type"),
        narrative=fields.get("narrative"),
        contractor=fields.get("contractor"),
        started_at=fields.get("started_at"),
        ended_at=fields.get("ended_at"),
        quantities=quantities,
        activity_date=_activity_date(fields),
        occurred_date_source=str(fields.get("occurred_date_source") or "inferred_at_confirmation"),
        source=str(fields.get("source") or "whatsapp_text"),
        created_by=confirmed.confirmed_by_user_id,
    )


def build_add_progress_update_command(confirmed: ConfirmedActionV2) -> AddProgressUpdateCommand:
    draft = confirmed.draft_action
    fields = draft.fields

    occurred_raw = fields.get("occurred_at")
    if isinstance(occurred_raw, str):
        try:
            occurred_at = datetime.fromisoformat(occurred_raw)
        except ValueError:
            occurred_at = datetime.now()
    elif isinstance(occurred_raw, datetime):
        occurred_at = occurred_raw
    else:
        # No stated moment -- the time this update was confirmed is the best
        # available fact (mirrors falling back to today() for activity_date).
        occurred_at = datetime.now()

    return AddProgressUpdateCommand(
        command_id=new_id("cmd"),
        idempotency_key=confirmed.workflow_instance_id,
        correlation_id=confirmed.correlation_id,
        organization_id=draft.organization_id,
        activity_id=fields.get("activity_id"),
        update_kind=str(fields.get("update_kind") or "PROGRESS").upper(),
        narrative=fields.get("narrative"),
        quantity=_decimal(fields.get("quantity")),
        unit=fields.get("unit"),
        unit_id=fields.get("unit_id"),
        occurred_at=occurred_at,
        source=str(fields.get("source") or "whatsapp_text"),
        created_by=confirmed.confirmed_by_user_id,
    )


def build_correct_activity_quantity_command(
    confirmed: ConfirmedActionV2,
) -> CorrectActivityQuantityCommand:
    """ADR-D14: "make that 180" -- draft.fields carries `progress_update_id`
    (resolved by seeding, see workflows/activity_correction/nodes.py) and
    `new_quantity`/`unit`/`unit_id` (the corrected value, `unit` already
    falling back to the original unit if the message didn't restate one --
    see that same node's build_draft)."""
    draft = confirmed.draft_action
    fields = draft.fields

    return CorrectActivityQuantityCommand(
        command_id=new_id("cmd"),
        idempotency_key=confirmed.workflow_instance_id,
        correlation_id=confirmed.correlation_id,
        organization_id=draft.organization_id,
        progress_update_id=fields.get("progress_update_id"),
        new_quantity=_decimal(fields.get("new_quantity")),
        new_unit=fields.get("unit"),
        new_unit_id=fields.get("unit_id"),
        reason=fields.get("reason"),
        source=str(fields.get("source") or "whatsapp_text"),
        created_by=confirmed.confirmed_by_user_id,
    )


#: BE-48: an issue's delay is at most one day, the dashboard's own limit
#: (site_day.MAX_HOURS_LOST); "no work for 2 days" is saved as a full day.
_MAX_DELAY_MINUTES = 24 * 60


def _delay_minutes(value: object) -> int | None:
    if value is None:
        return None
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    if minutes <= 0:
        return None
    return min(minutes, _MAX_DELAY_MINUTES)


def build_report_site_issue_command(confirmed: ConfirmedActionV2) -> ReportSiteIssueCommand:
    draft = confirmed.draft_action
    fields = draft.fields

    return ReportSiteIssueCommand(
        command_id=new_id("cmd"),
        idempotency_key=confirmed.workflow_instance_id,
        correlation_id=confirmed.correlation_id,
        organization_id=draft.organization_id,
        project_id=draft.project_id,
        site_id=draft.site_id,
        activity_id=fields.get("activity_id"),
        issue_type=str(fields.get("issue_type") or "OTHER").upper(),
        severity=str(fields.get("severity") or "MEDIUM").upper(),
        narrative=fields.get("narrative"),
        delay_duration_minutes=_delay_minutes(fields.get("delay_duration_minutes")),
        occurred_date=_activity_date(fields),
        occurred_date_source=str(fields.get("occurred_date_source") or "inferred_at_confirmation"),
        source=str(fields.get("source") or "whatsapp_text"),
        created_by=confirmed.confirmed_by_user_id,
    )


def build_close_site_issue_command(confirmed: ConfirmedActionV2) -> CloseSiteIssueCommand:
    draft = confirmed.draft_action
    fields = draft.fields

    return CloseSiteIssueCommand(
        command_id=new_id("cmd"),
        idempotency_key=confirmed.workflow_instance_id,
        correlation_id=confirmed.correlation_id,
        organization_id=draft.organization_id,
        site_issue_id=fields.get("site_issue_id"),
        action=str(fields.get("action") or "").strip().lower(),
        resolution_notes=fields.get("resolution_notes"),
        created_by=confirmed.confirmed_by_user_id,
    )
