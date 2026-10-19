"""What a trial company's people hear as the trial ends (SS-08).

Pure rules, no I/O. Company status itself is lifecycle.py's job; this only
decides the messages around it:

    ENDING_SOON  2 days left   reminder to the owner
    LAST_DAY     1 day left    reminder to the owner
    expired                    owner: "your trial ended, data safe for N
                               days, continue?"; anyone else: "ask <owner>"

Reminders go through the notifications queue (rule TRIAL_REMINDER_RULE), so
the sender's own policy applies: free text inside WhatsApp's 24-hour
window, the `mesiri_trial_ending` template outside it (once approved),
quiet hours, a recorded reason when skipped.

"Continue" (a reply or a tap) records a request the control panel shows
(organization_settings key `continue_requests`); converting to paid stays
a manual step for the Mesiri team (SS-10).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from mesiri.domains.organizations import lifecycle

TRIAL_REMINDER_RULE = "trial_reminder"
ENDING_SOON = "ending_soon"
LAST_DAY = "last_day"
TEMPLATE_NAME = "mesiri_trial_ending"

CONTINUE_WORDS = frozenset({"continue", "continue with mesiri", "yes continue"})
CONTINUE_TAP = "trial:continue"

OPEN = "open"
CLOSED = "closed"


def reminder_due(trial_ends_at: dt.datetime | None, now: dt.datetime) -> str | None:
    """Which reminder (if any) a trial ending at `trial_ends_at` is due now."""
    days_left = lifecycle.trial_days_left(trial_ends_at, now)
    if days_left == 2:
        return ENDING_SOON
    if days_left == 1:
        return LAST_DAY
    return None


def end_day_label(trial_ends_at: dt.datetime | None, timezone: str | None) -> str:
    """The trial's end as "22 Oct", in the company's local time."""
    if trial_ends_at is None:
        return "soon"
    try:
        zone = ZoneInfo(timezone or "Asia/Kolkata")
    except Exception:  # noqa: BLE001
        zone = ZoneInfo("Asia/Kolkata")
    local = trial_ends_at.astimezone(zone)
    return f"{local.day} {local:%b}"


def _so_far(reports_sent: int) -> str:
    if reports_sent <= 0:
        return ""
    plural = "report" if reports_sent == 1 else "reports"
    return f" So far Mesiri has made *{reports_sent} daily {plural}* for you."


def reminder_message(kind: str, *, company: str, end_day: str, reports_sent: int) -> str:
    # The date, never "tomorrow": the message is written when queued but can
    # go out hours later, after quiet hours.
    lead = "⏳ Last reminder: your" if kind == LAST_DAY else "⏳ Your"
    return (
        f"{lead} Mesiri free trial for *{company}* ends on *{end_day}*.{_so_far(reports_sent)}\n\n"
        "Reply *CONTINUE* and our team will call you to keep your daily reports going."
    )


def reminder_template_params(*, company: str, end_day: str) -> list[str]:
    """Body params for `mesiri_trial_ending` (text in docs/ops/whatsapp-templates.md)."""
    return [company, end_day]


def expired_owner_message(*, end_day: str, retention_days: int) -> str:
    return (
        f"Your Mesiri free trial ended on *{end_day}*. Your reports and data are safe "
        f"for {retention_days} days.\n\nWant to keep going? Our team will set it up for you."
    )


def expired_member_message(*, company: str, owner_name: str | None) -> str:
    who = owner_name or "your company's admin"
    return f"The Mesiri free trial for {company} has ended. Please ask {who} to continue."


CONTINUE_RECEIVED = "👍 Thank you! Our team will call you today to keep your daily reports going."
CONTINUE_ALREADY = "👍 We have your request. Our team will call you soon."


def add_continue_request(
    requests: object, *, user_id: str, via: str, now: dt.datetime
) -> tuple[list[dict[str, Any]], bool]:
    """`requests` with a new open request, unless one is already open.
    Returns (requests, added)."""
    items = [dict(r) for r in requests] if isinstance(requests, list) else []
    if any(r.get("status") == OPEN for r in items):
        return items, False
    items.append(
        {
            "id": str(uuid.uuid4()),
            "status": OPEN,
            "created_at": now.isoformat(),
            "user_id": user_id,
            "via": via,  # "whatsapp" or "dashboard"
        }
    )
    return items, True


def close_continue_requests(
    requests: object, *, resolution: str, by: str | None, now: dt.datetime
) -> tuple[list[dict[str, Any]], int]:
    """`requests` with every open request closed as `resolution` ("converted" /
    "extended", SA-10). Returns (requests, how many were closed)."""
    items = [dict(r) for r in requests] if isinstance(requests, list) else []
    closed = 0
    for r in items:
        if r.get("status") == OPEN:
            r.update(status=CLOSED, closed_at=now.isoformat(), closed_by=by, resolution=resolution)
            closed += 1
    return items, closed


def is_continue(text: object) -> bool:
    return " ".join(str(text or "").lower().replace("*", "").split()) in CONTINUE_WORDS
