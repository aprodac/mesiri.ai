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


# Readiness rule (approved 13 Oct 2026): a day is ready to send to the
# engineer when it has at least one work item AND a labour count. Photos,
# materials and issues are listed when absent but never block -- a day with
# no deliveries or no problems is a normal day.
def missing_sections(payload: dict[str, Any] | None) -> dict[str, list[str]]:
    payload = payload or {}
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
