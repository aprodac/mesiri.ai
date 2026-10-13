"""Save first, confirm later (BE-09): the review states of a reported fact.

What the AI reads from a message is saved straight away as a draft; the site
engineer confirms it (or rejects it) later. Only confirmed facts go into a
confirmed DPR. A fact's state is the latest row in `fact_reviews`
(migration 0470); a fact with no row at all is confirmed -- everything saved
before drafts existed, and every flow that still confirms before saving.

Pure rules only; the repository (infrastructure/postgres/repositories/
fact_reviews.py) applies them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

DRAFT = "draft"
CONFIRMED = "confirmed"
REJECTED = "rejected"

ACTIVITY = "activity"
SITE_ISSUE = "site_issue"
LABOUR_REPORT = "labour_report"
MATERIAL_RECEIPT = "material_receipt"
MATERIAL_USAGE = "material_usage"

FACT_TYPES = frozenset({ACTIVITY, SITE_ISSUE, LABOUR_REPORT, MATERIAL_RECEIPT, MATERIAL_USAGE})


class FactReviewError(ValueError):
    """A review action that cannot happen (unknown fact, wrong state, frozen day)."""


def state_of(latest: str | None) -> str:
    """No review row means confirmed (saved before drafts existed)."""
    return latest or CONFIRMED


def check_confirm(current: str) -> bool:
    """True when confirming changes something; False for an already-confirmed
    fact (a harmless repeat). A rejected fact cannot be confirmed: it was
    withdrawn through its module's own undo, and re-reporting is the way back."""
    if current == REJECTED:
        raise FactReviewError("this item was rejected; report it again instead")
    return current == DRAFT


def check_reject(current: str) -> None:
    """Only drafts are rejected here. A confirmed fact is corrected through its
    module's normal correction, which keeps the reason for the change."""
    if current != DRAFT:
        raise FactReviewError(f"only a draft can be rejected; this item is {current}")


def review_counts(states: Mapping[str, Mapping[Any, str]]) -> dict[str, int]:
    """Drafts per DPR section, for the payload and the evening check.
    `states` maps fact type -> {fact id -> state} for the facts on the day."""

    def drafts(types: Iterable[str]) -> int:
        return sum(
            1 for fact_type in types for state in (states.get(fact_type) or {}).values() if state == DRAFT
        )

    counts = {
        "activities": drafts([ACTIVITY]),
        "issues": drafts([SITE_ISSUE]),
        "labour_reports": drafts([LABOUR_REPORT]),
        "materials": drafts([MATERIAL_RECEIPT, MATERIAL_USAGE]),
    }
    counts["total"] = sum(counts.values())
    return counts
