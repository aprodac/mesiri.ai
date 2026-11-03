"""WA-166: units that just work (Paraclette, 31 Oct - 3 Nov: 21 unit dead ends in four days; TMT counted in loads
because the first message said "1 load TMT"; sand, M-sand and P-sand counted in bags; "1 load holobricks = 0.33 nos"
saved the wrong way round; a site engineer's size answer refused at Save, because only an admin or a project manager
may set one for the company).

Now: a new material is counted in its kind's unit; a size is asked once, in the person's direction, and shown on the
card ("(= 60 Bags)", "📏 1 Loads M-sand = 60 Bags") before Save; a size the wrong way round is refused; someone who
may not set the company's size has their own lines converted with their size, and is never asked again.
"""

from __future__ import annotations

import uuid

from tests.agent_api.standin import ACTOR
from tests.agent_api.test_api_stock_unit_165 import (
    BAG,
    CFT,
    KG,
    LOAD,
    MSAND,
    NOS,
    TMT,
    Store,
    _receipt,
)

from agent_api.agent import ApiAgent, confirm, size_key
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG
from mesiri_ai.fakes import FakeToolCallingProvider

TOOLS = ("record_receipt", "set_unit_conversion", "add_material")
LINE = _receipt(MSAND, "എംസാൻഡ്", LOAD, 1, "1 ലോഡ് എംസാൻഡ് Tower A")


def _size(material: str, unit: str, size: float) -> tuple[str, dict]:
    return ("set_unit_conversion", {"material_id": material, "from_unit_id": unit, "one_unit_equals": size,
                                    CONFIRM_ARG: "size"})


async def _turn(store: Store, script: list, text: str, *, ready: list | None = None, sizes: dict | None = None,
                may_set_sizes: bool = True, name: str = "Midlaj"):  # noqa: ANN202
    from agent_api.tools import build_tools

    app = store.api()
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in TOOLS))
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(
            client, text, ready=ready, sizes=sizes, may_set_sizes=may_set_sizes, sender_name=name)
    finally:
        await client.close()


async def _save(store: Store, pending: list):  # noqa: ANN202
    client = ApiClient(ACTOR, app=store.api())
    try:
        return await confirm(client, pending)
    finally:
        await client.close()


# -- someone who may not set the company's size (a site engineer) --------------------------------------------------


async def test_a_site_engineers_size_converts_their_line_and_saves_without_a_refused_company_setting() -> None:
    store = Store()
    first = await _turn(store, [[LINE], "1 load = ethra bags?"], "1 load msand vannu", may_set_sizes=False)
    assert first.pending == [] and "1 Loads എംസാന്റ് = how many Bags" in first.calls[0]["result"]["error"]
    second = await _turn(store, [[_size(MSAND, LOAD, 60), LINE], "Ready."], "60 bags", may_set_sizes=False)
    assert second.sizes_said == {size_key(MSAND, LOAD): 60.0}
    assert [e.tool for e in second.pending] == ["record_receipt"]  # no company setting that Save would refuse
    line = second.pending[0]
    assert line.body["unit_id"] == BAG and line.body["quantity"] == 60
    assert line.summary.endswith("(= 60 Bags)")
    assert all(r.ok for r in await _save(store, second.pending))
    assert store.received == [("എംസാന്റ്", 60.0)] and (MSAND, LOAD) not in store.one_unit
    assert "reported as 1 Loads (1 Loads = 60 Bags, as Midlaj said)" in store.notes[0]


async def test_the_next_load_from_the_same_engineer_is_never_asked_again() -> None:
    store = Store()
    turn = await _turn(store, [[_receipt(MSAND, "msand", LOAD, 2, "2 load msand")], "Ready."], "2 load msand vannu",
                       sizes={size_key(MSAND, LOAD): 60}, may_set_sizes=False)
    assert turn.pending[0].body["quantity"] == 120 and turn.pending[0].summary.endswith("(= 120 Bags)")
    assert not turn.question


# -- an admin: the company's size, shown before Save ---------------------------------------------------------------


async def test_an_admins_size_is_drawn_by_the_code_and_the_line_shows_what_it_is_in_stock() -> None:
    store = Store()
    turn = await _turn(store, [[_size(MSAND, LOAD, 60), LINE], "Ready."], "60 bags")
    size, line = turn.pending
    assert size.summary == "📏 1 Loads എംസാന്റ് = 60 Bags"
    assert line.summary.endswith("(= 60 Bags)") and line.body["unit_id"] == LOAD  # the API converts it at Save
    assert all(r.ok for r in await _save(store, turn.pending))
    assert store.one_unit[(MSAND, LOAD)] == 60 and store.received == [("എംസാന്റ്", 60.0)]


async def test_a_size_the_wrong_way_round_is_refused_before_it_is_held() -> None:
    store = Store()
    holo = str(uuid.uuid4())
    store.catalog.append({"id": holo, "name": "holobricks", "aliases": [], "default_unit_id": NOS})
    turn = await _turn(store, [[_size(holo, LOAD, 0.33)], "?"], "0.33")
    assert turn.pending == [] and "wrong way round" in turn.calls[0]["result"]["error"]


# -- a new material is counted in its kind's unit -------------------------------------------------------------------


async def test_new_tmt_said_in_loads_is_counted_in_kg_and_the_load_size_is_asked() -> None:
    store = Store()
    turn = await _turn(store, [[("add_material", {"name": "TMT 10mm", "default_unit_id": "load", CONFIRM_ARG: "➕ TMT 10mm"}),
                                _receipt("new:TMT 10mm", "tmt", LOAD, 1, "1 load TMT")], "?"], "➕ Add TMT")
    assert [e.tool for e in turn.pending] == ["add_material", "record_receipt"]  # held together ([217])
    assert turn.pending[0].body["default_unit_id"] == KG and turn.pending[0].summary.endswith("· counted in Kilograms")
    assert "1 Loads TMT 10mm = how many Kilograms" in turn.calls[1]["result"]["note"]


async def test_new_msand_with_no_unit_given_is_counted_in_cubic_feet() -> None:
    turn = await _turn(Store(), [[("add_material", {"name": "M-sand", CONFIRM_ARG: "➕ M-sand"})], "Ready."], "Add M-sand")
    assert turn.pending[0].body["default_unit_id"] == CFT


async def test_guard_a_material_of_unknown_kind_keeps_the_unit_given() -> None:
    turn = await _turn(Store(), [[("add_material", {"name": "Fevicol", "default_unit_id": "nos", CONFIRM_ARG: "➕ Fevicol"})],
                                 "Ready."], "Add fevicol")
    assert turn.pending[0].body["default_unit_id"] == NOS and "counted in" not in turn.pending[0].summary


# -- guards ---------------------------------------------------------------------------------------------------------


async def test_guard_a_known_size_shows_what_it_is_in_stock_and_the_stock_unit_shows_nothing() -> None:
    store = Store()
    turn = await _turn(store, [[_receipt(TMT, "tmt", NOS, 10, "10 TMT bars"), _receipt(MSAND, "msand", BAG, 40, "40 bags msand")],
                               "Ready."], "10 tmt 40 bag msand")
    assert turn.pending[0].summary == "10 TMT bars (= 106.7 Kilograms)"
    assert turn.pending[1].summary == "40 bags msand"


async def test_guard_an_admins_size_is_never_kept_as_their_own() -> None:
    turn = await _turn(Store(), [[_size(MSAND, LOAD, 60)], "Ready."], "60")
    assert turn.sizes_said == {} and turn.pending[0].tool == "set_unit_conversion"


# -- end to end through WhatsApp: the engineer's size is kept for their next message -----------------------------------


async def test_through_whatsapp_an_engineers_size_is_kept_and_their_next_load_is_converted(monkeypatch) -> None:  # noqa: ANN001
    from types import SimpleNamespace

    from tests.agent_api.test_api_stock_unit_165 import Harness
    from tests.agent_api.test_api_whatsapp_119 import CTX, _message

    from agent_api import tools as tools_mod
    from agent_api import whatsapp as wa

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(openapi, tuple(a for a in ALLOWED if a.name in TOOLS)))
    store = Store()
    engineer = SimpleNamespace(**{**vars(CTX), "role": "SITE_ENGINEER"})
    h = Harness(store, FakeToolCallingProvider([[_size(MSAND, LOAD, 60), LINE], "Ready."]))
    await h.service.handle(_message("oru load 60 chaakku"), engineer)
    h.service._agent._provider = FakeToolCallingProvider([[_receipt(MSAND, "msand", LOAD, 3, "3 load msand")], "Ready."])
    await h.service.handle(_message("3 load msand vannu"), engineer)
    state = await h.state()
    assert [p["summary"] for p in state["pending"]] == ["1 ലോഡ് എംസാൻഡ് Tower A (= 60 Bags)", "3 load msand (= 180 Bags)"]
    assert [p["body"]["quantity"] for p in state["pending"]] == [60, 180]
