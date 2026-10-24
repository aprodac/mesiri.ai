"""Request 104, B: weather, site working and tomorrow's plan from WhatsApp.

The dashboard's setter (``PostgresDprRepository.set_site_day_conditions``,
BE-14) is reused unchanged; the Save tap calls it. "Tomorrow plan: ..." is never
"noted" without being saved."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")

from tests.replay.test_agent_replay import _make_world  # noqa: E402
from tests.unit.request104_fakes import FakeActions  # noqa: E402

from context import seed  # noqa: E402
from mesiri.application.dpr import site_day  # noqa: E402
from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository  # noqa: E402
from mesiri_ai.fakes import FakeToolCallingProvider  # noqa: E402
from runtime.agent import save_button as sb  # noqa: E402
from runtime.agent.action_entry import ActionEntry  # noqa: E402


@pytest.fixture
def setter(monkeypatch):  # noqa: ANN001, ANN201
    """The shared setter, recording what it was asked."""
    calls: list[dict] = []

    async def set_site_day_conditions(self, **kwargs):  # noqa: ANN001, ANN003, ANN202
        site_day.validate_conditions(kwargs["changes"])  # the dashboard's own validation
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(PostgresDprRepository, "set_site_day_conditions", set_site_day_conditions)
    return calls


PROJECT = "11111111-1111-4111-8111-000000000001"
SITE = "11111111-1111-4111-8111-000000000002"


@pytest.fixture(autouse=True)
def _placed(monkeypatch):  # noqa: ANN001, ANN201
    """The sender is placed at one site by ``EntryScope.settle`` (tested with
    every entry); the seed world's ids are not database ids, so it is fixed."""
    from runtime.agent.entry_base import Scoped

    async def settle(self, message, understanding, candidate, **kwargs):  # noqa: ANN001, ANN003, ANN202
        ctx = await self.context_resolver.resolve(message, understanding)
        ctx = ctx.unwrap()
        return Scoped(ctx, str(ctx.organization_id), PROJECT, SITE, PROJECT, SITE)

    monkeypatch.setattr(ActionEntry, "settle", settle)


async def _world():  # noqa: ANN202
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.actions = FakeActions()
    return world


def _tap(world, action):  # noqa: ANN001, ANN202
    facts = [*(h for h in []), *world.last_gateway.action_facts()]
    return SimpleNamespace(metadata={"interactive_reply_id": sb.tap_id(action, facts)})


async def test_rain_and_half_day_is_a_card_and_save_sets_it_through_the_shared_setter(setter):
    world = await _world()
    provider = FakeToolCallingProvider(
        [
            [("set_site_conditions", {"weather": "rainy", "site_working": "half"})],
            "Rainy, half day. Please check it and tap Save.",
        ]
    )
    result = await world.say(provider, "It rained, only half day work")
    assert "Weather: Rainy · Site working: Half day" in result.reply.text
    assert setter == []  # nothing before the tap
    reply = await sb.handle_tap(_tap(world, sb.SAVE), world.actor, world.handler, actions=world.actions)
    assert [c["changes"] for c in setter] == [{"weather": "rainy", "site_working": "half"}]
    assert reply.text.startswith("✅ Saved: Weather: Rainy")


async def test_cancel_sets_nothing(setter):
    world = await _world()
    provider = FakeToolCallingProvider([[("set_site_conditions", {"weather": "sunny"})], "Sunny. Tap Save."])
    await world.say(provider, "sunny today")
    await sb.handle_tap(_tap(world, sb.CANCEL), world.actor, world.handler, actions=world.actions)
    assert setter == []


async def test_tomorrows_plan_is_saved_on_the_tap(setter):
    world = await _world()
    text = "Tomorrow plan: 2nd floor slab casting, need 15 workers"
    provider = FakeToolCallingProvider(
        [
            [("set_site_conditions", {"tomorrow_plan": "2nd floor slab casting, need 15 workers"})],
            "Tomorrow: 2nd floor slab casting, 15 workers. Check it and tap Save.",
        ]
    )
    result = await world.say(provider, text)
    assert "Tomorrow's plan: 2nd floor slab casting, need 15 workers" in result.reply.text
    await sb.handle_tap(_tap(world, sb.SAVE), world.actor, world.handler, actions=world.actions)
    assert setter[0]["changes"] == {"tomorrow_plan": "2nd floor slab casting, need 15 workers"}


async def test_tomorrows_plan_is_never_just_noted(setter):
    """The model answers "Noted" and calls nothing: the card is made anyway."""
    world = await _world()
    provider = FakeToolCallingProvider(["Noted, I will remember tomorrow's plan."])
    result = await world.say(provider, "Tomorrow plan: 2nd floor slab casting, need 15 workers")
    assert len(world.last_gateway.action_items) == 1
    assert "Tomorrow's plan: 2nd floor slab casting, need 15 workers" in result.reply.text
    assert "noted" not in result.reply.text.lower()
    assert setter == []
    await sb.handle_tap(_tap(world, sb.SAVE), world.actor, world.handler, actions=world.actions)
    assert len(setter) == 1


async def test_rain_that_stopped_work_is_one_card_with_the_weather_and_the_hours_lost(setter):
    world = await _world()

    async def settle_drafts(**kwargs):  # noqa: ANN003, ANN202
        return SimpleNamespace(done=list(kwargs["facts"]), refused=[])

    world.handler.settle_drafts = settle_drafts
    provider = FakeToolCallingProvider(
        [
            [
                ("set_site_conditions", {"weather": "rainy", "hours_lost": 2}),
                ("report_issue", {"issue_type": "WEATHER", "narrative": "Rain since 2 pm, work stopped", "delay_duration_minutes": 120}),
            ],
            "Rain since 2 pm, work stopped for 2 hours. Check it and tap Save.",
        ]
    )
    result = await world.say(provider, "Rain since 2 pm, work stopped 2 hours")
    lines = result.reply.text.split("\n")
    assert any(line.startswith("• Weather: Rainy") for line in lines)
    assert any(line.startswith("• Issue (weather)") for line in lines)
    assert len(world.last_gateway.card_items) == 2  # one card, two items
    facts = [*(h for h in []), *world.last_gateway.action_facts()]
    # The tap carries the issue draft and the pending weather together.
    from runtime.agent.save_button import card_plan

    plan, all_facts = card_plan(
        world.last_gateway.handled, before=[], after=[i.fact for i in world.last_gateway.action_items]
    )
    assert plan == "card" and len(all_facts) == 2
    tap = SimpleNamespace(metadata={"interactive_reply_id": sb.tap_id(sb.SAVE, all_facts)})
    reply = await sb.handle_tap(tap, world.actor, world.handler, actions=world.actions)
    assert setter[0]["changes"] == {"weather": "rainy", "hours_lost": 2.0}
    assert "✅ Saved." in reply.text and "Weather: Rainy" in reply.text
    assert facts


async def test_a_confirmed_day_is_refused_plainly(monkeypatch):
    async def refuse(self, **kwargs):  # noqa: ANN001, ANN003, ANN202
        raise site_day.InvalidSiteDayTransition("this day is already CONFIRMED")

    monkeypatch.setattr(PostgresDprRepository, "set_site_day_conditions", refuse)
    world = await _world()
    provider = FakeToolCallingProvider([[("set_site_conditions", {"weather": "rainy"})], "Rainy. Tap Save."])
    await world.say(provider, "rain today")
    reply = await sb.handle_tap(_tap(world, sb.SAVE), world.actor, world.handler, actions=world.actions)
    assert "already confirmed" in reply.text and "Saved" not in reply.text
