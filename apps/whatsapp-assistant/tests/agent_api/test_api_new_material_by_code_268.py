"""[268] (Ilan, 6 Nov 13:36-13:37: "20 TMT Steel bars vannu", twice; nothing was prepared either time): a material not
in the list was the model's job in three calls (the line, add_material, the line again) and add_material sent it back
for a category; it gave up. The code now prepares both on the first call: the new material (category from its name,
never asked) and the line on it. The model's own add_material for it adds nothing more.

Guards: a listed material is never added again; a line for a material named on the card goes on it; nothing is saved
before Save.
"""

from __future__ import annotations

from tests.agent_api.test_api_new_material_210b import (
    DRUM,
    PAINT,
    TIN,
    Store,
    _add,
    _receipt,
    _save,
    _turn,
)


async def test_a_material_not_in_the_list_is_added_with_its_line_in_one_call() -> None:
    store = Store()
    turn = await _turn(store, [[_receipt(PAINT, "Wash Basin", TIN, 20, "20 tin Wash Basin")], "Wash Basin is new."],
                       "20 wash basin vannu")
    assert [e.tool for e in turn.pending] == ["add_material", "record_receipt"]
    assert turn.pending[0].body["name"] == "Wash Basin" and turn.pending[1].body["material_id"] == "new:Wash Basin"
    assert "category" not in turn.options and not turn.options  # never a category question
    assert store.received == [] and len(store.catalog) == 1  # a draft: nothing saved yet
    results = await _save(store, turn.pending)
    assert all(r.ok for r in results)
    assert store.received == [("Wash Basin", 20.0)]


async def test_the_second_production_call_a_new_line_with_no_add_is_prepared_too() -> None:
    store = Store()
    turn = await _turn(store, [[_receipt("new:Wash Basin", "Wash Basin", TIN, 20, "20 tin Wash Basin")], "Ok."],
                       "20 wash basin vannu")
    assert [e.tool for e in turn.pending] == ["add_material", "record_receipt"]


async def test_the_models_own_add_after_it_adds_nothing_more() -> None:
    store = Store()
    turn = await _turn(store, [[_receipt(PAINT, "Wash Basin", TIN, 20, "20 tin Wash Basin")],
                               [_add("Wash Basin")], "Ok."], "20 wash basin vannu")
    assert [e.tool for e in turn.pending] == ["add_material", "record_receipt"]


async def test_guard_a_listed_material_is_never_added() -> None:
    store = Store()
    turn = await _turn(store, [[_receipt(PAINT, "paint", DRUM, 2, "2 drum Paint")], "Ok."], "2 drum paint vannu")
    assert [e.tool for e in turn.pending] == ["record_receipt"] and turn.pending[0].body["material_id"] == PAINT
