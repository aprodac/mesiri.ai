"""WA-77 (Alan, 25 Oct): an entry counts once it is saved. A draft (sent on
WhatsApp, Save not yet tapped) is left out of the report and only listed
for the engineer."""

from __future__ import annotations

import uuid

import pytest

from mesiri.application.dpr import fact_review
from mesiri.application.dpr.assembly import (
    build_review_items,
    build_site_report_payload,
    saved_rows_only,
)

A_SAVED, A_DRAFT, A_CONTINUED = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
L_SAVED, L_DRAFT = uuid.uuid4(), uuid.uuid4()
R_DRAFT, U_SAVED = uuid.uuid4(), uuid.uuid4()
I_DRAFT = uuid.uuid4()

STATES = {
    fact_review.ACTIVITY: {A_SAVED: fact_review.CONFIRMED, A_DRAFT: fact_review.DRAFT, A_CONTINUED: fact_review.DRAFT},
    fact_review.LABOUR_REPORT: {L_SAVED: fact_review.CONFIRMED, L_DRAFT: fact_review.DRAFT},
    fact_review.MATERIAL_RECEIPT: {R_DRAFT: fact_review.DRAFT},
    fact_review.MATERIAL_USAGE: {U_SAVED: fact_review.CONFIRMED},
    fact_review.SITE_ISSUE: {I_DRAFT: fact_review.DRAFT},
}


def _rows():
    return {
        "activities": [
            {"id": A_SAVED, "work_type": "plastering"},
            {"id": A_DRAFT, "work_type": "flooring"},
            {"id": A_CONTINUED, "work_type": "brickwork", "continued": True, "started_on": "2026-10-24"},
        ],
        "issues": [{"id": I_DRAFT, "issue_type": "WEATHER", "status": "OPEN"}],
        "labour": [
            {"report_id": L_SAVED, "trade": "Helper", "headcount": 5},
            {"report_id": L_DRAFT, "trade": "Mason", "headcount": 2},
        ],
        "materials": [
            {"source_type": "material_receipt", "source_id": R_DRAFT, "material_name": "cement", "quantity": 10},
            {"source_type": "material_usage", "source_id": U_SAVED, "material_name": "sand", "quantity": 3},
            {"source_type": "transfer_in", "source_id": uuid.uuid4(), "material_name": "steel", "quantity": 1},
        ],
    }


def test_saved_rows_only_leaves_out_drafts():
    kept = saved_rows_only(_rows(), STATES)

    assert [r["id"] for r in kept["activities"]] == [A_SAVED, A_CONTINUED]
    assert kept["issues"] == []
    assert [r["report_id"] for r in kept["labour"]] == [L_SAVED]
    # A draft receipt is out; a saved usage and a movement the review log doesn't cover stay.
    assert [r["material_name"] for r in kept["materials"]] == ["sand", "steel"]


def test_a_fact_with_no_review_row_counts():
    rows = {"activities": [{"id": uuid.uuid4()}], "issues": [], "labour": [], "materials": []}
    assert saved_rows_only(rows, {}) == rows


def test_the_report_is_saved_entries_while_the_review_list_still_shows_drafts():
    rows = {**_rows(), "materials": []}
    kwargs = dict(
        project_name="Hospital",
        site_name="Tower A",
        report_date=__import__("datetime").date(2026, 10, 25),
        quantities_by_activity={},
        evidence_count_by_activity={},
        review_states=STATES,
    )

    def payload_of(r):
        return build_site_report_payload(
            activity_rows=r["activities"], issue_rows=r["issues"], labour_lines=r["labour"],
            material_movement_rows=r["materials"], **kwargs,
        )

    report = payload_of(saved_rows_only(rows, STATES))
    assert [a["work_type"] for a in report["activities"]] == ["plastering", "brickwork"]
    assert report["labour"]["headcount"] == 5
    assert report["issues"] == []
    # The report still says how many wait to be saved.
    assert report["drafts"]["total"] > 0

    items = build_review_items(
        payload=payload_of(rows), activity_rows=rows["activities"], issue_rows=rows["issues"],
        labour_lines=rows["labour"], material_movement_rows=rows["materials"], review_states=STATES,
    )
    drafts = {i["id"] for i in items if i["review"] == fact_review.DRAFT}
    assert {str(A_DRAFT), str(L_DRAFT), str(I_DRAFT)} <= drafts


def test_counted_sql_takes_known_fact_types_only():
    sql = fact_review.counted_sql(fact_review.MATERIAL_USAGE, "mu.id")
    assert "fr_c.fact_type = 'material_usage'" in sql and "fr_c.fact_id = mu.id" in sql
    assert sql.endswith("<> 'draft'")
    with pytest.raises(ValueError):
        fact_review.counted_sql("payroll; DROP TABLE users", "x.id")


def test_counts():
    assert fact_review.counts(None) and fact_review.counts(fact_review.CONFIRMED)
    assert not fact_review.counts(fact_review.DRAFT)


def test_late_entries_are_listed_and_claimed_once_saved():
    import inspect

    from mesiri.application.dpr import late_entries

    assert "<> 'draft'" in late_entries._SAVED
    assert "{_SAVED}" in inspect.getsource(late_entries.late_entries_for_report)
    assert "{_SAVED}" in inspect.getsource(late_entries.claim_for_report)
