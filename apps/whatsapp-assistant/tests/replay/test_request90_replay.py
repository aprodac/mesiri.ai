"""Request 90: the 23 Oct re-test sequence ("[89] re-test") through the real
journey pieces -- the mixer issue gets a card, the masons are saved, and "undo that"
removes the masons, not the mixer issue; the old Undo of the latest record of any
type is never reached."""

from __future__ import annotations

from tests.replay.test_agent_replay import world  # noqa: F401,F811  (fixture)
from tests.replay.test_request88_replay import Day

from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import cards as c
from runtime.agent import save_button as sb
from runtime.agent.journey_gateway import NOTHING_TO_UNDO, undo_from_card

MIXER = "mixer machine kedayi, pani nirthi"
MASONS = "ഇന്ന് 3 മേസൺ വന്നു"


async def test_the_mixer_issue_has_a_card_and_undo_removes_the_masons(world):  # noqa: F811
    day = Day(world)
    issue = FakeToolCallingProvider(
        [
            [("report_issue", {"issue_type": "EQUIPMENT", "narrative": "mixer machine kedayi, pani nirthi"})],
            "Ayyo, mixer machine kedayi, pani nirthi. Nokki Save tap cheyyu.",
        ]
    )
    result, _, issue_facts = await day.say(issue, MIXER)
    assert issue_facts is not None and len(issue_facts) == 1, "a write always has a card"
    assert (await day.cards.get(world.actor)).state == c.OPEN

    masons = FakeToolCallingProvider(
        [[("save_labour", {"workers": [{"trade": "mason", "headcount": 3}]})], "Sheri, 3 mason. Nokki Save tap cheyyu."]
    )
    _, _, mason_facts = await day.say(masons, MASONS)
    assert mason_facts is not None
    reply = await day.tap(sb.SAVE, mason_facts)
    assert reply.text == sb.SAVED_DONE
    assert (await day.cards.get(world.actor)).state == c.SAVED

    # "undo that": the journey answers it from the latest card, before the agent.
    step = await undo_from_card(day.cards, world.actor, day.undo_facts, [])
    assert day.withdrawn == mason_facts, "the masons, and nothing else"
    assert issue_facts[0] not in day.withdrawn
    assert step.text == "Removed: 3 workers (3 mason) (today)"

    # and again: the card is gone, so there is nothing to undo -- the mixer issue is not touched
    again = await undo_from_card(day.cards, world.actor, day.undo_facts, [])
    assert (again.status, again.text) == ("info", NOTHING_TO_UNDO)
    assert day.withdrawn == mason_facts
