"""WA-270 / WA-281 (the state layer, part 3: memory is state, not replay). Whole conversations through the real
WhatsApp service (its chat state and its day memory), with the model scripted: what these tests hold is what the
model is GIVEN on each turn, which is the code's job.

Today (13 Nov 2026) the model gets the day's chat replayed (up to 120 messages). Live on Mesiri Test Builders that
gave: "athu 25 aakku" dropping the line and answering an old question (WA-293), a new message bringing back the lines
of cancelled messages (WA-294), a repeated message getting an earlier reply copied (WA-286).

The tests marked ``xfail`` are the target of step 4 (the state block and the short window): they fail on today's code
and must pass, with the mark removed, when the company's setting is on. The others hold what must not change.
"""

from __future__ import annotations

import pytest
from tests.agent_api.standin import two_receipts_model
from tests.agent_api.test_api_whatsapp_119 import CTX, Harness, _message, _stand_in_tools  # noqa: F401

from mesiri_ai.fakes import FakeToolCallingProvider

#: How many earlier messages the model keeps once memory is state (plan decision 2: three exchanges).
WINDOW = 6
STEP_4 = "WA-270 step 4: the state block and the short window are not built yet"


async def _chat(h: Harness, said: str, reply: str = "Sheri.") -> FakeToolCallingProvider:
    """One message answered in words; returns the model stand-in, which kept what it was given."""
    model = FakeToolCallingProvider([reply])
    h.service._agent._provider = model
    await h.service.handle(_message(said), CTX)
    return model


async def _long_day(h: Harness, exchanges: int = 15) -> None:
    for i in range(exchanges):
        await _chat(h, f"chodyam {i}: innu enthokke nadannu?", f"marupadi {i}: onnum record cheythittilla.")


def _given(model: FakeToolCallingProvider) -> tuple[list, str]:
    return list(model.last_messages), str(model.last_system_prompt or "")


async def test_baseline_today_the_whole_day_is_replayed() -> None:
    """The measure before the change (step 2): after 15 exchanges the model is handed all 30 messages again."""
    h = Harness(FakeToolCallingProvider(["-"]))
    await _long_day(h)
    messages, _ = _given(await _chat(h, "20 bag cement vannu"))
    assert len(messages) == 31  # 15 exchanges replayed + this message


@pytest.mark.xfail(strict=True, reason=STEP_4)
async def test_the_model_gets_a_short_window_not_the_day() -> None:
    h = Harness(FakeToolCallingProvider(["-"]))
    await _long_day(h)
    messages, _ = _given(await _chat(h, "20 bag cement vannu"))
    assert len(messages) <= WINDOW + 1
    assert messages[-1].text.endswith("20 bag cement vannu")  # the message to act on is last
    assert not any("marupadi 3:" in (m.text or "") for m in messages)  # an old reply is not there to copy


@pytest.mark.xfail(strict=True, reason=STEP_4)
async def test_what_was_cancelled_is_named_so_it_never_comes_back() -> None:
    """WA-294: the lines of a cancelled card came back on the next message. The model must be told, as state."""
    h = Harness(two_receipts_model())
    await h.service.handle(_message(), CTX)  # "50 bag cement, 50 TMT vannu": a card with two lines
    await h.service.handle(_message("cancel"), CTX)
    _, system = _given(await _chat(h, "3 carpenter vannu"))
    assert "Cancelled in this chat" in system
    assert "50 bags cement" in system.split("Cancelled in this chat")[1][:400]


@pytest.mark.xfail(strict=True, reason=STEP_4)
async def test_the_card_and_the_message_to_act_on_are_state_not_history() -> None:
    """WA-293: "athu 25 aakku" must be read against the card, given as numbered state, with the message marked."""
    h = Harness(two_receipts_model())
    await h.service.handle(_message(), CTX)
    messages, system = _given(await _chat(h, "athu 25 aakku"))
    assert "On the card now" in system and "1. 50 bags cement" in system
    assert len(messages) <= WINDOW + 1


async def test_guard_a_first_message_of_the_day_is_given_alone() -> None:
    h = Harness(FakeToolCallingProvider(["-"]))
    messages, _ = _given(await _chat(h, "20 bag cement vannu"))
    assert [m.role for m in messages] == ["user"] and messages[0].text.endswith("20 bag cement vannu")


def test_wa281_a_replay_reads_the_persons_sites_from_its_facts() -> None:
    from tests.agent_api.replaykit import facts_places

    facts = ("The person's projects and sites (use these ids):\n"
             "- project Green Villa, Kakkanad (project_id fee7ee7c-e5d6-436c-88be-7a5ea29cc1ee)\n"
             "  - site Green Villa, Kakkanad (site_id 727d30ee-c40d-4587-90ed-cdf519121dfb)\n"
             "  - site Site B (site_id 11116a12-47aa-436c-89ba-207cfcd1b926)\n"
             "- project Omega Towers (project_id d9884ea2-36bc-4636-b488-cef3008cec03)\n"
             "  (Omega Towers has no site yet: a report for it goes on Omega Towers; Save adds its site.)\n\n"
             "Units (unit_id): bags (03e5cbfa-43d6-4af5-b18a-61aa7f884af7)")
    places = facts_places(facts)
    assert [name for _id, name in places.projects] == ["Green Villa, Kakkanad", "Omega Towers"]
    assert [(name, project) for _id, name, project in places.sites] == [
        ("Green Villa, Kakkanad", "fee7ee7c-e5d6-436c-88be-7a5ea29cc1ee"), ("Site B", "fee7ee7c-e5d6-436c-88be-7a5ea29cc1ee")]
    assert facts_places("Units (unit_id): bags (x)") is None
