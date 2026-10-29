"""Request 124, P1: a pending action of request 104 (the day's conditions, a
question for the engineer) is a line of the same card; the one Save tap runs it
after everything else is written, and Cancel drops it."""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")

from tests.replay.test_agent_replay import _make_world  # noqa: E402
from tests.replay.test_draft_per_message_p1 import LABOUR, press, titles  # noqa: E402
from tests.unit.request104_fakes import FakeActions  # noqa: E402

from context import seed  # noqa: E402
from mesiri.application.dpr import site_day  # noqa: E402
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository  # noqa: E402
from mesiri_ai.fakes import FakeToolCallingProvider  # noqa: E402
from runtime.agent import draft as dr  # noqa: E402
from runtime.agent.action_entry import ActionEntry  # noqa: E402
from runtime.agent.draft_store import MemoryDraftStore  # noqa: E402

PROJECT = "11111111-1111-4111-8111-000000000001"
SITE = "11111111-1111-4111-8111-000000000002"


@pytest.fixture
def setter(monkeypatch):  # noqa: ANN001, ANN201
    calls: list[dict] = []

    async def set_site_day_conditions(self, **kwargs):  # noqa: ANN001, ANN003, ANN202
        site_day.validate_conditions(kwargs["changes"])
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(PostgresDprRepository, "set_site_day_conditions", set_site_day_conditions)
    return calls


@pytest.fixture(autouse=True)
def _placed(monkeypatch):  # noqa: ANN001, ANN201
    from runtime.agent.entry_base import Scoped

    async def settle(self, message, understanding, candidate, **kwargs):  # noqa: ANN001, ANN003, ANN202
        ctx = (await self.context_resolver.resolve(message, understanding)).unwrap()
        return Scoped(ctx, str(ctx.organization_id), PROJECT, SITE, PROJECT, SITE)

    monkeypatch.setattr(ActionEntry, "settle", settle)


async def _world():  # noqa: ANN202
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.actions = FakeActions()
    world.draft_v2, world.drafts = True, MemoryDraftStore()
    return world


CONDITIONS = ("set_site_conditions", {"weather": "rainy", "site_working": "half"})


async def test_labour_and_the_days_conditions_are_one_card_and_one_save(setter):
    world = await _world()
    result = await world.say(
        FakeToolCallingProvider([[LABOUR, CONDITIONS], "Check it and tap Save."]), "3 masons 12 helpers, rain, half day"
    )
    assert "15 workers (3 mason, 12 helper)" in result.reply.text
    assert "Weather: Rainy · Site working: Half day" in result.reply.text
    assert titles(result.reply) == ["✅ Save", "❌ Cancel"]
    assert world.dispatcher.dispatched == [] and setter == []  # nothing before the tap

    out, _ = await press(world, result.reply, "✅ Save")
    assert len(world.dispatcher.dispatched) == 1
    assert [c["changes"] for c in setter] == [{"weather": "rainy", "site_working": "half"}]
    assert out.text.startswith("✅ Saved: 15 workers (3 mason, 12 helper); ")


async def test_cancel_drops_the_action_with_the_rest(setter):
    world = await _world()
    result = await world.say(
        FakeToolCallingProvider([[LABOUR, CONDITIONS], "Check it and tap Save."]), "3 masons 12 helpers, rain, half day"
    )
    out, _ = await press(world, result.reply, "❌ Cancel")
    assert out.text == dr.CANCELLED
    assert world.dispatcher.dispatched == [] and setter == []
    assert await world.actions.store.take(world.actor, "0" * 32) is None


async def test_a_failed_write_runs_no_action(setter):
    """The action runs only after the writes committed: a rolled-back Save has
    sent and set nothing."""
    from tests.replay.test_draft_per_message_p1 import _FailsOn

    world = await _world()
    result = await world.say(
        FakeToolCallingProvider([[LABOUR, CONDITIONS], "Check it and tap Save."]), "3 masons 12 helpers, rain, half day"
    )
    world.handler._dispatcher = _FailsOn(world.dispatcher, 1)
    out, _ = await press(world, result.reply, "✅ Save")
    assert out.text.startswith("Nothing was saved")
    assert setter == []
