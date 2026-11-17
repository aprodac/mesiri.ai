"""Maps a confirmed workflow action into a typed Labour Application Command (M8).

Shape-mapping only — no business validation here (that's
domains/workforce/validation.py, run separately by the Handler). Mirrors
application/materials/mapper.py: occurred_date is defaulted to today because
nothing upstream (CanonicalEvent/DraftAction) ever carries a stated date;
occurred_date_source records that this is an inferred value, not a
user-reported one.

Each line arrives from workflows/labour_update/nodes.py's build_draft as a
plain dict (draft.fields is JSON-shaped, not typed) — this is the one place
that turns those dicts back into LabourAttendanceLine, matching the shape
the domain and the database both expect.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from mesiri.domains.shared import clock
from mesiri_contracts.application.commands.labour import (
    LabourAttendanceLine,
    RecordLabourAttendanceCommand,
)
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
from mesiri_contracts.common.ids import new_id


def _optional_decimal(value: object) -> Decimal | None:
    """Coerce a JSON-sourced numeric value (int/float/str) to Decimal, or
    None -- unlike materials' `_decimal`, a missing wage is a real,
    meaningful state (P9: a wage-less report is a legitimate fast capture),
    not something to silently default to zero."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


def _int_headcount(value: object) -> int:
    try:
        parsed = int(float(str(value)))
    except (TypeError, ValueError):
        return 1
    return parsed if parsed > 0 else 1


def _build_line(raw: dict[str, Any]) -> LabourAttendanceLine:
    return LabourAttendanceLine(
        worker_name=raw.get("worker_name"),
        worker_name_original=raw.get("worker_name_original"),
        worker_id=raw.get("worker_id"),
        trade=raw.get("trade"),
        headcount=_int_headcount(raw.get("headcount", 1)),
        daily_wage=_optional_decimal(raw.get("daily_wage")),
        contractor=raw.get("contractor"),
        activity=raw.get("activity"),
        # Defaulted rather than validated here: canonicalization already maps
        # the sheet's P/A/H mark and leaves it unset when unreadable, and
        # "present" is the right answer for every typed report.
        attendance_status=_attendance_status(raw.get("attendance_status")),
        overtime_hours=_optional_decimal(raw.get("overtime_hours")),
        remarks=raw.get("remarks"),
    )


_VALID_ATTENDANCE_STATUSES = frozenset({"present", "absent", "half_day"})


def _attendance_status(raw: Any) -> str:
    """Anything unrecognised falls back to present.

    The command would reject an unknown value outright, which would throw away
    an entire attendance report over one unreadable cell. Recording the day as
    worked is both the overwhelmingly common case and the recoverable error --
    a supervisor can see it in the confirmation and correct it; a rejected
    report just disappears."""
    text = str(raw or "").strip().lower()
    return text if text in _VALID_ATTENDANCE_STATUSES else "present"


def _attachment_object_keys(fields: dict[str, Any]) -> list[str]:
    """Attendance sheet photo(s), via the same field the image-purpose
    picker's re-processed image lands in (ADR-L3 -- reuses the attachment
    shape receipts already use, no labour-specific image path).

    `attachment_object_keys` (plural) is the command's real shape and wins if
    a future multi-image flow ever populates it; `media_object_key`
    (singular) is what the pipeline actually sets today, so it is wrapped
    into a one-element list rather than dropped.
    """
    keys = fields.get("attachment_object_keys")
    if isinstance(keys, list) and keys:
        return [str(k) for k in keys if k]
    single = fields.get("media_object_key")
    return [str(single)] if single else []


def _optional_str(raw: Any) -> str | None:
    """A blank string is not an id. Fields survive a JSON round-trip through
    workflow_instances, where an unanswered slot can come back as "" rather
    than absent, and "" would fail the command's UUID validation for no
    reason a user could act on."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _occurred_date(fields: dict[str, Any]) -> date:
    """The day the work happened, as decided upstream.

    Canonicalization owns this now (canonicalization/occurred_date.py): it is
    the only point holding both what the message said and the sender's
    timezone. Deciding it here instead was the direct cause of two bugs --
    a stated "yesterday" was overwritten with today, and `date.today()` used
    the host's UTC clock, so any report from India before 05:30 local was
    filed under the previous day.

    Falling back to `date.today()` keeps an older draft (persisted before
    this shipped, still sitting at AWAITING_CONFIRMATION) confirmable rather
    than failing on a field it never carried. New drafts always carry it.
    """
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


def build_command(confirmed: ConfirmedActionV2) -> RecordLabourAttendanceCommand:
    """Map a ConfirmedActionV2 into RecordLabourAttendanceCommand.

    Malformed line entries (not a dict) are skipped rather than raising —
    the same defensiveness workflows/labour_update/nodes.py's own readers
    apply, since fields have already survived a JSON round-trip through
    workflow_instances by the time they reach here. domains/workforce/
    validation.py is what rejects an attendance that ends up with zero
    lines as a result; this function never decides that on its own.
    """
    draft = confirmed.draft_action
    fields = draft.fields
    raw_lines = fields.get("lines")
    lines = [
        _build_line(entry)
        for entry in (raw_lines if isinstance(raw_lines, list) else [])
        if isinstance(entry, dict)
    ]

    return RecordLabourAttendanceCommand(
        command_id=new_id("cmd"),
        idempotency_key=confirmed.workflow_instance_id,
        correlation_id=confirmed.correlation_id,
        organization_id=draft.organization_id,
        project_id=draft.project_id,
        site_id=draft.site_id,
        lines=lines,
        notes=fields.get("notes"),
        attachment_object_keys=_attachment_object_keys(fields),
        occurred_date=_occurred_date(fields),
        occurred_date_source=str(fields.get("occurred_date_source") or "inferred_at_confirmation"),
        recorded_via=str(fields.get("recorded_via") or "whatsapp_text"),
        # Only ever set by the supervisor answering "replace what I sent
        # earlier" -- never inferred here. An absent or blank value means this
        # report stands alongside any other for the same day, which is a real
        # case (a second shift), not a failure to detect a duplicate.
        corrects_report_id=_optional_str(fields.get("corrects_report_id")),
        created_by=confirmed.confirmed_by_user_id,
    )
