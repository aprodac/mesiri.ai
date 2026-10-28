"""Request 137: the Day Facts rules (runtime/day_facts.py)."""

from __future__ import annotations

import pytest

from runtime import day_facts as df
from runtime.agent.cards import CardItem

ID_70 = "11111111-1111-1111-1111-111111111111"


def item(percent=None, quantity=None, work="tiling", place="ground floor", fact_id=ID_70) -> CardItem:
    args = {"work_type": work, "location": place}
    if percent is not None:
        args["progress_percent"] = percent
    if quantity is not None:
        args["quantities"] = [{"quantity": quantity, "unit": "sqm"}]
    return CardItem("save_work_done", args, "activity", fact_id, "Tiling")


@pytest.mark.parametrize(
    ("state", "counts"),
    [(None, True), ("confirmed", True), ("draft", False)],
)
def test_counted_is_saved_which_is_not_a_draft(state, counts):
    assert df.counted(state) is counts


def test_a_work_fact_carries_its_fact_id_key_and_value():
    fact = df.work_fact_of(item(percent=70), "site-1")
    assert (fact.fact_id, fact.field, fact.value, fact.site_id) == (ID_70, df.PERCENT, 70.0, "site-1")
    assert fact.key == df.work_key("Tiling", " Ground  Floor ")
    assert df.work_fact_of(item(quantity=12)).field == df.QUANTITY
    assert df.work_fact_of(CardItem("save_labour", {}, "labour_report", ID_70, "x")) is None


@pytest.mark.parametrize(
    ("value", "unit", "text", "expected"),
    [
        (80, None, "Green Villa ground floor tiling 80% aayi", True),
        (80, "%", "make it 80", True),
        (80, None, "tiling 80 percent done", True),
        (150, None, "correction, it was 150 not 180", False),
        (30, "sqm", "make that 30 sqm", False),
    ],
)
def test_a_percent_is_a_figure_said_with_a_percent(value, unit, text, expected):
    assert df.is_percent(value, unit, text) is expected


def test_a_newer_percent_is_a_new_line():
    facts = df.work_facts([item(percent=70)])
    assert df.resolve_percent(facts, 80, "Green Villa ground floor tiling 80% aayi").action == df.NEW_LINE


def test_an_explicit_correction_edits_the_saved_line_by_fact_id():
    facts = df.work_facts([item(percent=70)])
    resolved = df.resolve_percent(facts, 75, "alla, 75%")
    assert (resolved.action, resolved.fact.fact_id) == (df.CHANGE, ID_70)


def test_nothing_saved_means_a_new_line_and_several_works_are_never_guessed():
    assert df.resolve_percent([], 75, "alla, 75%").action == df.NEW_LINE
    two = df.work_facts([item(percent=70), item(percent=40, work="plastering", fact_id="22222222-2222-2222-2222-222222222222")])
    assert df.resolve_percent(two, 75, "alla, 75%").action == df.NOTHING


def test_open_work_leaves_out_drafts_and_cancelled_activities():
    sql = df.open_work_sql("activities.id")
    assert "fact_type = 'activity'" in sql and "= 'confirmed'" in sql and "activities.id" in sql
