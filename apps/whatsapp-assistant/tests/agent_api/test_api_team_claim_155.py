"""WA-155 (3 Nov): "it said it informed the team" must always be true. Nothing checked that a reply saying the team
was told came with a tell_the_team call. Now: one more try, told plainly; still claimed without the call, the code
passes it on itself. Guard: a reply that doesn't speak of the team, or one that really called it, is left alone."""

from __future__ import annotations

from tests.agent_api.standin import ACTOR, stand_in_api, stand_in_tools
from tests.agent_api.test_api_change_ready_205 import _Turns

from agent_api.agent import ApiAgent, claims_team
from agent_api.client import ApiClient
from agent_api.feedback import TELL_THE_TEAM
from mesiri_ai.fakes import FakeToolCallingProvider

ASK = "Sahal-ine Rana Mart-il site engineer aayi add cheyyu"


async def _run(model):  # noqa: ANN001, ANN202
    app = stand_in_api([])
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(model, stand_in_tools(app)).run(client, ASK)
    finally:
        await client.close()


async def test_a_claim_without_the_call_gets_one_more_try_that_calls_it() -> None:
    model = _Turns(FakeToolCallingProvider(["I've informed the team, they will add this feature."]),
                   FakeToolCallingProvider([[(TELL_THE_TEAM, {"kind": "missing_feature", "about": "add a member"})],
                                            "Passed to the team."]))
    turn = await _run(model)
    assert model.calls == 2 and "you did not call tell_the_team" in model.last_messages[-1].text
    assert [c["tool"] for c in turn.calls] == [TELL_THE_TEAM]


async def test_still_claimed_without_the_call_the_code_passes_it_on() -> None:
    model = _Turns(FakeToolCallingProvider(["Team-ine ariyichittund."]), FakeToolCallingProvider(["Team-ine ariyichittund."]))
    turn = await _run(model)
    [call] = turn.calls
    assert call["tool"] == TELL_THE_TEAM and call["by"] == "code" and ASK in call["arguments"]["about"]


async def test_guard_a_real_call_or_no_claim_is_left_alone() -> None:
    real = FakeToolCallingProvider([[(TELL_THE_TEAM, {"kind": "missing_feature", "about": "x"})], "I've told the team."])
    assert [c["tool"] for c in (await _run(real)).calls] == [TELL_THE_TEAM] and real.calls == 1
    plain = FakeToolCallingProvider(["Hello Ilan, which site?"])
    assert (await _run(plain)).calls == [] and plain.calls == 1
    assert claims_team("ടീമിനെ അറിയിച്ചു")  # Malayalam script, inflected
    assert claims_team("ടീം അറിയിച്ചു") and claims_team("मैंने टीम को बता दिया") and not claims_team("Your site has 3 masons.")
