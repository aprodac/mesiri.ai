"""The site's working day (BE-08): which status a SITE-level DPR may move to,
and whether a day's draft is complete enough to send to the engineer.

A site day is the SITE-level `daily_reports` row (one per site per date,
migration 0440), not a separate table. V1 flow, decided 13 Oct 2026:

    collecting (DRAFT) -> needs details (NEEDS_DETAILS) / ready (READY)
      -> with engineer (IN_REVIEW) -> confirmed (APPROVED) -> sent (PUBLISHED)

The engineer is the only approver. Pure logic, no I/O -- the repository
(infrastructure/postgres/repositories/dpr.py) enforces these rules in its
UPDATE statements, so both stay testable without Postgres.
"""

from __future__ import annotations

from typing import Any

DRAFT = "DRAFT"
NEEDS_DETAILS = "NEEDS_DETAILS"
READY = "READY"
IN_REVIEW = "IN_REVIEW"
APPROVED = "APPROVED"
PUBLISHED = "PUBLISHED"
NOT_REPORTED = "NOT_REPORTED"

# Frozen (P7): a new version needs revise_version and a stated reason.
FROZEN = frozenset({APPROVED, PUBLISHED})

# Statuses whose readiness label a regeneration may recompute. IN_REVIEW is
# deliberately absent: a report the engineer is looking at keeps its place
# when new facts arrive -- it used to be reset to DRAFT on every run.
REEVALUATED = frozenset({DRAFT, NEEDS_DETAILS, READY, NOT_REPORTED})

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    DRAFT: frozenset({NEEDS_DETAILS, READY, IN_REVIEW, APPROVED}),
    NOT_REPORTED: frozenset({DRAFT, NEEDS_DETAILS, READY}),
    NEEDS_DETAILS: frozenset({READY, IN_REVIEW, APPROVED}),
    READY: frozenset({NEEDS_DETAILS, IN_REVIEW, APPROVED}),
    # Back out of review when the engineer asks to fix something (WA-05).
    IN_REVIEW: frozenset({NEEDS_DETAILS, READY, APPROVED}),
    APPROVED: frozenset({PUBLISHED, DRAFT}),  # DRAFT only via a revision
    PUBLISHED: frozenset({DRAFT}),  # DRAFT only via a revision
}


class InvalidSiteDayTransition(ValueError):
    pass


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def sources_for(target: str) -> list[str]:
    """Every status a day may be in to move to `target` -- what the
    repository's `WHERE status IN (...)` guards against."""
    return sorted(s for s, targets in ALLOWED_TRANSITIONS.items() if target in targets)


def check_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise InvalidSiteDayTransition(f"a site day cannot move from {current} to {target}")


# Site conditions (BE-14). Weather words match the dashboard's existing set.
WEATHER_VALUES = frozenset({"sunny", "cloudy", "rainy", "windy", "extreme_heat"})
SITE_WORKING_FULL = "full"
SITE_WORKING_HALF = "half"
SITE_WORKING_NONE = "none"
SITE_WORKING_VALUES = frozenset({SITE_WORKING_FULL, SITE_WORKING_HALF, SITE_WORKING_NONE})
MAX_HOURS_LOST = 24


def validate_conditions(changes: dict[str, Any]) -> None:
    """Raises ValueError naming the first bad field. `None` clears a field."""
    weather = changes.get("weather")
    if weather is not None and weather not in WEATHER_VALUES:
        raise ValueError(f"weather must be one of {sorted(WEATHER_VALUES)}")
    working = changes.get("site_working")
    if working is not None and working not in SITE_WORKING_VALUES:
        raise ValueError(f"site_working must be one of {sorted(SITE_WORKING_VALUES)}")
    hours = changes.get("hours_lost")
    if hours is not None and not 0 <= float(hours) <= MAX_HOURS_LOST:
        raise ValueError(f"hours_lost must be between 0 and {MAX_HOURS_LOST}")


# Readiness rule (approved 13 Oct 2026): a day is ready to send to the
# engineer when it has at least one work item AND a labour count. Photos,
# materials, weather and tomorrow's plan are listed when absent but never
# block -- a day with no deliveries is a normal day. A day marked "no work"
# (BE-14) is ready with nothing required: there is nothing to report.
def missing_sections(payload: dict[str, Any] | None) -> dict[str, list[str]]:
    payload = payload or {}
    conditions = payload.get("conditions") or {}
    if conditions.get("site_working") == SITE_WORKING_NONE:
        return {"blocking": [], "optional": []}
    blocking: list[str] = []
    optional: list[str] = []
    if not payload.get("activity_count"):
        blocking.append("work_done")
    if not (payload.get("labour") or {}).get("headcount"):
        blocking.append("labour")
    if not payload.get("evidence_count"):
        optional.append("photos")
    if not payload.get("materials"):
        optional.append("materials")
    if not conditions.get("weather"):
        optional.append("weather")
    if not conditions.get("tomorrow_plan"):
        optional.append("tomorrow_plan")
    return {"blocking": blocking, "optional": optional}


def readiness_status(payload: dict[str, Any] | None) -> str:
    return NEEDS_DETAILS if missing_sections(payload)["blocking"] else READY


def status_after_refresh(
    current: str, payload: dict[str, Any] | None, *, evaluate_readiness: bool
) -> str:
    """The status a SITE day takes when its draft is regenerated.

    `evaluate_readiness` is True once the project's cutoff has passed (the
    automatic DPR and the nightly run). Before that the day is still
    collecting and keeps DRAFT. A day already marked needs details or ready
    is re-checked on every refresh, so a missing labour count arriving late
    turns it ready without waiting for another cutoff."""
    if current in FROZEN:
        raise InvalidSiteDayTransition(f"a {current} day is frozen; revise it instead")
    if current not in REEVALUATED:
        return current
    if evaluate_readiness or current in (NEEDS_DETAILS, READY):
        return readiness_status(payload)
    return DRAFT
