"""WA-194 (5 Nov, Ilan, from users' feedback in the control panel): a material that is not in the catalogue must never become a
blocker, and must never be saved in Malayalam. "2 drum primer vannu" used to stop at a question ("Same as Paint, or
add Primer?") with nothing prepared. Now the model holds the new material (English name) and the line in the same
turn: one Save adds Primer to the catalogue and records the line. If they meant one they have ("athu paint aanu"),
the line moves there, the new material leaves the list, and their word is remembered as that material's name.
"""

from __future__ import annotations

from tests.agent_api.test_api_new_material_210b import (
    DRUM,
    LITRE,
    PAINT,
    Store,
    _add,
    _receipt,
    _save,
    _turn,
)

from agent_api.agent import ApiTurn


async def _held(store: Store) -> ApiTurn:
    return await _turn(store, [[_receipt(PAINT, "primer", LITRE, 40, "40 L Paint")],
                               [_add("Primer"), _receipt("new:Primer", "primer", LITRE, 40, "📥 40 L Primer")],
                               "Primer is new: Save adds it to your list."], "40 litre primer vannu")


async def test_unknown_material_is_held_with_its_line_and_one_save_adds_both() -> None:
    store = Store()
    turn = await _held(store)
    assert turn.options == [] and [e.tool for e in turn.pending] == ["add_material", "record_receipt"]
    results = await _save(store, turn.pending)
    assert all(r.ok for r in results)
    assert [r["name"] for r in store.catalog] == ["Paint", "Primer"]
    assert store.received == [("Primer", 40.0)]


async def test_it_is_paint_moves_the_line_drops_the_new_material_and_remembers_the_word() -> None:
    store = Store()
    held = await _held(store)
    change = ("change_ready_entry", {"number": 2, "changes": {"material_id": PAINT}, "confirm_line": "📥 40 L Paint"})
    turn = await _turn(store, [[change], "Moved to Paint."], "athu paint aanu", ready=held.pending)
    assert [e.tool for e in turn.pending] == ["record_receipt", "add_material_alias"]
    assert turn.pending[1].path == f"/materials/{PAINT}/aliases" and turn.pending[1].body == {"alias": "Primer"}
    results = await _save(store, turn.pending)
    assert all(r.ok for r in results)
    assert [r["name"] for r in store.catalog] == ["Paint"]  # no stray Primer in the catalogue
    assert store.catalog[0]["aliases"] == ["Primer"]
    assert store.received == [("Paint", 40.0)]


async def test_sibling_the_size_of_the_new_material_goes_with_it_when_it_is_moved() -> None:
    store = Store()
    held = await _turn(store, [[_add("Primer"), _receipt("new:Primer", "primer", DRUM, 2, "📥 2 drum Primer"),
                                ("set_unit_conversion", {"material_id": "new:Primer", "from_unit_id": DRUM,
                                                         "one_unit_equals": 20, "confirm_line": "1 drum = 20 L"})],
                               "Ready."], "2 drum primer vannu")
    assert len(held.pending) == 3
    change = ("change_ready_entry", {"number": 2, "changes": {"material_id": PAINT}})
    turn = await _turn(store, [[change], "Moved."], "paint thanne", ready=held.pending)
    assert [e.tool for e in turn.pending] == ["record_receipt", "add_material_alias"]


async def test_guard_a_malayalam_name_is_never_held_as_a_new_material() -> None:
    store = Store()
    turn = await _turn(store, [[_add("ചോക്ക്")], "?"], "chokk vannu")
    assert turn.pending == [] and "English" in turn.calls[0]["result"]["error"]


async def test_guard_a_material_in_the_list_is_never_added_again() -> None:
    store = Store()
    turn = await _turn(store, [[_add("paint")], "?"], "paint vannu")
    assert turn.pending == [] and "already in the company's list" in turn.calls[0]["result"]["error"]


async def test_guard_moving_one_of_two_lines_keeps_the_new_material_for_the_other() -> None:
    store = Store()
    held = await _turn(store, [[_add("Primer"), _receipt("new:Primer", "primer", LITRE, 40, "40 L Primer"),
                                _receipt("new:Primer", "primer", LITRE, 10, "10 L Primer")], "Ready."], "primer 40, 10")
    turn = await _turn(store, [[("change_ready_entry", {"number": 3, "changes": {"material_id": PAINT}})], "Moved."],
                       "the 10 is paint", ready=held.pending)
    assert [e.tool for e in turn.pending] == ["add_material", "record_receipt", "record_receipt"]
