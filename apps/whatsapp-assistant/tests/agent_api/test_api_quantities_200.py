"""WA-200 (basic 4, "never change their data"; Ilan, 5 Nov: "do it"). [210] (3 Nov): "2 drum primer, 20 litre drum"
was held as "40 litres", the model's own arithmetic, and the stock went wrong with it. SOP rule 6 says never to do
arithmetic they did not ask for; only the model was told. Now a held quantity that is not a number they said but two
of their numbers multiplied or added is sent back once: their number, in their unit (the code converts).
"""

from __future__ import annotations

from tests.agent_api.test_api_lose_nothing_198 import Runs, _turn
from tests.agent_api.test_api_stock_unit_165 import BAG, LOAD, MSAND, Store, _conversion, _receipt

from agent_api.agent import worked_out

SAID = "2 load msand vannu, 60 bag oru load"


async def test_a_worked_out_total_is_sent_back_and_their_number_is_held() -> None:
    model = Runs([[_receipt(MSAND, "msand", BAG, 120, "120 bags msand")],
                  [_conversion(MSAND, LOAD, 60), _receipt(MSAND, "msand", LOAD, 2, "2 load msand")], "2 load msand ready."])
    turn = await _turn(Store(), model, SAID)
    error = turn.calls[0]["result"]["error"]
    assert "120 is not a number they said: it is 2 x 60" in error and model.calls == 1
    line = next(e for e in turn.pending if e.tool == "record_receipt")
    assert line.body["unit_id"] == LOAD and line.body["quantity"] == 2 and line.summary.endswith("(= 120 Bags)")


def test_sibling_two_amounts_added_into_one_line() -> None:
    assert "5 is not a number they said: it is 2 + 3" in worked_out("2 load sand and 3 load sand", {"quantity": 5})


async def test_guard_sent_back_once_then_a_total_they_mean_goes_through() -> None:
    line = _receipt(MSAND, "msand", BAG, 120, "120 bags msand")
    model = Runs([[line], [line, _conversion(MSAND, LOAD, 60)], "Ready."], ["Ready."])
    turn = await _turn(Store(), model, SAID)
    assert "error" in turn.calls[0]["result"]
    assert [e.body.get("quantity") for e in turn.pending if e.tool == "record_receipt"] == [120]  # held the 2nd time


def test_guard_a_number_they_said_is_never_questioned() -> None:
    assert worked_out("4 bag cement, total 8 bag with yesterday's 4", {"quantity": 8}) == ""
    assert worked_out("50 bag cement", {"quantity": 50}) == ""
    assert worked_out("6 mason 2 helper", {"lines": [{"headcount": 6}, {"headcount": 2}]}) == ""


def test_guard_dates_times_and_word_numbers_are_not_their_amounts() -> None:
    assert worked_out("cement at 10:30 on 5/11", {"quantity": 15}) == ""  # no two amounts said
    assert worked_out("aaru mason, 2 helper", {"lines": [{"headcount": 6}]}) == ""
