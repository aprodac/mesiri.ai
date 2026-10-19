"""WA-04: which evening message a site day calls for, and when a day is
looked at again after the cutoff. Pure rules."""

from __future__ import annotations

import datetime as dt

import pytest

from mesiri.application.dpr import evening_review as review

_LABOUR_MISSING = {"blocking": ["labour"], "optional": ["photos"]}
_NOTHING = {"blocking": ["work_done", "labour"], "optional": ["photos", "materials"]}
_COMPLETE = {"blocking": [], "optional": ["photos"]}


@pytest.mark.parametrize(
    ("status", "missing", "has_facts", "expected"),
    [
        ("NEEDS_DETAILS", _LABOUR_MISSING, True, review.GAP_CHECK),
        ("NEEDS_DETAILS", _NOTHING, False, review.NO_UPDATE),
        ("READY", _COMPLETE, True, review.CONFIRM),
        ("IN_REVIEW", _COMPLETE, True, review.CONFIRM),
        # Marked "no work today": ready with nothing required, no facts.
        ("READY", {"blocking": [], "optional": []}, False, review.CONFIRM),
        # A day with the engineer that lost its labour count asks again.
        ("IN_REVIEW", _LABOUR_MISSING, True, review.GAP_CHECK),
        ("APPROVED", _COMPLETE, True, None),
        ("PUBLISHED", _COMPLETE, True, None),
        ("DRAFT", _LABOUR_MISSING, True, None),  # still collecting
        (None, None, False, None),
    ],
)
def test_evening_step(status, missing, has_facts, expected) -> None:
    assert review.evening_step(status=status, missing=missing, has_facts=has_facts) == expected


_T = dt.datetime(2026, 10, 15, 13, 30, tzinfo=dt.UTC)


def test_a_day_with_nothing_saved_is_not_refreshed() -> None:
    assert review.needs_refresh(last_fact_at=None, day_updated_at=_T) is False


def test_a_fact_after_the_last_label_refreshes_the_day() -> None:
    assert review.needs_refresh(last_fact_at=_T + dt.timedelta(minutes=5), day_updated_at=_T)


def test_a_fact_just_before_the_last_label_is_looked_at_again() -> None:
    assert review.needs_refresh(last_fact_at=_T - dt.timedelta(seconds=30), day_updated_at=_T)


def test_an_old_fact_does_not_refresh_the_day() -> None:
    assert not review.needs_refresh(last_fact_at=_T - dt.timedelta(hours=1), day_updated_at=_T)


def test_rule_keys_share_the_quiet_hours_prefix() -> None:
    for step in (review.GAP_CHECK, review.CONFIRM, review.NO_UPDATE):
        assert review.rule_key(step, "s1").startswith(review.RULE_KEY_PREFIX)
    assert review.rule_key(review.GAP_CHECK, "s1") == "site_day_gap:s1"


def test_has_content() -> None:
    assert not review.has_content({"activity_count": 0, "labour": {"headcount": 0}})
    assert review.has_content({"labour": {"headcount": 4}})
    assert review.has_content({"materials": [{"name": "cement"}]})


# --- WA-05: what holds back "Confirm all" --------------------------------------


@pytest.mark.parametrize(
    ("confidence", "fields", "expected"),
    [
        ("high", {}, set()),
        (None, {}, set()),
        ("medium", {}, set()),
        ("low", {}, {review.HOLD_LOW_CONFIDENCE}),
        ("AMBIGUOUS", {}, {review.HOLD_LOW_CONFIDENCE}),
        ("unresolved", {}, {review.HOLD_LOW_CONFIDENCE}),
        # Sent directly, no date said: about today, no guess.
        ("high", {"occurred_date_source": "inferred_at_confirmation"}, set()),
        # Forwarded with a stated date: fine.
        ("high", {"is_forwarded": True, "occurred_date_source": "stated_by_user"}, set()),
        # Forwarded with no date: may be an old update.
        ("high", {"is_forwarded": True}, {review.HOLD_DATE_GUESSED}),
        (
            "high",
            {"is_forwarded": True, "is_frequently_forwarded": True, "occurred_date_source": "stated_by_user"},
            {review.HOLD_FREQUENTLY_FORWARDED},
        ),
    ],
)
def test_draft_holds(confidence, fields, expected):
    assert review.draft_holds(confidence=confidence, fields=fields) == expected


def test_confirm_all_holds_counts_per_reason_in_order():
    drafts = [
        {"confidence": "low", "fields": {"is_forwarded": True}},
        {"confidence": "low", "fields": {}},
        {"confidence": "high", "fields": {}},
    ]
    holds = review.confirm_all_holds(payload={"possible_duplicates": 1, "stock_flags": 3}, drafts=drafts)
    assert holds == {
        review.HOLD_DUPLICATE: 1,
        review.HOLD_LOW_CONFIDENCE: 2,
        review.HOLD_DATE_GUESSED: 1,
    }
    assert list(holds) == [review.HOLD_DUPLICATE, review.HOLD_LOW_CONFIDENCE, review.HOLD_DATE_GUESSED]


def test_nothing_holds_a_clean_day_and_stock_is_only_a_warning():
    assert review.confirm_all_holds(payload={"stock_flags": 2}, drafts=[{"confidence": "high"}]) == {}
    assert review.confirm_all_holds(payload=None, drafts=[]) == {}
