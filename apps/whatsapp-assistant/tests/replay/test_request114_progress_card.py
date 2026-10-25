"""Request 114: work done on an open activity is a Save / Cancel card, not a
"Saved" reply over a bare Yes / No. Live 25 Oct: "plastering 50 sq ft done
today" answered "✅ Saved ... Wrong? Reply UNDO." with Yes / No buttons, while
nothing was saved and the next message was refused."""

from __future__ import annotations

from types import SimpleNamespace

from tests.replay.test_agent_replay import world, world_two_sites  # noqa: F401  (fixtures)

from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.draft_action import DraftActionType

ACTIVITY = "11111111-1111-4111-8111-111111111111"
S1 = "22222222-2222-4222-8222-222222222222"
S2 = "33333333-3333-4333-8333-333333333333"
MANGLISH = ("theernnu", "cheythu", "cheyyu", "-il ")


class _OpenPlastering:
    async def find_open_activities(self, **kwargs):  # noqa: ANN003, ANN202
        return [{"activity_id": ACTIVITY, "work_type": "plastering", "narrative": "plastering"}]


def _work_done(*, site: str | None = None):  # noqa: ANN202
    args = {
        "narrative": "plastering 50 sq ft done", "work_type": "plastering",
        "quantities": [{"work_type": "plastering", "quantity": 50, "unit": "sq ft"}],
        "update_kind": "completed", "continues": "plastering",
    }
    if site:
        args["site"] = site
    return [
        [("save_work_done", args)],
        # The live model wrote this in Manglish and claimed a save.
        "Ok, Green Villa site-il 50 sq ft plastering theernnu. ✅ Saved: Plastering 50 sq ft. Wrong? Reply UNDO.",
    ]


async def test_work_done_is_a_save_cancel_card_that_claims_nothing(world_two_sites):  # noqa: F811
    world = world_two_sites  # noqa: F811
    world.site = {"activity_query": _OpenPlastering()}
    result = await world.say(FakeToolCallingProvider(_work_done(site="Site A2")), "plastering 50 sq ft done today")

    reply = result.reply
    assert "📝 To save: Plastering: 50 sq ft (completed)" in reply.text
    assert [b.title for b in reply.buttons] == ["✅ Save", "❌ Cancel"]
    low = reply.text.casefold()
    assert "saved" not in low and "undo" not in low and "yes" not in low
    assert not any(word in low for word in MANGLISH)  # English message, English reply
    assert world.dispatcher.dispatched == []  # nothing is written before Save


async def test_save_writes_it_and_the_next_message_is_not_blocked(world):  # noqa: F811
    world.site = {"activity_query": _OpenPlastering()}
    await world.say(FakeToolCallingProvider(_work_done()), "plastering 50 sq ft done today")
    assert world.dispatcher.dispatched == []

    handled = await world.handler.handle_fast_path(world.actor.user_id, world.message("✅ Save"))
    assert handled is not None
    (confirmed,) = world.dispatcher.dispatched
    assert confirmed.draft_action.action_type is DraftActionType.ADD_PROGRESS_UPDATE
    assert confirmed.draft_action.fields["activity_id"] == ACTIVITY

    provider = FakeToolCallingProvider(
        [[("save_material_receipt", {"material": "cement", "quantity": 50, "unit": "bags"})], "Cement is on the card."]
    )
    nxt = await world.say(provider, "50 bags cement arrived")
    (call,) = nxt.run.calls
    assert call.outcome.content["status"] != "error"
    assert "earlier entry" not in nxt.reply.text
    assert "Cement in: 50 bags" in nxt.reply.text


async def test_cancel_drops_it(world):  # noqa: F811
    world.site = {"activity_query": _OpenPlastering()}
    await world.say(FakeToolCallingProvider(_work_done()), "plastering 50 sq ft done today")
    await world.handler.handle_fast_path(world.actor.user_id, world.message("❌ Cancel"))
    assert world.dispatcher.dispatched == []
    assert await world.handler.handle_fast_path(world.actor.user_id, world.message("✅ Save")) is None


def test_a_sender_with_several_sites_sees_which_one_the_card_is_for():
    from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
    from runtime.agent.journey_gateway import JourneyGateway

    sites = [SimpleNamespace(id=S1, name="Green Villa", project_id=None), SimpleNamespace(id=S2, name="Tower", project_id=None)]
    gateway = JourneyGateway.__new__(JourneyGateway)
    gateway.actor = SimpleNamespace(sites=sites, projects=[], timezone=None)
    draft = DraftActionV2(
        draft_id="d", correlation_id="c", workflow_instance_id="w", action_type=DraftActionType.ADD_PROGRESS_UPDATE,
        organization_id=S2, user_id=S2, site_id=S1,
        fields={"work_type": "plastering", "quantities": [{"quantity": 50, "unit": "sq ft"}], "update_kind": "completed"},
    )
    card = gateway._work_card(SimpleNamespace(draft_action=draft))
    assert card.text == "📝 To save · Green Villa: Plastering: 50 sq ft (completed)"
