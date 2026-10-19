"""Request 57, B4/B5: a stated percentage is progress (never "finished"), the
saved note says it, the card shows it, and a site with its project's name is
named once."""

from __future__ import annotations

import pytest
from tests.unit.receipt_samples import receipt

from canonicalization.progress import apply_progress, find_percent
from mesiri_contracts.assistant.draft_action import DraftActionType


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Plastering 2nd floor 40% aayi", 40.0),
        ("plastering 40 percent done", 40.0),
        ("പ്ലാസ്റ്ററിംഗ് 40 ശതമാനം", 40.0),
        ("12.5% done", 12.5),
        ("6 mason, 10 helper vannu", None),
        ("150% of plan", None),
    ],
)
def test_find_percent(text, expected):
    assert find_percent(text) == expected


def test_percentage_below_100_is_never_completed_and_the_note_says_it():
    fields = {
        "narrative": "രണ്ടാം നിലയിൽ പ്ലാസ്റ്ററിംഗ് കഴിഞ്ഞു",  # "finished", wrongly
        "work_type": "plastering",
        "location": "2nd floor",
        "update_kind": "completed",
        "progress_percent": 40,
    }
    out = apply_progress(fields)
    assert out["update_kind"] == "progress"
    assert out["narrative"] == "Plastering, 2nd floor: 40%"
    assert out["progress_percent"] == 40


def test_percentage_found_in_the_senders_words_when_the_model_missed_it():
    out = apply_progress(
        {"narrative": "Plastering 2nd floor 40% aayi", "work_type": "plastering", "update_kind": "completed"}
    )
    assert out["progress_percent"] == 40
    assert out["update_kind"] == "progress"
    assert out["narrative"] == "Plastering: 40%"


def test_hundred_percent_stays_completed_and_no_percentage_changes_nothing():
    done = {"narrative": "Plastering done", "work_type": "plastering", "update_kind": "completed", "progress_percent": 100}
    assert apply_progress(done)["update_kind"] == "completed"
    plain = {"narrative": "Started plastering", "update_kind": "started"}
    assert apply_progress(plain) is plain


def test_card_shows_work_place_and_percentage():
    data = receipt(
        DraftActionType.CREATE_ACTIVITY,
        {
            "work_type": "plastering",
            "location": "2nd floor",
            "progress_percent": 40,
            "narrative": "Plastering, 2nd floor: 40%",
        },
    )
    assert (data.hero_number, data.hero_unit) == ("40", "% done")
    assert [(r.tag, r.text) for r in data.rows] == [("Work", "Plastering · 2nd floor · 40%")]
    assert data.summary.text == "Plastering · 2nd floor"
    assert data.summary.value == "40%"


def test_progress_update_card_shows_the_percentage():
    data = receipt(
        DraftActionType.ADD_PROGRESS_UPDATE,
        {"update_kind": "PROGRESS", "activity_summary": "Plastering", "progress_percent": 40},
    )
    assert (data.hero_number, data.hero_unit) == ("40", "% done")
    assert data.hero_title == ""


def test_site_and_project_with_the_same_name_are_shown_once():
    same = receipt(
        DraftActionType.RECORD_EXPENSE,
        {"amount": "10"},
        project="Green Villa, Kakkanad",
        site="Green Villa, Kakkanad",
    )
    assert same.site_line == "Green Villa, Kakkanad"
    differ = receipt(DraftActionType.RECORD_EXPENSE, {"amount": "10"}, project="Tower", site="Block A")
    assert differ.site_line == "Block A · Tower"
