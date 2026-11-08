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
