"""WA-77 (Alan, 25 Oct): the evening message says what nobody saved; those
entries stay out of the report unless the engineer keeps them."""

from __future__ import annotations

from runtime.site_day_review import confirm_message


def _message(total: int) -> str:
    return confirm_message(
        site_name="Tower A",
        project_name="Hospital",
        payload={"activity_count": 0, "labour": {}, "materials": [], "drafts": {"total": total}},
        holds={},
        deadline="18:00",
    )


def test_unsaved_entries_are_named_with_how_to_keep_them():
    text = _message(2)
    assert "2 entries were not saved (Save wasn't tapped)" in text
    assert "Fix something" in text


def test_one_unsaved_entry():
    assert "1 entry was not saved" in _message(1)


def test_no_line_when_everything_was_saved():
    assert "not saved" not in _message(0)
