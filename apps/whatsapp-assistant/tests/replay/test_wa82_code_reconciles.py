# ruff: noqa: F811
"""WA-82 (plan of 27 Oct, phase 3): the model extracts, code decides where a fact
goes on the card.

Live 27 Oct (docs/qa/runs/2026-10-27-whatsapp-live-tests):
- round 7: the four-part note lost "mixer breakdown aayi pani 2 hour ninnu";
- round 8 (#4335): "Green Villa ground floor tiling 70% aayi" after the card was
  cancelled was taken as a correction of nothing: "angane oru card ippol open
  aayitilla", nothing saved.

The model is scripted the way the live model behaved; everything after it is the
real journey.
"""

from __future__ import annotations

import pytest
from tests.replay.test_draft_per_message_p1 import open_items, titles
from tests.replay.test_draft_per_message_p3 import at, tap, two  # noqa: F401  (fixtures)

from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import draft as dr
from runtime.agent.equipment import hours_lost_minutes, problem_clause
from runtime.agent.toolbox import NOT_A_CORRECTION

NOTE = "Site A2 innathe update: 5 mason 3 helper, ground floor tiling 60% aayi, 30 bags cement use cheythu, mixer breakdown aayi pani 2 hour ninnu"
LABOUR = ("save_labour", {"workers": [{"trade": "mason", "headcount": 5}, {"trade": "helper", "headcount": 3}]})
TILING = ("save_work_done", {"narrative": "ground floor tiling 60%", "work_type": "tiling", "location": "ground floor",
                             "progress_percent": 60})
TILING_70 = ("save_work_done", {"narrative": "ground floor tiling 70%", "work_type": "tiling", "location": "ground floor",
                                "progress_percent": 70})
CEMENT_USED = ("save_material_usage", {"material": "cement", "quantity": 30, "unit": "bags"})


@pytest.mark.parametrize(
    "text, clause",
    [
        (NOTE, "mixer breakdown aayi pani 2 hour ninnu"),
        ("Green Villa mixer breakdown aayi", "Green Villa mixer breakdown aayi"),
        ("5 mason vannu, pump problem illa", None),  # said to be fine
        ("mixer breakdown theernnu", None),  # over
        ("enthu problem?", None),  # a question
        ("5 mason 3 helper, tiling 60% aayi", None),
    ],
)
def test_the_problem_part_of_a_message(text, clause):
    assert problem_clause(text) == clause


def test_hours_lost():
    assert hours_lost_minutes("pani 2 hour ninnu") == 120
    assert hours_lost_minutes("mixer breakdown") is None


async def test_a_breakdown_the_model_left_out_of_a_site_note_is_on_the_card(two):
    """Round 7: the model saved labour, tiling and cement and called no report_issue."""
    calls = [at("Site A2", c) for c in (LABOUR, TILING, CEMENT_USED)]
    result = await two.say(FakeToolCallingProvider([calls, "Check it and tap Save."]), NOTE)
    issues = [i for i in await open_items(two) if i.kind == dr.KIND_ISSUE_OPEN]
    assert len(issues) == 1
    assert "breakdown" in issues[0].summary.casefold() or "mixer" in issues[0].summary.casefold()
    assert issues[0].args.get("delay_duration_minutes") == 120
    assert "Tiling, ground floor: 60%" in result.reply.text and "Cement used: 30 bags" in result.reply.text


async def test_a_breakdown_the_model_did_report_is_not_added_twice(two):
    issue = ("report_issue", {"issue_type": "EQUIPMENT_BREAKDOWN", "narrative": "mixer breakdown",
                              "delay_duration_minutes": 120})
    calls = [at("Site A2", c) for c in (LABOUR, TILING, CEMENT_USED, issue)]
    await two.say(FakeToolCallingProvider([calls, "Check it and tap Save."]), NOTE)
    assert len([i for i in await open_items(two) if i.kind == dr.KIND_ISSUE_OPEN]) == 1


async def test_a_correction_of_nothing_is_saved_as_new_information(two):
    """#4335: no open card and no saved card: the model is told it is new, and saves it."""
    correct = ("update_pending_card", {"card_id": "abc123", "item_index": 1, "changes": {"progress_percent": 70}})
    provider = FakeToolCallingProvider([[correct], [at("Site A2", TILING_70)], "Tiling 70% aayi. Save tap cheyyu."])
    result = await two.say(provider, "Site A2 ground floor tiling 70% aayi")
    assert result.run.calls[0].outcome.content["status"] == NOT_A_CORRECTION
    assert "Tiling, ground floor: 70%" in result.reply.text
    assert "✅ Save" in titles(result.reply)
    assert "open aayitilla" not in result.reply.text


async def test_a_new_figure_for_the_same_work_replaces_its_line(two):
    await two.say(FakeToolCallingProvider([[at("Site A2", TILING)], "Okay."]), "Site A2 ground floor tiling 60% aayi")
    result = await two.say(FakeToolCallingProvider([[at("Site A2", TILING_70)], "Okay."]), "Site A2 ground floor tiling 70% aayi")
    (item,) = await open_items(two)
    assert "70%" in item.summary
    assert "60%" not in result.reply.text


async def test_other_work_stays_beside_it(two):
    await two.say(FakeToolCallingProvider([[at("Site A2", TILING)], "Okay."]), "Site A2 ground floor tiling 60% aayi")
    putty = ("save_work_done", {"narrative": "first floor wall putty 200 sqft", "work_type": "wall putty",
                                "location": "first floor",
                                "quantities": [{"work_type": "wall putty", "quantity": 200, "unit": "sqft"}]})
    await two.say(FakeToolCallingProvider([[at("Site A2", putty)], "Okay."]), "Site A2 first floor wall putty 200 sqft")
    assert len(await open_items(two)) == 2


async def test_a_cancelled_card_never_comes_back(two):
    first = await two.say(FakeToolCallingProvider([[at("Site A2", TILING)], "Okay."]), "Site A2 ground floor tiling 60% aayi")
    await tap(two, first.reply, "Cancel")
    result = await two.say(FakeToolCallingProvider([[at("Site A2", LABOUR)], "Okay."]), "Site A2 5 mason 3 helper")
    assert "Tiling" not in result.reply.text
    assert [i.kind for i in await open_items(two)] == [dr.KIND_LABOUR]
