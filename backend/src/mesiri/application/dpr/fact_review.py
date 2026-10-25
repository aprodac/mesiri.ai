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


def counted_sql(fact_type: str, fact_id_sql: str) -> str:
    """WA-77 (Alan, 25 Oct): an entry counts only once it is saved. SQL that
    is true unless the fact's latest review is a draft (sent, Save not yet
    tapped). A fact with no review row counts, as `state_of` says.
    `fact_type` is one of FACT_TYPES (a constant, never user input);
    `fact_id_sql` is the column holding the fact's id. Uses
    ix_fact_reviews_fact (fact_type, fact_id, created_at)."""
    if fact_type not in FACT_TYPES:
        raise ValueError(f"unknown fact type: {fact_type}")
    return counted_sql_by_column(f"'{fact_type}'", fact_id_sql)


def counted_sql_by_column(fact_type_sql: str, fact_id_sql: str) -> str:
    """`counted_sql` for rows that carry their fact type in a column (late
    entries): both arguments are SQL expressions from code, never input."""
    return (
        "COALESCE((SELECT fr_c.state FROM fact_reviews fr_c "
        f"WHERE fr_c.fact_type = {fact_type_sql} AND fr_c.fact_id = {fact_id_sql} "
        f"ORDER BY fr_c.created_at DESC LIMIT 1), '{CONFIRMED}') <> '{DRAFT}'"
    )


def movement_counted_sql(alias: str) -> str:
    """WA-77 for stock: SQL true unless this `material_movements` row comes
    from an entry still waiting for its Save -- a receipt or usage whose
    latest review is a draft, or the incoming half of a transfer whose
    outgoing half (the reviewed one) is. Rejecting a draft posts a reversal
    and leaves the draft `rejected`, so the two still cancel out. `alias` is
    a table alias from code, never input. For what is shown as stock; the
    write-time over-stock check still counts drafts (they were reported)."""
    return (
        f"NOT ("
        f"({alias}.source_type = 'material_usage' AND NOT ({counted_sql(MATERIAL_USAGE, f'{alias}.source_id')})) "
        f"OR ({alias}.source_type = 'material_receipt' AND NOT ({counted_sql(MATERIAL_RECEIPT, f'{alias}.source_id')})) "
        f"OR ({alias}.source_type = 'material_receipt' AND EXISTS ("
        f"SELECT 1 FROM material_receipts r_c JOIN material_usage u_c ON u_c.transfer_id = r_c.transfer_id "
        f"WHERE r_c.id = {alias}.source_id AND r_c.transfer_id IS NOT NULL "
        f"AND NOT ({counted_sql(MATERIAL_USAGE, 'u_c.id')})))"
        f")"
    )


def counts(state: str | None) -> bool:
    """WA-77: whether a fact in this review state is part of the record
    (stock, attendance, the report). A draft is not, until it is saved."""
    return state_of(state) != DRAFT


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
