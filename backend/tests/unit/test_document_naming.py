"""DOC-01 / DOC-05: a document's folder, number, title and revision from its name; "the latest X" matching."""

from __future__ import annotations

import pytest

from mesiri.domains.documents import naming


@pytest.mark.parametrize("name, folder, number, revision, discipline", [
    ("S-101 Rev C Column Layout.pdf", "drawing", "S-101", "C", "structural"),
    ("A-201_R2 First floor plan.pdf", "drawing", "A-201", "2", "architectural"),
    ("Electrical layout GF rev 1.pdf", "drawing", None, "1", "mep"),
    ("Building permit 2026.pdf", "approval", None, None, None),
    ("CAR insurance policy.pdf", "approval", None, None, None),
    ("Signed agreement - Green Villa.pdf", "contract", None, None, None),
    ("Estimate sheet final.xlsx", "boq", None, None, None),
    ("Work order Ravi tiling.pdf", "work_order", None, None, None),
    ("Cube test 28 days.pdf", "test_report", None, None, None),
    ("As built drawings set.pdf", "handover", None, None, None),
    ("IMG_2041.jpg", "other", None, None, None),
])
def test_guess_from_the_file_name(name, folder, number, revision, discipline):
    g = naming.guess(name)
    assert (g["folder"], g["number"], g["revision"], g["discipline"]) == (folder, number, revision, discipline)


def test_the_title_block_wins_over_the_name():
    g = naming.guess("scan 4.pdf", {"number": "S-102 GROUND", "revision": "D STRUCT", "title": "FOOTING LAYOUT",
                                   "kind": "plan", "discipline": "structural"})
    assert (g["folder"], g["number"], g["revision"], g["title"]) == ("drawing", "S-102", "D", "Footing Layout")


def test_a_room_name_is_not_a_revision():
    assert naming.guess("Kitchen R2 tiles.jpg")["revision"] is None


def test_only_known_kinds_are_kept():
    assert naming.content_type("plan.PDF") == "application/pdf"
    assert naming.content_type("tool.exe") is None


def _doc(**kw):
    return {"folder": "drawing", "discipline": None, "number": None, "title": "", "file_name": "", **kw}


def test_find_prefers_the_number_then_the_words():
    column = _doc(number="S-101", title="Column layout", discipline="structural")
    plan = _doc(number="A-101", title="Ground floor plan", discipline="architectural")
    permit = _doc(folder="approval", title="Building permit")
    assert naming.find_score("send me the latest s101", column) > naming.find_score("send me the latest s101", plan)
    assert naming.find_score("latest column drawing", column) > naming.find_score("latest column drawing", plan)
    assert naming.find_score("building permit evide", permit) > 0
    assert naming.find_score("permit", column) == 0
    assert naming.find_score("send me the latest drawing", column) == 0  # says no which: ask


# --- Step 7 test (23 Nov 2026): one letter per revision, and a permit's last day read from its words -------------

@pytest.mark.parametrize("current, nxt", [
    ("A", "B"), ("b", "C"), ("Z", "AA"), ("AZ", "BA"), ("0", "1"), ("9", "10"), ("R2", "R3"), ("P09", "P10"),
    (None, "A"), ("-", "A"),
])
def test_the_next_revision_letter(current, nxt):
    assert naming.next_revision(current) == nxt


def test_same_revision_ignores_case_and_spaces():
    assert naming.same_revision("b", " B") and naming.same_revision(None, "") and not naming.same_revision("A", "B")


@pytest.mark.parametrize("text, day", [
    ("Building permit. Permit no. TMC/BP/2026/1187 Date 30 September 2026 Owner Dr. Anand. Validity 3 years from "
     "the date of issue. Construction to follow the approved drawings (Rev A).", "2029-09-29"),
    ("Valid up to 31/03/2029", "2029-03-31"),
    ("Validity: till 31 March 2029", "2029-03-31"),
    ("Expiry date: 2029-03-31", "2029-03-31"),
    ("This licence expires on March 31, 2029", "2029-03-31"),
    ("Fire NOC dated 01.04.2026, valid for one year from the date of issue", "2027-03-31"),
    ("Valid upto 5th Jan 2028", "2028-01-05"),
])
def test_a_permits_last_day_is_read_from_its_words(text, day):
    found = naming.valid_until_of(text)
    assert found is not None and found[0].isoformat() == day and found[1]


@pytest.mark.parametrize("text", [
    "Fire NOC. No date here.",
    "Date 30 September 2026. Plot 412/3.",                 # an issue date alone is not a last day
    "Validity 3 years from the date of issue.",            # no issue date to count from
])
def test_no_last_day_is_made_up(text):
    assert naming.valid_until_of(text) is None
