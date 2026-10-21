"""WA-37: under the agent the old pipeline never splits a tool call again.

Cement used "for slab" is one tool call; the classic canonicalizer also reads
"slab" as continued work and adds a second step. Under the agent that second
step became a plan the model never saw, answered later by the old closing
summary ("Here's what I did ... Which site is this for?"). Only the first
event may reach the plan; the classic path still splits as before.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")

from tests.replay.test_agent_replay import _make_world  # noqa: E402

import runtime.inbound_journey.process as process  # noqa: E402
from context import seed  # noqa: E402
from mesiri_ai.fakes import FakeToolCallingProvider  # noqa: E402

USAGE_FOR_SLAB = ("save_material_usage", {"material": "cement", "quantity": 20, "unit": "bags", "work_item": "slab"})


async def _planned_events(monkeypatch, *, agent: bool) -> list[str]:
    planned: list[list[str]] = []

    def spy(events, **_kw):
        planned.append([e.event_type.value for e in events])
        return SimpleNamespace(plan=None)

    monkeypatch.setattr(process, "build_plan_from_segments", spy)
    world = await _make_world(site_keys=(seed.SITE_A1,), direct=False)  # the classic route's planning
    real = process.process_inbound_message

    async def with_plan_store(*args, **kwargs):
        pipeline = kwargs["pipeline"]
        if not agent:
            pipeline.one_event_per_call = False  # the classic reading of the same candidate
        return await real(*args, plan_store=AsyncMock(), **kwargs)

    monkeypatch.setattr("tests.replay.test_agent_replay.process_inbound_message", with_plan_store)
    await world.say(FakeToolCallingProvider([[USAGE_FOR_SLAB], ""]), "slab-inu 20 bag cement use cheythu")
    return planned[0]


async def test_the_agent_plans_only_the_tool_calls_own_event(monkeypatch):
    assert await _planned_events(monkeypatch, agent=True) == ["MaterialUsageRequested"]


async def test_the_classic_path_still_adds_the_work_step(monkeypatch):
    assert await _planned_events(monkeypatch, agent=False) == [
        "MaterialUsageRequested",
        "ActivityContinuationRequested",
    ]


async def test_the_direct_route_runs_no_old_journey_and_saves_one_record():
    """ARCH-01: a known material goes straight to its workflow -- no
    canonicalizer, planner or second step at all."""
    world = await _make_world(site_keys=(seed.SITE_A1,))
    result = await world.say(
        FakeToolCallingProvider([[USAGE_FOR_SLAB], "20 bag cement slab-inu. Save tap cheyyu."]),
        "slab-inu 20 bag cement use cheythu",
    )
    assert world.journeys == 0
    assert result.outcome == "ok"
    [confirmed] = world.dispatcher.dispatched
    fields = confirmed.draft_action.fields
    assert (fields["material_name"], fields["quantity"], fields["work_item"]) == ("cement", 20.0, "slab")
    assert fields["occurred_date_source"] == "inferred_at_confirmation"


async def test_a_name_that_is_not_in_the_catalogue_is_asked_not_picked():
    """ARCH-04: no old picker and no held report -- the model is told the
    options and asks; nothing is saved."""
    world = await _make_world(site_keys=(seed.SITE_A1,))
    call = ("save_material_receipt", {"material": "fevicol", "quantity": 2, "unit": "tins"})
    result = await world.say(FakeToolCallingProvider([[call], "Which material was it?"]), "2 tin fevicol vannu")
    assert world.journeys == 0
    assert world.dispatcher.dispatched == []
    [record] = result.run.calls
    assert record.outcome.content["status"] == "choose"
