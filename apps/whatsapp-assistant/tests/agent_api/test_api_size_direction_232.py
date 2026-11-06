"""[232] (Ilan, ADMIN, Paraclette, 4 Nov 14:00-14:03 IST; again Adarsh, ADMIN, 6 Nov): "30 TMT steel bars received", TMT
counted in loads. Mesiri asked "how many loads are 30 bars?" (a fraction nobody can answer), took no answer ("oru load-il
ekadesham 200 bar undakum, save cheythoo" was longer than 4 words), had no way out for "I don't know", and told the
admin "asked your admin" when they were the admin.

Root cause: the size question's direction was the model's, the answer was recognised by length, and "don't know" had one
exit (hold for the admin) even when the admin is the one asking.
Fix (code): bigger unit first (``size_sides``), the question drawn by the code, a number in the reply while the question
is open answers it, "don't know" gives two taps (tell the size / save in the unit said, when the material has no stock
yet), and an admin is never told their admin was asked.

Each test walks the person's whole journey and asserts what is saved or set, not the reply's wording.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from tests.agent_api.test_api_size_requests_168 import ADMIN, ENGINEER
from tests.agent_api.test_api_stock_unit_165 import (
    BAG,
    KG,
    LOAD,
    NOS,
    TMT,
    UNITS,
    Harness,
    Store,
    _receipt,
    _tools,  # noqa: F401 -- the autouse fixture
)
from tests.agent_api.test_api_whatsapp_119 import _message

from agent_api.agent import size_answer, size_sides
from mesiri_ai.fakes import FakeToolCallingProvider

DRUM, LITRE, TRUCK = (str(uuid.uuid4()) for _ in range(3))
UNITS.update({DRUM: ("drum", "Drums"), LITRE: ("l", "Litres"), TRUCK: ("truck", "Trucks")})
TMT_LOAD, PRIMER, GRAVEL = (str(uuid.uuid4()) for _ in range(3))


class TmtStore(Store):
    """TMT counted in loads, no stock yet; primer counted in drums; gravel in bags."""

    def __init__(self) -> None:
        super().__init__()
        self.catalog += [{"id": TMT_LOAD, "name": "TMT Steel Bars", "aliases": ["tmt steel bar"], "default_unit_id": LOAD},
                         {"id": PRIMER, "name": "Primer", "aliases": [], "default_unit_id": DRUM},
                         {"id": GRAVEL, "name": "Gravel", "aliases": [], "default_unit_id": BAG}]
        self.unmoved = {TMT_LOAD, PRIMER}


BARS = _receipt(TMT_LOAD, "TMT steel bar", NOS, 30, "30 TMT steel bar Tower A")
SAY = "30 TMT steel bar vannu"


def _unit(store: TmtStore, material: str) -> str:
    return next(r["default_unit_id"] for r in store.catalog if r["id"] == material)


async def _say(h: Harness, text: str, script: list, ctx=ADMIN, tap: str | None = None) -> object:
    h.service._agent._provider = FakeToolCallingProvider(script)
    await h.service.handle(_message(text, tap=tap), ctx)
    return h.sent[-1]


async def _save(h: Harness, ctx=ADMIN) -> object:
    batch = (await h.state())["batch"]
    h.service._agent._provider = FakeToolCallingProvider(["Ok."])
    await h.service.handle(_message("Save", tap=f"apiag:save:{batch}"), ctx)
    return h.sent[-1]


async def _started(store: TmtStore, ctx=ADMIN, language: str = "manglish") -> Harness:
    h = Harness(store, FakeToolCallingProvider(["-"]))
    await h.hold(language=language)
    await _say(h, SAY, [[BARS], "Ok."], ctx)
    return h


# -- the direction ---------------------------------------------------------------------------------------------------


async def test_the_question_asks_the_bigger_unit_first_and_the_line_waits_on_the_card() -> None:
    h = await _started(TmtStore())
    reply, state = h.sent[-1], await h.state()
    need = state["size_needed"][0]
    assert (need["big"], need["small"], need["stock_bigger"]) == ("Loads", "Numbers", True)
    assert "1 Loads TMT Steel Bars-il ethra Numbers undu?" in reply.text  # never "30 bars = how many loads?"
    assert [p["body"]["quantity"] for p in state["pending"]] == [30]  # the 30 bars are on the card


def test_which_unit_is_bigger_is_decided_by_the_code() -> None:
    def sides(said: str, stock: str) -> tuple[str, str]:
        found = size_sides({"unit": said, "unit_name": said.title(), "stock_unit": stock, "stock_unit_name": stock.title()})
        return found["big"], found["small"]

    assert sides("nos", "load") == ("Load", "Nos") and sides("l", "drum") == ("Drum", "L")
    assert sides("load", "bags") == ("Load", "Bags") and sides("truck", "bags") == ("Truck", "Bags")
    assert sides("kg", "bags") == ("Bags", "Kg")  # [271]: a bag is bigger than a kilo ("1 bag = 50 kg", never 0.02)
    assert sides("nos", "kg") == ("Nos", "Kg")  # same size rank: the unit said is asked about, as before


@pytest.mark.parametrize("reply", ["200", "1 load 200 bar", "200 bars oru load", "oru load-il ekadesham 200 bar undakum"])
async def test_the_answer_is_taken_in_either_direction_and_from_a_long_voice_reply(reply: str) -> None:
    store = TmtStore()
    h = await _started(store)
    await _say(h, reply, ["Ready."])  # the model calls nothing: the code took the size
    state = await h.state()
    assert [p["tool"] for p in state["pending"]] == ["record_receipt", "set_unit_conversion"] or [
        p["tool"] for p in state["pending"]] == ["set_unit_conversion", "record_receipt"]
    await _save(h)
    assert store.one_unit[(TMT_LOAD, NOS)] == pytest.approx(1 / 200)  # 1 load = 200 nos, stored as loads per no
    assert store.received == [("TMT Steel Bars", pytest.approx(0.15))]  # 30 bars received = 0.15 load
    assert "size_needed" not in await h.state()


async def test_a_range_is_its_middle_and_a_voice_save_in_the_same_message_saves() -> None:
    store = TmtStore()
    h = await _started(store)
    # "oru load-il 180-200 undakum, save cheythoo": the code takes 190, then the model saves the waiting card
    await _say(h, "oru load-il 180-200 bar undakum, save cheythoo", [[("save_ready_entries", {})], "Saved."])
    assert store.one_unit[(TMT_LOAD, NOS)] == pytest.approx(1 / 190, rel=1e-3)
    assert store.received == [("TMT Steel Bars", pytest.approx(30 / 190, rel=1e-3))]


async def test_a_site_engineer_answer_converts_their_own_line() -> None:
    store = TmtStore()
    h = await _started(store, ENGINEER)
    await _say(h, "200", ["Ready."], ENGINEER)
    state = await h.state()
    line = next(p for p in state["pending"] if p["tool"] == "record_receipt")
    assert line["body"]["unit_id"] == LOAD and line["body"]["quantity"] == pytest.approx(0.15)
    await _save(h, ENGINEER)
    assert store.received == [("TMT Steel Bars", pytest.approx(0.15))]


# -- "I don't know": never a dead end --------------------------------------------------------------------------------


async def test_dont_know_offers_the_size_or_saving_the_30_bars_in_nos_and_after_save_30_nos_are_received() -> None:
    store = TmtStore()
    h = await _started(store)
    reply = await _say(h, "🤷 Ariyilla", [], tap="apiag:opt:0")  # no model turn
    titles = [b.title for b in reply.buttons]
    assert titles[:2] == ["Size parayam", "30 nos aayi save"]
    assert "size_needed" in await h.state() and store.size_requests == []  # nothing held for anyone
    await _say(h, titles[1], [], tap="apiag:opt:1")
    await _save(h)
    assert _unit(store, TMT_LOAD) == NOS  # the stock unit of TMT is nos now
    assert store.received == [("TMT Steel Bars", 30.0)]


async def test_usually_how_much_gets_the_question_and_buttons_again_never_nothing_ready() -> None:
    store = TmtStore()
    h = await _started(store)
    reply = await _say(h, "usually how much?", ["It depends on the bar's diameter."])
    assert "Numbers" in reply.text and "30 TMT steel bar" in reply.text  # the question and the line on show
    assert "anything ready" not in reply.text and "Ref #" not in reply.text
    assert reply.buttons[0].title == "🤷 Don't know"  # their language this turn: English
    assert [p["body"]["quantity"] for p in (await h.state())["pending"]] == [30]
    await _say(h, "🤷 Ariyilla", [], tap="apiag:opt:0")
    assert [b.title for b in h.sent[-1].buttons][:2] == ["Tell the size", "Save as 30 nos"]


async def test_tell_the_size_asks_the_one_question_again() -> None:
    h = await _started(TmtStore())
    await _say(h, "🤷 Ariyilla", [], tap="apiag:opt:0")
    reply = await _say(h, "Size parayam", [], tap="apiag:opt:0")
    assert "Loads" in reply.text and "Numbers" in reply.text and "size_needed" in await h.state()


async def test_an_admin_who_does_not_know_is_never_told_their_admin_was_asked() -> None:
    # [232] (6 Nov, Adarsh, ADMIN: "10 load M sand", stock in cum, tapped Ariyilla, "Size admin-nodu chodichittundu").
    store = TmtStore()
    store.unmoved.discard(TMT_LOAD)  # TMT has stock: no unit change possible, the line waits until the size is set
    h = await _started(store, ADMIN)
    reply = await _say(h, "🤷 Ariyilla", [], tap="apiag:opt:0")
    assert "admin-nodu" not in reply.text and "Nee size set cheyyunnathu vare" in reply.text
    assert store.size_requests[0]["held_lines"][0]["body"]["quantity"] == 30  # waits for their size; nothing lost


async def test_sibling_the_admin_with_no_stock_gets_the_way_out_not_a_hold() -> None:
    store = TmtStore()
    h = await _started(store, ADMIN)
    reply = await _say(h, "🤷 Ariyilla", [], tap="apiag:opt:0")
    assert "30 nos aayi save" in [b.title for b in reply.buttons] and store.size_requests == []


async def test_sibling_a_material_with_stock_held_by_an_engineer_is_asked_of_the_admin_as_before() -> None:
    store = TmtStore()
    store.unmoved.discard(TMT_LOAD)
    h = await _started(store, ENGINEER)
    reply = await _say(h, "🤷 Ariyilla", [], ENGINEER, tap="apiag:opt:0")
    assert "admin-nodu chodichittundu" in reply.text and len(store.size_requests) == 1


# -- the same class: other units, languages --------------------------------------------------------------------------


async def test_sibling_litres_of_primer_counted_in_drums() -> None:
    store = TmtStore()
    h = Harness(store, FakeToolCallingProvider(["-"]))
    await h.hold(language="english")
    await _say(h, "5 litre primer received", [[_receipt(PRIMER, "primer", LITRE, 5, "5 L primer")], "Ok."])
    assert "1 Drums Primer = how many Litres?" in h.sent[-1].text
    await _say(h, "20", ["Ready."])
    await _save(h)
    assert store.received == [("Primer", pytest.approx(0.25))] and store.one_unit[(PRIMER, LITRE)] == pytest.approx(0.05)


async def test_sibling_a_truck_of_gravel_counted_in_bags_is_asked_truck_first_and_stored_as_said() -> None:
    store = TmtStore()
    h = Harness(store, FakeToolCallingProvider(["-"]))
    await h.hold(language="english")
    await _say(h, "1 truck gravel received", [[_receipt(GRAVEL, "gravel", TRUCK, 1, "1 truck gravel")], "Ok."])
    assert "1 Trucks Gravel = how many Bags?" in h.sent[-1].text
    await _say(h, "100 bag", ["Ready."])
    await _save(h)
    assert store.one_unit[(GRAVEL, TRUCK)] == 100 and store.received == [("Gravel", 100.0)]


async def test_sibling_in_malayalam_the_question_and_the_taps_are_in_malayalam() -> None:
    h = Harness(TmtStore(), FakeToolCallingProvider(["-"]))
    await h.hold(language="malayalam")
    await _say(h, "30 ടിഎംടി സ്റ്റീൽ ബാർ വന്നു", [[BARS], "ശരി."])
    assert "ൽ എത്ര Numbers ഉണ്ട്?" in h.sent[-1].text
    reply = await _say(h, "🤷 അറിയില്ല", [], tap="apiag:opt:0")
    assert [b.title for b in reply.buttons][:2] == ["സൈസ് പറയാം", "30 nos ആയി സേവ്"]


# -- guards ----------------------------------------------------------------------------------------------------------


async def test_guard_a_built_in_conversion_asks_nothing() -> None:
    store = TmtStore()
    h = Harness(store, FakeToolCallingProvider(["-"]))
    await h.hold(language="english")
    await _say(h, "10 bar tmt 12mm", [[_receipt(TMT, "tmt", NOS, 10, "10 TMT 12mm")], "Ready."])  # nos -> kg is set
    assert "size_needed" not in await h.state() and "how many" not in h.sent[-1].text
    await _say(h, "50 kg tmt", [[_receipt(TMT, "tmt", KG, 50, "50 kg TMT 12mm")], "Ready."])
    assert "size_needed" not in await h.state()


async def test_guard_an_unrelated_request_still_drops_the_question() -> None:
    store = TmtStore()
    h = await _started(store)
    await _say(h, "add 5 masons to Tower A for today", ["Ok, noted."])
    state = await h.state()
    assert "size_needed" not in state and state.get("size_choices") is None
    assert [p["body"]["quantity"] for p in state["pending"]] == [30]  # the line itself is never dropped


def test_the_number_of_an_answer() -> None:
    need: dict = {}
    assert size_answer("200", need) == 200 and size_answer("1 load 200 bar", need) == 200
    assert size_answer("180 to 200", need) == 190 and size_answer("ariyilla", need) is None
    assert size_answer("100 or 200", need) is None  # two different numbers: asked again, never guessed
    assert SimpleNamespace  # keep the import used



