"""[271] (Ilan, 6 Nov 13:38-13:39, Aprodac: "50 chaakku M sand vannu", M Sand counted in cubic metres): the size was
asked "1 Bags M Sand = how many Cubic Meters?" (a fraction nobody knows); after Save the admin was told to send it
"e.g. '1 load = 60 bags'", sent "1 load = 50 bags", and got back the code's own note "(ignored, not an answer to ...)".

Fix: the bigger unit is asked about by size rank (cubic metre > bag > kg); the held reply's example is the line's own
question; the code's notes never reach the person.

Guards: a load is still the bigger unit; kg against bags still asks about the bag; a real reply is untouched.
"""

from __future__ import annotations

from agent_api.agent import PendingWrite, WriteResult, size_sides
from agent_api.reply_guard import without_internals
from agent_api.whatsapp import size_example


def _sides(said: str, stock: str) -> dict:
    return size_sides({"unit": said, "stock_unit": stock, "unit_name": said.title(), "stock_unit_name": stock.title(),
                       "material": "M Sand"})


def test_bags_against_cubic_metres_asks_about_the_cubic_metre() -> None:
    sides = _sides("bags", "cum")
    assert (sides["big"], sides["small"], sides["stock_bigger"]) == ("Cum", "Bags", True)


def test_guards_a_load_is_bigger_and_a_bag_is_bigger_than_a_kilo() -> None:
    assert _sides("load", "bags")["big"] == "Load"
    assert _sides("bags", "load")["big"] == "Load"
    assert _sides("bags", "kg")["big"] == "Bags"
    assert _sides("nos", "kg")["big"] == "Nos"  # same rank: the unit they said, as before


def test_the_held_reply_example_is_the_lines_own_question() -> None:
    held = WriteResult(PendingWrite("record_receipt", "POST", "/materials/inflows", {}, {},
                                    "50 bags M Sand, Main block (1 Cubic Meters = how many Bags?)", "k"), 202, {})
    assert size_example([held]) == "1 Cubic Meters = … Bags"
    assert "load" in size_example([])


def test_the_codes_note_never_reaches_the_person() -> None:
    echoed = '(ignored, not an answer to "1 Bags M Sand-il ethra Cubic Meters undu?")'
    assert without_internals(echoed) == ""
    assert without_internals("Sheri. " + echoed).strip() == "Sheri."
    assert without_internals("1 load-il 50 bags aanu.") == "1 load-il 50 bags aanu."  # guard
