"""The three tools back from the classic pipeline, through the real journey:
the model's call -> the change entry -> the real workflow graph, which asks
for Yes before anything changes (22 Oct)."""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")

from tests.replay.test_agent_replay import _make_world  # noqa: E402
from tests.unit.test_change_entry import _DayFacts, _fact, _Members  # noqa: E402

from context import seed  # noqa: E402
from mesiri_ai.fakes import FakeToolCallingProvider  # noqa: E402
from workflows.entities import Resolved  # noqa: E402


async def _say(world, call, reply="Done."):  # noqa: ANN001
    result = await world.say(FakeToolCallingProvider([[call], reply]), "message")
    (step,) = [c.outcome.content for c in result.run.calls]
    return result, step


async def test_adding_a_known_person_asks_for_yes_and_saves_nothing_yet():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    import dataclasses

    world.actor = dataclasses.replace(world.actor, role="PROJECT_MANAGER")
    world.change = {"member_resolver": _Members(Resolved(entity_id="u1", display_name="Ravi Kumar"))}
    result, step = await _say(world, ("add_member", {"name": "ravi", "role": "supervisor"}))
    assert step["status"] == "waiting_for_user", step
    assert "Ravi Kumar" in result.reply.text
    assert world.dispatcher.dispatched == []


async def test_a_correction_with_its_target_asks_for_yes():
    world = await _make_world(site_keys=(seed.SITE_A1,))

    async def remembered() -> str:
        return "a1"

    world.change = {"day_facts": _DayFacts([_fact("progress_update", "p9", "a1", 180)]), "remembered_activity": remembered}
    result, step = await _say(world, ("correct_work_quantity", {"new_quantity": 150}))
    assert step["status"] == "waiting_for_user", step
    assert "150" in result.reply.text and world.dispatcher.dispatched == []


async def test_nothing_to_correct_is_said_plainly():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.change = {"day_facts": _DayFacts()}
    _, step = await _say(world, ("correct_work_quantity", {"new_quantity": 150}))
    assert step["status"] == "answer" and step["text"], step


async def test_fixed_shows_a_to_close_card_and_closes_nothing_before_the_tap():
    """Request 104, C: "resolve" is a Save / Cancel card naming the issue by the
    sender's words; the old Yes / No question is for the other actions."""
    import datetime as dt

    from tests.unit.request104_fakes import FakeActions, FakeDispatcher

    world = await _make_world(site_keys=(seed.SITE_A1,))
    dispatcher = FakeDispatcher()
    world.actions = FakeActions(dispatcher=dispatcher)

    async def open_issues(scoped):  # noqa: ANN001, ANN202
        return [
            {"id": "i7", "issue_type": "EQUIPMENT_BREAKDOWN", "severity": "HIGH", "narrative": "JCB breakdown",
             "status": "OPEN", "occurred_at": dt.datetime(2026, 10, 19, 5, 0, tzinfo=dt.UTC)},
        ]

    world.open_issues = open_issues
    result, step = await _say(world, ("update_issue", {"action": "resolve", "about": ["jcb"]}))
    assert step["status"] == "saved", step
    assert "*To close*: JCB breakdown" in result.reply.text
    assert dispatcher.dispatched == []
