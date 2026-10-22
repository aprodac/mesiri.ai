"""The three tools back from the classic pipeline, through the real journey:
the model's call -> the change entry -> the real workflow graph, which asks
for Yes before anything changes (22 Oct)."""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")

from tests.replay.test_agent_replay import _make_world  # noqa: E402
from tests.unit.test_change_entry import _Activities, _Issues, _Members  # noqa: E402

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

    world.change = {"activity_query": _Activities(), "remembered_activity": remembered}
    result, step = await _say(world, ("correct_work_quantity", {"new_quantity": 150}))
    assert step["status"] == "waiting_for_user", step
    assert "150" in result.reply.text and world.dispatcher.dispatched == []


async def test_nothing_to_correct_is_said_plainly():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.change = {"activity_query": _Activities()}
    _, step = await _say(world, ("correct_work_quantity", {"new_quantity": 150}))
    assert step["status"] == "answer" and step["text"], step


async def test_fixed_closes_the_latest_issue_after_yes():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.change = {"site_issue_query": _Issues()}
    result, step = await _say(world, ("update_issue", {"action": "resolve"}))
    assert step["status"] == "waiting_for_user", step
    assert "JCB" in result.reply.text or "breakdown" in result.reply.text.lower()
