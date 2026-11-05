"""WA-199 (basic 10, "never a dead end"; Ilan, 5 Nov: "continue with dead ends"). On 3 Nov (users' feedback, WA-196)
Mesiri answered four different messages with the same "cannot track details of multiple contractors" line, without
looking at a tool and without passing anything on; SOP rule 10 ("check the tools before I can't") was only written.
Now a "can't" said with no tool looked at gets one more try (the tools first, else tell_the_team and the way for now);
if it still says "can't" without passing it on, the code passes it to the team itself, so what they asked gets built.
"""

from __future__ import annotations

from tests.agent_api.test_api_lose_nothing_198 import CEMENT_4, Runs, _turn
from tests.agent_api.test_api_stock_unit_165 import Store

from agent_api.reply_guard import claims_cannot

TEAM = ("tell_the_team", {"kind": "missing_feature", "about": "track contractor rates"})


def _by_code(turn) -> list[dict]:  # noqa: ANN001
    return [c for c in turn.calls if c.get("by") == "code"]


async def test_a_cant_from_memory_gets_the_tools_first_and_does_it() -> None:
    model = Runs(["I can't record deliveries here."], [[CEMENT_4], "4 bag cement ready."])
    turn = await _turn(Store(), model, "4 bag cement vannu")
    assert model.calls == 2 and "Check your tools first" in model.prompts[1]
    assert len(turn.pending) == 1 and turn.reply == "4 bag cement ready." and not _by_code(turn)


async def test_sibling_nothing_does_it_so_the_model_passes_it_to_the_team() -> None:
    model = Runs(["I cannot track contractor rates."], [[TEAM], "Not here yet; passed to the team to build."])
    turn = await _turn(Store(), model, "electrician 1200 per day, now wants 1300")
    assert model.calls == 2 and [c["tool"] for c in turn.calls] == ["tell_the_team"] and not _by_code(turn)


async def test_still_cant_and_not_passed_on_the_code_passes_it_on() -> None:
    model = Runs(["Contractor rates ivide record cheyyan pattilla."], ["Athu pattilla."])
    turn = await _turn(Store(), model, "electrician rate 1300 aakki")
    assert model.calls == 2
    assert [c["result"]["status"] for c in _by_code(turn)] == ["passed on by the code (WA-199)"]
    assert "electrician rate 1300" in _by_code(turn)[0]["arguments"]["about"]


async def test_guard_a_cant_after_looking_at_the_tools_is_left_alone() -> None:
    # The tools were tried (the API refused, or the model read and found nothing): the reply stands, no extra call.
    model = Runs([[CEMENT_4], "Cement ready; I can't change yesterday's report here."], ["never reached"])
    turn = await _turn(Store(), model, "4 bag cement vannu, yesterday's report maattanam")
    assert model.calls == 1 and not _by_code(turn)


async def test_guard_an_answer_with_no_cant_is_left_alone() -> None:
    model = Runs(["Good morning! What came to the site today?"], ["never reached"])
    await _turn(Store(), model, "good morning")
    assert model.calls == 1


def test_the_cant_words_in_each_language() -> None:
    for said in ("I can't record that here.", "I'm unable to change it.", "Mesiri cannot track rates yet.",
                 "That is not possible here.", "Ithu ivide cheyyan pattilla.", "Athu kazhiyilla.",
                 "ഇത് ഇവിടെ പറ്റില്ല.", "Main yeh nahi kar sakta.", "मैं यह नहीं कर सकता।"):
        assert claims_cannot(said), said


def test_guard_not_a_cant() -> None:
    for said in ("If you can't find the size, just tap Save.", "Can't find the bill?", "The size is not known yet.",
                 "You cannot add a site without a project name?", "Nothing is recorded for today.",
                 "Cement ready aanu."):
        assert not claims_cannot(said), said
