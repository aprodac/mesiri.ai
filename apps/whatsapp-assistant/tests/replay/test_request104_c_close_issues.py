"""Request 104, C: closing issues from WhatsApp.

"Crane is repaired" offered to close "Cement running low (MATERIAL_SHORTAGE)":
the old close-out took the latest reported issue. Now the issue is matched by
the sender's words, the open issues are listed when it is unclear, several
close in one card, and the card is "📝 To close: ..." with Save / Cancel."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")

from tests.replay.test_agent_replay import _make_world  # noqa: E402
from tests.unit.request104_fakes import FakeActions, FakeDispatcher  # noqa: E402

from context import seed  # noqa: E402
from mesiri_ai.fakes import FakeToolCallingProvider  # noqa: E402
from runtime.agent import save_button as sb  # noqa: E402
from runtime.agent.action_entry import ActionEntry  # noqa: E402
from runtime.agent.issue_match import MAX_LISTED, SOMETHING_ELSE  # noqa: E402


def _issue(n: int, narrative: str, issue_type: str, day: int, **kw):  # noqa: ANN001, ANN202
    return {
        "id": f"00000000-0000-4000-8000-{n:012d}",
        "site_id": "11111111-1111-4111-8111-000000000002",
        "issue_type": issue_type,
        "severity": "MEDIUM",
        "narrative": narrative,
        "status": "OPEN",
        "occurred_at": dt.datetime(2026, 10, day, 6, 0, tzinfo=dt.UTC),
        **kw,
    }


CEMENT = _issue(2, "Cement running low", "MATERIAL_SHORTAGE", 21)
CRANE = _issue(1, "Crane breakdown, work stopped", "EQUIPMENT_BREAKDOWN", 20)
CRANE_2 = _issue(3, "Crane cable snapped", "EQUIPMENT_BREAKDOWN", 19)


@pytest.fixture(autouse=True)
def _placed(monkeypatch):  # noqa: ANN001, ANN201
    from runtime.agent.entry_base import Scoped

    async def settle(self, message, understanding, candidate, **kwargs):  # noqa: ANN001, ANN003, ANN202
        ctx = (await self.context_resolver.resolve(message, understanding)).unwrap()
        return Scoped(ctx, str(ctx.organization_id), "11111111-1111-4111-8111-000000000001",
                      "11111111-1111-4111-8111-000000000002", None, None)

    monkeypatch.setattr(ActionEntry, "settle", settle)


async def _world(issues):  # noqa: ANN001, ANN202
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.dispatcher_for_close = FakeDispatcher()
    world.actions = FakeActions(dispatcher=world.dispatcher_for_close)

    async def open_issues(scoped):  # noqa: ANN001, ANN202
        return list(issues)  # newest first, as the query returns them

    world.open_issues = open_issues
    return world


async def _say(world, text, args):  # noqa: ANN001, ANN202
    provider = FakeToolCallingProvider([[("update_issue", {"action": "resolve", **args})], "Done. Tap Save."])
    return await world.say(provider, text)


def _tap(world, action):  # noqa: ANN001, ANN202
    return SimpleNamespace(metadata={"interactive_reply_id": sb.tap_id(action, world.last_gateway.action_facts())})


async def test_crane_repaired_offers_the_crane_issue_not_the_cement_one():
    world = await _world([CEMENT, CRANE])
    result = await _say(world, "Crane is repaired", {"about": ["crane"]})
    assert "📝 To close: Crane breakdown (since 20 Oct)" in result.reply.text
    assert "Cement" not in result.reply.text
    assert "MATERIAL_SHORTAGE" not in result.reply.text and "EQUIPMENT_BREAKDOWN" not in result.reply.text
    assert "Reply YES" not in result.reply.text
    assert world.dispatcher_for_close.dispatched == []  # nothing before the tap
    spec = sb.with_save_buttons(result.reply, world.last_gateway.action_facts())
    assert [row.title for row in spec.buttons] == ["✅ Save", "❌ Cancel"]


async def test_save_closes_exactly_that_issue_through_the_shared_dispatcher():
    world = await _world([CEMENT, CRANE])
    await _say(world, "Crane is repaired", {"about": ["crane"]})
    reply = await sb.handle_tap(_tap(world, sb.SAVE), world.actor, world.handler, actions=world.actions)
    (confirmed,) = world.dispatcher_for_close.dispatched
    import uuid

    uuid.UUID(confirmed.workflow_instance_id)  # the database keys workflow instances by UUID
    fields = confirmed.draft_action.fields
    assert fields == {"site_issue_id": CRANE["id"], "action": "resolve"}
    assert confirmed.draft_action.action_type.value == "close_site_issue"
    assert reply.text == "✅ Closed: Crane breakdown (since 20 Oct)."


async def test_cancel_closes_nothing():
    world = await _world([CEMENT, CRANE])
    await _say(world, "Crane is repaired", {"about": ["crane"]})
    await sb.handle_tap(_tap(world, sb.CANCEL), world.actor, world.handler, actions=world.actions)
    assert world.dispatcher_for_close.dispatched == []


async def test_two_issues_that_fit_are_listed_not_guessed():
    world = await _world([CEMENT, CRANE, CRANE_2])
    result = await _say(world, "Crane is repaired", {"about": ["crane"]})
    assert world.last_gateway.action_items == []
    titles = [r.title for r in result.reply.buttons or result.reply.list_rows]
    assert titles == ["Crane breakdown", "Crane cable snapped", SOMETHING_ELSE]


async def test_no_words_lists_the_open_issues_newest_first_up_to_nine_and_something_else():
    many = [_issue(n, f"Problem {n} at gate", "OTHER", 24) for n in range(12, 0, -1)]
    world = await _world(many)
    result = await _say(world, "it is fixed", {})
    rows = result.reply.list_rows
    assert len(rows) == MAX_LISTED + 1
    assert rows[0].title.startswith("Problem 12") and rows[-1].title == SOMETHING_ELSE


async def test_the_issue_they_pick_from_the_list_is_the_one_closed():
    world = await _world([CEMENT, CRANE, CRANE_2])
    result = await _say(world, "Crane breakdown", {"about": ["Crane breakdown"]})
    assert "To close: Crane breakdown (since 20 Oct)" in result.reply.text
    assert len(world.last_gateway.action_items) == 1


async def test_both_are_fixed_closes_several_on_one_card():
    world = await _world([CEMENT, CRANE])
    result = await _say(world, "Both are fixed", {"all_issues": True})
    lines = result.reply.text.split("\n")
    assert "📝 To close:" in lines
    assert "• Crane breakdown (since 20 Oct)" in lines and "• Cement running low (since 21 Oct)" in lines
    reply = await sb.handle_tap(_tap(world, sb.SAVE), world.actor, world.handler, actions=world.actions)
    assert sorted(c.draft_action.fields["site_issue_id"] for c in world.dispatcher_for_close.dispatched) == sorted(
        [CRANE["id"], CEMENT["id"]]
    )
    assert reply.text.count("✅ Closed:") == 2


async def test_nothing_open_is_said_plainly():
    world = await _world([])
    result = await _say(world, "Crane is repaired", {"about": ["crane"]})
    (call,) = result.run.calls
    assert "no open issues" in call.outcome.content["message"].lower()
    assert world.last_gateway.action_items == []


async def test_two_issues_that_read_the_same_are_told_apart_by_their_day():
    twin = _issue(4, "Crane breakdown", "EQUIPMENT_BREAKDOWN", 22)
    world = await _world([twin, CRANE])
    result = await _say(world, "Crane is repaired", {"about": ["crane"]})
    titles = [r.title for r in result.reply.buttons or result.reply.list_rows]
    assert titles == ["Crane breakdown · 22 Oct", "Crane breakdown · 20 Oct", SOMETHING_ELSE]


async def test_a_close_that_fails_is_not_called_closed():
    world = await _world([CRANE])
    world.actions._dispatcher = FakeDispatcher(succeed=False)
    await _say(world, "Crane is repaired", {"about": ["crane"]})
    reply = await sb.handle_tap(_tap(world, sb.SAVE), world.actor, world.handler, actions=world.actions)
    assert reply.text.startswith("❌ Couldn't close") and "Closed" not in reply.text


async def test_two_issues_of_the_same_words_are_told_apart_by_the_picked_day():
    a = _issue(5, "Rain today", "WEATHER", 21)
    b = _issue(6, "Rain today", "WEATHER", 19)
    world = await _world([a, b])
    result = await _say(world, "Rain today · 21 Oct", {"about": ["Rain today · 21 Oct"]})
    assert "To close: Rain today (since 21 Oct)" in result.reply.text


async def test_a_card_line_the_model_wrote_itself_is_not_doubled():
    world = await _world([CEMENT, CRANE])
    provider = FakeToolCallingProvider(
        [
            [("update_issue", {"action": "resolve", "about": ["crane"]})],
            "Okay, the crane is fixed.\n\n📝 To close: Crane breakdown (since 20 Oct)",
        ]
    )
    result = await world.say(provider, "Crane is repaired")
    assert result.reply.text.count("To close: Crane breakdown") == 1
