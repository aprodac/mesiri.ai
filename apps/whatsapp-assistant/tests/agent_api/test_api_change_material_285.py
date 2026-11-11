"""[285] (live, 11 Nov 12:57-12:59, New India): "20 ton Tata steel and 30 ton TMT steel came; they are different
items". TMT steel went on the listed Steel (its trade name, [254]) and the card said "Steel". "Steel ennallathu
maattittu TMT steel aakku" then went round three turns: change_ready_entry refused material_said ("cannot change
material_said") while the material check asked for it ("pass material_said"), and with only material_id the line
stayed on Steel. Nothing changed.

Now material_said is read by change_ready_entry (never sent as a field), and a line corrected away from the material
it is on, to a narrower name ("TMT steel" for "Steel"), goes on a new material with one Save.

Guards: a correction to another listed material moves the line there (no new material); "steel" for a line on Steel
adds nothing; a quantity change is unchanged.
"""

from __future__ import annotations

import uuid

from tests.agent_api.test_api_new_material_210b import LITRE, PAINT, Store, _receipt, _save, _turn

from agent_api.agent import CHANGE_READY
from mesiri_ai.models import ChatMessage

STEEL = str(uuid.uuid4())


def _store() -> Store:
    store = Store()
    store.catalog.append({"id": STEEL, "name": "Steel", "aliases": [], "default_unit_id": LITRE})
    return store


def _change(changes: list[tuple[str, str]], line: str, number: int = 1) -> tuple[str, dict]:
    return (CHANGE_READY, {"number": number, "changes": [{"field": f, "value": v} for f, v in changes],
                           "confirm_line": line})


SAID = [ChatMessage(role="user", text="30 ton TMT steel vannu"), ChatMessage(role="model", text="Ready.")]


async def _on_steel(store: Store):  # noqa: ANN202
    turn = await _turn(store, [[_receipt(STEEL, "TMT steel", LITRE, 30, "30 ton TMT steel, Green Villa")], "Ready."],
                       "30 ton TMT steel vannu")
    assert [e.body["material_id"] for e in turn.pending] == [STEEL]  # [254]: TMT is the trade name of Steel
    return turn.pending


async def test_the_reported_correction_puts_the_line_on_a_new_tmt_steel() -> None:
    store = _store()
    ready = await _on_steel(store)
    turn = await _turn(store, [[_change([("material_id", STEEL), ("material_said", "TMT steel")],
                                        "30 ton TMT steel, Green Villa")], "Changed."],
                       "Steel ennallathu maattittu TMT steel aakku", ready=ready, history=SAID)
    assert "error" not in turn.calls[0]["result"], turn.calls[0]["result"]
    assert [e.tool for e in turn.pending] == ["add_material", "record_receipt"]
    assert turn.pending[0].body["name"] == "TMT steel"
    assert turn.pending[1].body["material_id"] == "new:TMT steel" and turn.pending[1].body["quantity"] == 30
    assert store.received == []  # nothing saved before Save
    results = await _save(store, turn.pending)
    assert all(r.ok for r in results), [(r.pending.summary, r.body) for r in results]
    assert store.received == [("TMT steel", 30.0)]  # Steel's stock is untouched


async def test_sibling_material_said_alone_is_enough() -> None:
    store = _store()
    ready = await _on_steel(store)
    turn = await _turn(store, [[_change([("material_said", "TMT steel")], "30 ton TMT steel")], "Changed."],
                       "make it TMT steel", ready=ready, history=SAID)
    assert [e.tool for e in turn.pending] == ["add_material", "record_receipt"]


async def test_sibling_a_word_not_in_the_list_is_a_new_material_too() -> None:
    store = _store()
    ready = await _on_steel(store)
    turn = await _turn(store, [[_change([("material_said", "Binding wire")], "30 binding wire")], "Changed."],
                       "alla, binding wire aanu", ready=ready, history=SAID)
    assert [e.tool for e in turn.pending] == ["add_material", "record_receipt"]
    assert turn.pending[0].body["name"] == "Binding wire"


async def test_guard_another_listed_material_moves_the_line_with_nothing_new() -> None:
    store = _store()
    ready = await _on_steel(store)
    turn = await _turn(store, [[_change([("material_id", PAINT), ("material_said", "paint")], "30 tin Paint")],
                                "Changed."], "alla, paint aanu", ready=ready, history=SAID)
    assert [(e.tool, e.body["material_id"]) for e in turn.pending] == [("record_receipt", PAINT)]


async def test_guard_the_listed_name_itself_adds_nothing() -> None:
    store = _store()
    ready = await _on_steel(store)
    turn = await _turn(store, [[_change([("material_said", "steel"), ("quantity", "25")], "25 ton Steel")],
                                "Changed."], "25 ton steel aanu", ready=ready, history=SAID)
    assert [(e.tool, e.body["material_id"], e.body["quantity"]) for e in turn.pending] == [
        ("record_receipt", STEEL, 25)]


async def test_guard_an_unknown_field_is_still_refused() -> None:
    store = _store()
    ready = await _on_steel(store)
    turn = await _turn(store, [[_change([("colour", "red")], "x")], "Sorry."], "red", ready=ready, history=SAID)
    assert "cannot change colour" in turn.calls[0]["result"]["error"]
