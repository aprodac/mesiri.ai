"""Re-sending a day's attendance must not double it.

Attendance is append-only (P5): a supervisor who forgets someone re-sends the
whole list rather than editing. Migration 0371 reserved `corrects_report_id`
for exactly this and every total already excludes a report another report
corrects -- but nothing ever *wrote* the column, so the guard could not fire.
Production shows the consequence: 14 separate reports for one site-day, all
counting.

These cover the question that produces the value: it is asked only when a
report already exists, it is never guessed, and "replace" is what carries the
earlier report's id into the command.
"""

from __future__ import annotations

from workflows.labour_update.nodes import (
    ADD_SEPARATELY_SENTINEL,
    DUPLICATE_DAY_SLOT_NAME,
    REPLACE_SENTINEL,
    build_draft,
    check_duplicate_day,
    request_confirmation,
)

EXISTING = {
    "report_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "line_count": 3,
    "total_headcount": 16,
    "total_cost": "12800.00",
}


def _state(**fields):
    collected = {"lines": [{"worker_name": "Ravi", "trade": "mason", "headcount": 1}]}
    collected.update(fields)
    return {
        "collected_fields": collected,
        "correlation_id": "corr-1",
        "workflow_instance_id": "wf-1",
        "organization_id": "11111111-1111-4111-8111-111111111111",
        "user_id": "22222222-2222-4222-8222-222222222222",
    }


# --- When the question is asked at all ------------------------------------

def test_a_clear_day_asks_nothing():
    """The ordinary case. Most reports are the first for their day, and an
    extra question on every one of them would be its own problem (P9)."""
    assert check_duplicate_day(_state()) == {}


def test_a_day_that_already_has_a_report_asks():
    result = check_duplicate_day(_state(existing_report=EXISTING))
    assert result["awaiting_slot"] == DUPLICATE_DAY_SLOT_NAME
    assert "already reported" in result["pending_prompt"]


def test_the_prompt_says_what_is_already_on_record():
    """A bare "this looks like a duplicate" asks the supervisor to decide
    against something they cannot see."""
    prompt = check_duplicate_day(_state(existing_report=EXISTING))["pending_prompt"]
    assert "16 workers" in prompt
    assert "12,800" in prompt or "12800" in prompt


def test_an_answered_question_is_not_asked_again():
    state = _state(existing_report=EXISTING, duplicate_day_answered=True)
    assert check_duplicate_day(state) == {}


def test_a_malformed_seed_is_ignored_rather_than_crashing():
    for bad in (None, {}, {"report_id": ""}, "not-a-dict", 42):
        assert check_duplicate_day(_state(existing_report=bad)) == {}


# --- Answering ------------------------------------------------------------

def test_replace_carries_the_earlier_report_id():
    state = _state(existing_report=EXISTING, _slot_answer_text="1")
    state["awaiting_slot"] = DUPLICATE_DAY_SLOT_NAME
    result = check_duplicate_day(state)

    assert result["collected_fields"]["corrects_report_id"] == EXISTING["report_id"]
    assert result["collected_fields"]["duplicate_day_answered"] is True
    assert result["awaiting_slot"] is None


def test_add_separately_leaves_both_reports_counting():
    """A second shift on the same site and day is a real report, not a
    mistake -- it must not be silently folded into the first."""
    state = _state(existing_report=EXISTING, _slot_answer_text="Add as separate")
    state["awaiting_slot"] = DUPLICATE_DAY_SLOT_NAME
    result = check_duplicate_day(state)

    assert "corrects_report_id" not in result["collected_fields"]
    assert result["collected_fields"]["duplicate_day_answered"] is True
    assert result["awaiting_slot"] is None


def test_replace_matches_by_label_not_only_by_number():
    state = _state(existing_report=EXISTING, _slot_answer_text="replace it")
    state["awaiting_slot"] = DUPLICATE_DAY_SLOT_NAME
    result = check_duplicate_day(state)
    assert result["collected_fields"]["corrects_report_id"] == EXISTING["report_id"]


def test_an_unrecognised_answer_re_asks_rather_than_guessing():
    """Guessing either way silently loses real attendance or silently doubles
    it, so an unclear answer must produce the question again."""
    state = _state(existing_report=EXISTING, _slot_answer_text="mmm what")
    state["awaiting_slot"] = DUPLICATE_DAY_SLOT_NAME
    result = check_duplicate_day(state)

    assert result["awaiting_slot"] == DUPLICATE_DAY_SLOT_NAME
    assert "couldn't tell which one" in result["pending_prompt"]
    assert "corrects_report_id" not in result["collected_fields"]


def test_the_two_answers_are_the_only_options_offered():
    result = check_duplicate_day(_state(existing_report=EXISTING))
    values = [o.get("value") if isinstance(o, dict) else o for o in result["awaiting_slot_options"]]
    assert REPLACE_SENTINEL in str(values)
    assert ADD_SEPARATELY_SENTINEL in str(values)


# --- What reaches the command --------------------------------------------

def test_the_draft_carries_the_answer_but_not_the_bookkeeping():
    """`existing_report` and `duplicate_day_answered` are how the node kept
    its place; only the decision itself belongs in the command."""
    state = _state(
        existing_report=EXISTING,
        duplicate_day_answered=True,
        corrects_report_id=EXISTING["report_id"],
    )
    fields = build_draft(state)["draft_action"].fields

    assert fields["corrects_report_id"] == EXISTING["report_id"]
    assert "existing_report" not in fields
    assert "duplicate_day_answered" not in fields


def test_the_confirmation_says_in_words_that_this_replaces_something():
    """Attendance cannot be edited afterwards, so this is the last moment the
    supervisor can catch a replacement they did not intend."""
    state = _state(corrects_report_id=EXISTING["report_id"])
    draft_state = {**state, "draft_action": build_draft(state)["draft_action"]}
    prompt = request_confirmation(draft_state)["pending_prompt"]

    assert "replaces your earlier report" in prompt
    # The uuid itself is meaningless to a supervisor and must not be shown.
    assert EXISTING["report_id"] not in prompt


def test_an_ordinary_report_says_nothing_about_replacing():
    state = _state()
    draft_state = {**state, "draft_action": build_draft(state)["draft_action"]}
    prompt = request_confirmation(draft_state)["pending_prompt"]
    assert "replaces" not in prompt
