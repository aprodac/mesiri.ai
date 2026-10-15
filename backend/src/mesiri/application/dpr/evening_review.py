"""The evening review of each site's day (WA-04, WA-05, WA-06).

Between a project's cutoff (`reporting_cutoff_time`, when the day's drafts
are built) and its send deadline (`dpr_send_deadline`, when the project DPR
goes out whatever happened), each site's engineer gets one message about
their site's day, chosen from what the day holds:

    something sent, but no work items or no labour count  -> gap-check (WA-04)
    complete enough to send ("ready")                      -> confirm   (WA-05)
    nothing sent at all                                    -> reminder  (WA-06)

A day the engineer has marked "site closed / no work" (BE-14) is ready with
nothing required, so it goes to the confirmation, never to a gap-check.

Pure rules only; the scheduler step lives on the WhatsApp side
(runtime/site_day_review.py), the database reads in
application/projects/auto_dpr.py.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any

from mesiri.application.dpr import site_day

GAP_CHECK = "gap_check"
CONFIRM = "confirm"
NO_UPDATE = "no_update"

#: The `notifications.rule_key` prefix of every evening message. One row per
#: (site, recipient, date) and step, so each goes once a day. BE-38's quiet
#: hours skip it: the owner chose the cutoff and deadline it runs between.
RULE_KEY_PREFIX = "site_day_"
RULE_KEY_PREFIXES: Mapping[str, str] = {
    GAP_CHECK: "site_day_gap:",
    CONFIRM: "site_day_confirm:",
    NO_UPDATE: "site_day_no_update:",
}

#: A fact saved this close to the day's last refresh may have been committed
#: just after the refresh read the day, so the day is looked at again. A
#: refresh that finds nothing new writes no new version.
REFRESH_MARGIN = datetime.timedelta(minutes=2)


def rule_key(step: str, site_id: Any) -> str:
    return f"{RULE_KEY_PREFIXES[step]}{site_id}"


def evening_step(
    *, status: str | None, missing: Mapping[str, Any] | None, has_facts: bool
) -> str | None:
    """Which evening message a site day calls for, or None (no day yet, or
    already confirmed)."""
    if status is None or status in site_day.FROZEN or status == site_day.DRAFT:
        return None
    blocking = list((missing or {}).get("blocking") or [])
    if not has_facts and blocking:
        return NO_UPDATE
    if blocking:
        return GAP_CHECK
    if status in (site_day.READY, site_day.IN_REVIEW):
        return CONFIRM
    return None


def needs_refresh(
    *, last_fact_at: datetime.datetime | None, day_updated_at: datetime.datetime | None
) -> bool:
    """Whether something was saved on the day since it was last labelled."""
    if last_fact_at is None:
        return False
    if day_updated_at is None:
        return True
    return last_fact_at > day_updated_at - REFRESH_MARGIN


def has_content(payload: Mapping[str, Any] | None) -> bool:
    """Whether a day's payload holds anything at all -- a report worth a
    version, as opposed to an empty day that is only labelled."""
    payload = payload or {}
    return bool(
        payload.get("activity_count")
        or payload.get("issues")
        or (payload.get("labour") or {}).get("headcount")
        or payload.get("materials")
        or payload.get("evidence_count")
    )
