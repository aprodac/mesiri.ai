"""WA-198, numbers said as words (live, Aprodac, 14 Nov 06:06 IST, a voice note): "Main blockile randu mesonum pathu
bag sandum vannittund tto" got a card with the 10 bags of sand only. The masons' "randu" (2) was never read as a
number, so the "lose nothing" check saw nothing missing, and after its one more try a part still missing was said to
nobody. Now number words in Mesiri's languages count (Manglish, Malayalam script, Hinglish, Devanagari, English), and
a number still on nothing after the one more try is said under the card ("⚠️ Not on the list…"), never left to look
complete. The card check (WA-264) had seen it too, in shadow: it stays shadow (about half its "wrong" were wrong).
"""

from __future__ import annotations

from tests.agent_api.standin import ACTOR
from tests.agent_api.test_api_lose_nothing_198 import CEMENT_4, Runs, _turn
from tests.agent_api.test_api_stock_unit_165 import NOS, TMT, Store, _receipt

from agent_api.agent import left_over, said_phrase

TMT_10 = _receipt(TMT, "tmt", NOS, 10, "10 TMT bars")
assert ACTOR  # the stand-in actor of the shared harness


def test_live_the_masons_randu_is_a_number_left_over() -> None:
    said = "Main blockile randu mesonum pathu bag sandum vannittund tto"
    assert left_over(said, '{"quantity": 10} 10 bags sand, Main block') == ["randu (2)"]
    assert said_phrase(said, "randu (2)") == "randu mesonum"


def test_sibling_every_language_mesiri_replies_in() -> None:
    assert left_over("മെയിൻ ബ്ലോക്കിൽ രണ്ടു മേസണും പത്തു ബാഗ് സാൻഡും വന്നു", "10 bags sand") == ["രണ്ടു (2)"]
    assert left_over("Main block mein teen mistri aur paanch bag cement aaye", "5 bags cement") == ["teen (3)"]
    assert left_over("मेन ब्लॉक में तीन मिस्त्री और पाँच बैग सीमेंट आए", "5 bags cement") == ["तीन (3)"]
    assert left_over("two masons and ten bags of sand came", "10 bags sand") == ["two (2)"]
    assert left_over("moonum randum vannu", "") == ["moonum (3)", "randum (2)"]  # "-m" / "-um" joined on


def test_guard_everyday_words_and_times_are_not_amounts() -> None:
    assert left_over("oru doubt, randu naal munpu 20 bag cement vannu", "20 bags cement") == []  # 1 and a time
    assert left_over("2 days ago 20 bag cement came", "20 bags cement") == []
    assert left_over("do bag cement de do", "") == []  # Hindi "do" is also "give": left out on purpose
    assert left_over("randu mesonum vannu", '{"lines": [{"trade": "Mason", "headcount": 2}]}') == []  # kept in digits
    assert left_over("2 mason", "randu masons") == []  # kept in words


async def test_live_shape_a_part_said_in_words_gets_one_more_try_naming_it() -> None:
    model = Runs([[CEMENT_4], "Cement ready."], [[TMT_10], "Cement and TMT ready."])
    turn = await _turn(Store(), model, "4 bag cement, pathu tmt bar vannu")
    assert model.calls == 2 and "pathu (10)" in model.prompts[1]
    assert [e.summary.split(" (")[0] for e in turn.pending] == ["4 bag cement", "10 TMT bars"]
    assert turn.not_held == []


async def test_live_shape_still_missing_after_the_try_is_said_under_the_card() -> None:
    model = Runs([[CEMENT_4], "Cement ready."], ["Cement ready."])
    turn = await _turn(Store(), model, "4 bag cement, pathu tmt bar vannu")
    assert model.calls == 2 and len(turn.pending) == 1
    assert turn.not_held == ["pathu tmt"]  # the code's "⚠️ Not on the list, nothing saved for: pathu tmt"


async def test_sibling_a_digit_still_missing_is_said_too() -> None:
    model = Runs([[CEMENT_4], "Cement ready."], ["Cement ready."])
    turn = await _turn(Store(), model, "4 bag cement, 10 tmt bar vannu")
    assert turn.not_held == ["10 tmt"]
