"""Request 104, D: the issue keeps its details.

The date (when not today), the hours lost and the severity are on the card and
saved; "since afternoon" with no hours is asked once; accidents and leaks get
their own types; "any open issues?" counts what the dashboard counts."""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")

from tests.replay.test_agent_replay import _make_world  # noqa: E402

from context import seed  # noqa: E402
from mesiri_ai.fakes import FakeToolCallingProvider  # noqa: E402
from runtime.agent import toolbox as tb  # noqa: E402
from runtime.agent.prompt import Turn  # noqa: E402
from runtime.agent.toolbox import (  # noqa: E402
    HOURS_OPTIONS,
    HOURS_QUESTION,
    classify_issue,
    needs_hours_question,
)


@pytest.fixture
async def world():  # noqa: ANN201
    return await _make_world(site_keys=(seed.SITE_A1,))


def _saved_fields(world):  # noqa: ANN001, ANN202
    return [dict(c.draft_action.fields) for c in world.dispatcher.dispatched]


# -- details are saved ------------------------------------------------------------


async def test_the_day_the_hours_and_the_severity_are_saved_with_the_issue(world):
    provider = FakeToolCallingProvider(
        [
            [
                (
                    "report_issue",
                    {
                        "issue_type": "WEATHER",
                        "narrative": "Heavy rain, work stopped",
                        "date": "yesterday",
                        "delay_duration_minutes": 180,
                        "severity": "HIGH",
                    },
                )
            ],
            "Heavy rain yesterday, 3 hours lost. Check it and tap Save.",
        ]
    )
    result = await world.say(provider, "Yesterday heavy rain, work stopped 3 hours")
    (fields,) = _saved_fields(world)
    assert fields["delay_duration_minutes"] == 180 and fields["severity"] == "HIGH"
    assert fields["occurred_date_source"] == "stated_by_user"
    line = [line for line in result.reply.text.split("\n") if "Issue (weather)" in line][0]
    assert "3 h lost" in line and "High severity" in line


# -- the hours lost are asked once ------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Rain since afternoon, work stopped",
        "Crane breakdown, work stopped since morning",
        "raavile muthal pani nirthi",
    ],
)
def test_since_without_hours_needs_the_question(text):
    assert needs_hours_question(text, {})


@pytest.mark.parametrize(
    "text, args",
    [
        ("Rain since 2 pm, work stopped 2 hours", {}),
        ("Rain since afternoon, work stopped", {"delay_duration_minutes": 120}),
        ("Rain stopped work", {}),
        ("Crane breakdown since morning, half day lost", {}),
    ],
)
def test_no_question_when_the_hours_are_said_or_there_is_no_start(text, args):
    assert not needs_hours_question(text, args)


async def test_since_afternoon_asks_about_hours_and_saves_nothing_yet(world):
    provider = FakeToolCallingProvider(
        [[("report_issue", {"issue_type": "WEATHER", "narrative": "Rain since afternoon, work stopped"})], "Sorry to hear that."]
    )
    result = await world.say(provider, "Rain since afternoon, work stopped")
    assert world.dispatcher.dispatched == []
    assert HOURS_QUESTION in result.reply.text
    assert [r.title for r in result.reply.buttons] == HOURS_OPTIONS


async def test_the_answer_saves_it_and_the_question_is_not_asked_again(world):
    turns = (Turn("Rain since afternoon, work stopped", HOURS_QUESTION),)
    provider = FakeToolCallingProvider(
        [
            [("report_issue", {"issue_type": "WEATHER", "narrative": "Rain since afternoon, work stopped", "delay_duration_minutes": 240})],
            "Rain since afternoon, 4 hours lost. Check it and tap Save.",
        ]
    )
    result = await world.say(provider, "4 hours", turns=turns)
    (fields,) = _saved_fields(world)
    assert fields["delay_duration_minutes"] == 240
    assert HOURS_QUESTION not in result.reply.text


async def test_even_an_answer_that_leaves_the_hours_out_is_not_asked_twice(world):
    turns = (Turn("Rain since afternoon, work stopped", HOURS_QUESTION),)
    provider = FakeToolCallingProvider(
        [[("report_issue", {"issue_type": "WEATHER", "narrative": "Rain since afternoon, work stopped"})], "Check it and tap Save."]
    )
    await world.say(provider, "Rain since afternoon, work stopped", turns=turns)
    assert len(world.dispatcher.dispatched) == 1


# -- the new types ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Worker fell from scaffolding, minor injury",
        "mason got hurt on site",
        "accident at the gate",
        "a helper slipped and fell near the stairs",
    ],
)
def test_an_accident_is_safety_and_high(text):
    out = classify_issue(text, {"issue_type": "OTHER", "narrative": text, "severity": "LOW"})
    assert out["issue_type"] == "SAFETY" and out["severity"] == "HIGH"


def test_a_safety_issue_keeps_a_critical_severity():
    out = classify_issue("worker died in the accident", {"issue_type": "SAFETY", "severity": "CRITICAL"})
    assert out["severity"] == "CRITICAL"


@pytest.mark.parametrize("text", ["Water leakage in 2nd floor bathroom", "cracks in the beam", "seepage on the wall"])
def test_a_leak_or_crack_left_as_other_is_quality(text):
    assert classify_issue(text, {"issue_type": "OTHER", "narrative": text})["issue_type"] == "QUALITY"


@pytest.mark.parametrize(
    "text, kind",
    [
        ("bricks fell from the lorry", "OTHER"),
        ("pump is leaking, motor burnt", "EQUIPMENT_BREAKDOWN"),
        ("no cement left", "MATERIAL_SHORTAGE"),
    ],
)
def test_other_problems_keep_the_type_the_model_chose(text, kind):
    assert classify_issue(text, {"issue_type": kind, "narrative": text})["issue_type"] == kind


async def test_an_injury_is_saved_as_safety_with_a_high_severity(world):
    provider = FakeToolCallingProvider(
        [[("report_issue", {"issue_type": "OTHER", "narrative": "Worker fell from scaffolding, minor injury"})], "Check it and tap Save."]
    )
    result = await world.say(provider, "Worker fell from scaffolding, minor injury")
    (fields,) = _saved_fields(world)
    assert fields["issue_type"] == "SAFETY" and fields["severity"] == "HIGH"
    assert "Issue (safety / accident)" in result.reply.text


async def test_a_leak_is_saved_as_quality(world):
    provider = FakeToolCallingProvider(
        [[("report_issue", {"issue_type": "OTHER", "narrative": "Water leakage in 2nd floor bathroom"})], "Check it and tap Save."]
    )
    result = await world.say(provider, "Water leakage in 2nd floor bathroom")
    (fields,) = _saved_fields(world)
    assert fields["issue_type"] == "QUALITY"
    assert "Issue (leakage / quality)" in result.reply.text


def test_the_database_and_the_validation_know_the_new_types():
    from mesiri.domains.progress.validation import _VALID_ISSUE_TYPES
    from mesiri.infrastructure.postgres.repositories.progress import VALID_ISSUE_TYPES
    from runtime.agent.tools import tool_specs

    spec = next(s for s in tool_specs() if s.name == "report_issue")
    enum = set(spec.parameters["properties"]["issue_type"]["enum"])
    assert {"SAFETY", "QUALITY"} <= enum <= set(VALID_ISSUE_TYPES) == set(_VALID_ISSUE_TYPES)
    assert tb.classify_issue  # (the type list above is the one the tool offers)


# -- "any open issues?" ------------------------------------------------------------


def _log(open_issues, count):  # noqa: ANN001, ANN202
    from types import SimpleNamespace

    from workflows.activity_query.nodes import generate_activity_search_reply

    state = {
        "collected_fields": {
            "activity_search_results": {
                "date_range_label": "today",
                "activities": [],
                "activity_count": 0,
                "open_issues": open_issues,
                "open_issue_count": count,
            }
        }
    }
    assert SimpleNamespace  # (state is a plain dict)
    return generate_activity_search_reply(state)["pending_prompt"]


def test_a_being_handled_issue_is_listed_as_open_and_says_so():
    text = _log(
        [
            {"issue_type": "EQUIPMENT_BREAKDOWN", "narrative": "Crane breakdown", "severity": "HIGH", "status": "ACKNOWLEDGED"},
            {"issue_type": "MATERIAL_SHORTAGE", "narrative": "Cement low", "severity": "MEDIUM", "status": "OPEN"},
        ],
        2,
    )
    assert "2 open issues" in text
    assert "• Equipment Breakdown — Crane breakdown (High, being handled)" in text
    assert "• Material Shortage — Cement low (Medium)" in text


def test_up_to_twenty_are_listed_and_the_rest_are_counted():
    rows = [{"issue_type": "OTHER", "narrative": f"Problem {n}", "severity": "LOW", "status": "OPEN"} for n in range(20)]
    text = _log(rows, 27)
    assert text.count("• Other — Problem") == 20
    assert text.rstrip().endswith("+7 more")
    assert "+" not in _log(rows, 20).split("issues", 1)[1]


def test_the_search_counts_open_and_acknowledged():
    import inspect

    from runtime import activity_search_service

    source = inspect.getsource(activity_search_service)
    assert '.in_(["OPEN", "ACKNOWLEDGED"])' in source


# -- a question ends the reply: no card is left looking saved ------------------------


async def test_a_card_prepared_beside_the_hours_question_is_not_listed_as_saved(world):
    """Live 24 Oct: the weather card was prepared, then the hours question ended
    the reply, which listed "✅ Saved: Weather: Rainy" with no button to tap."""
    from tests.unit.request104_fakes import FakeActions

    world.actions = FakeActions()
    provider = FakeToolCallingProvider(
        [
            [
                ("set_site_conditions", {"weather": "rainy"}),
                ("report_issue", {"issue_type": "WEATHER", "narrative": "Rain since afternoon, work stopped"}),
            ],
            "Sorry to hear that.",
        ]
    )
    result = await world.say(provider, "Rain since afternoon, work stopped")
    assert HOURS_QUESTION in result.reply.text
    assert "Saved" not in result.reply.text and "Weather" not in result.reply.text
    assert world.last_gateway.action_items == []
