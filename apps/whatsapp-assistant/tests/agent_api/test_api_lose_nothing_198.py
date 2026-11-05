"""WA-198 (basic 2, "lose nothing"; Ilan, 5 Nov: "yes"): a message with several updates ("4 bag cement, 10 TMT bar")
came back with only some of them on the card, and nothing noticed the rest. Now the code compares the numbers in the
person's own words with everything the turn prepared, asked, answered or looked up; a number that is nowhere gets the
model one more try, told which. Times, dates, floors, refs, phone numbers and a photo's reading are not amounts. One
corrective try per turn at most (reply time). (Scripted: requests [232], [234], [237] could not be read here, no
control-plane token, so this is the general shape, not their replay.)
"""

from __future__ import annotations

from typing import Any

from tests.agent_api.standin import ACTOR
from tests.agent_api.test_api_stock_unit_165 import (
    ALLOWED,
    CEMENT,
    NOS,
    TMT,
    TOOLS,
    Store,
    _receipt,
)

from agent_api.agent import ApiAgent, left_over, own_words
from agent_api.client import ApiClient
from agent_api.tools import build_tools
from mesiri_ai.fakes import FakeToolCallingProvider


class Runs:
    """One scripted model run per call (the fake replays its whole script on every run); counts the runs."""

    def __init__(self, *scripts: list) -> None:
        self._runs = [FakeToolCallingProvider(s) for s in scripts]
        self.calls = 0
        self.prompts: list[str] = []

    async def run_tools(self, system: str, messages: list, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        self.prompts.append(messages[-1].text)
        return await self._runs[min(self.calls, len(self._runs)) - 1].run_tools(system, messages, *args, **kwargs)


async def _turn(store: Store, model: Runs, text: str) -> Any:
    app = store.api()
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(model, build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in TOOLS))).run(
            client, text)
    finally:
        await client.close()

CEMENT_4 = _receipt(CEMENT, "cement", "bags", 4, "4 bag cement")
TMT_10 = _receipt(TMT, "tmt", NOS, 10, "10 TMT bars")


async def test_a_part_left_off_the_card_gets_one_more_try_naming_it() -> None:
    store = Store()
    model = Runs([[CEMENT_4], "Cement ready."], [[TMT_10], "Cement and TMT ready."])
    turn = await _turn(store, model, "4 bag cement, 10 tmt bar vannu")
    assert model.calls == 2 and "said 10," in model.prompts[1]
    assert [e.summary.split(" (")[0] for e in turn.pending] == ["4 bag cement", "10 TMT bars"]
    assert turn.reply == "Cement and TMT ready."


async def test_sibling_a_part_asked_about_counts_as_kept() -> None:
    store = Store()
    model = Runs([[CEMENT_4, ("ask", {"question": "10 TMT: which size?"})], "Which size are the 10 TMT?"])
    turn = await _turn(store, model, "4 bag cement, 10 tmt vannu")
    assert model.calls == 1 and len(turn.pending) == 1 and turn.question  # the 10 is in the question


async def test_guard_everything_kept_means_no_second_try() -> None:
    store = Store()
    model = Runs([[CEMENT_4, TMT_10], "Both ready."])
    turn = await _turn(store, model, "4 bag cement, 10 tmt vannu")
    assert model.calls == 1 and turn.reply == "Both ready."


async def test_guard_one_more_try_only_never_a_loop() -> None:
    store = Store()
    model = Runs([[CEMENT_4], "Cement ready."], ["Cement ready (TMT later)."], [[TMT_10], "never reached"])
    turn = await _turn(store, model, "4 bag cement, 10 tmt vannu")
    assert model.calls == 2 and len(turn.pending) == 1 and turn.reply == "Cement ready (TMT later)."


async def test_guard_nothing_prepared_is_left_to_the_other_checks() -> None:
    store = Store()
    model = Runs(["How much cement is left?"], ["never reached"])
    turn = await _turn(store, model, "4 bag cement left? 10 tmt?")
    assert model.calls == 1 and turn.reply == "How much cement is left?"


def test_guard_times_dates_floors_refs_and_phone_numbers_are_not_amounts() -> None:
    said = "4 bag cement at 10:30 / 10am on 5/11, 2nd floor, #12 [243], driver 9876543210"
    assert left_over(said, "4 bag cement") == []


def test_guard_a_photos_reading_is_not_their_words() -> None:
    text = "(sent a photo: bill)\nWhat the photo shows: Invoice 2026, GST 18%, total 4500"
    assert own_words(text) == "(sent a photo: bill)" and left_over(own_words(text), "") == []


def test_the_numbers_left_over_are_named_once_each() -> None:
    assert left_over("20 bag cement, 6 mason, 6 helper", "20 bags cement") == ["6"]
    assert left_over("1.5 load sand", "1.5 Loads sand") == []


def test_guard_digits_inside_ids_do_not_count_as_kept() -> None:
    assert left_over("10 tmt", '{"site_id": "4b2e5df7-4c10-4a2b-9e10-10ab12cd34ef"}') == ["10"]


def test_guard_a_number_in_a_site_name_is_kept_by_the_name() -> None:
    assert left_over("50 bag cement Tower 2", "50 bags cement Tower 2 Green Villa") == []
