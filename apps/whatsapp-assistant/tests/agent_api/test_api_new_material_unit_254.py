"""[254] point 3 (5 Nov, Adarsh: "10 bags metal" held "Add Metal · counted in Cubic Feet"; "I don't need cubic feet"
kept it in cft; Ilan: the card said "counted in Cubic Feet" twice). Approved by Ilan in session, 5 Nov: a new material
is counted in the unit of its own line. The held add changes in place, its card note says the unit once, and no size
is asked.

Guard (WA-166, "1 load TMT" made TMT counted in loads): a line in a delivery unit (load, trip, drum, ...) keeps the
material's natural unit and the size question; a line already in the material's unit changes nothing.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from agent_api.agent import NEW, PendingWrite, adopt_line_unit

BAG, CFT, LOAD = (str(uuid.uuid4()) for _ in range(3))
UNITS = [{"id": BAG, "code": "bags", "display_name": "Bags", "is_active": True},
         {"id": CFT, "code": "cft", "display_name": "Cubic Feet", "is_active": True},
         {"id": LOAD, "code": "load", "display_name": "Loads", "is_active": True}]


class _Client:
    async def call(self, method: str, path: str, **kw: Any) -> Any:  # noqa: ANN401
        return SimpleNamespace(ok=True, body={"items": UNITS})


def _add(unit: str = CFT) -> PendingWrite:
    return PendingWrite("add_material", "POST", "/materials", {}, {"name": "Metal Chips", "default_unit_id": unit},
                        "➕ Add Metal Chips · counted in Cubic Feet · counted in Cubic Feet · 📂 Structural › Concrete",
                        "k-add")


async def _adopt(unit: str, *, in_waiting: bool = False) -> tuple[bool, PendingWrite]:
    new: list = [] if in_waiting else [_add()]
    waiting: list = [_add()] if in_waiting else []
    done = await adopt_line_unit(_Client(), {"unit_id": unit, "quantity": 10}, f"{NEW}Metal Chips",  # type: ignore[arg-type]
                                 waiting, new)
    return done, (waiting or new)[0]


async def test_the_new_material_is_counted_in_its_lines_unit_and_says_it_once() -> None:
    done, add = await _adopt(BAG)
    assert done and add.body["default_unit_id"] == BAG
    assert add.summary == "➕ Add Metal Chips · counted in Bags · 📂 Structural › Concrete"  # once, category kept


async def test_an_add_held_in_an_earlier_message_changes_too() -> None:
    done, add = await _adopt(BAG, in_waiting=True)
    assert done and add.body["default_unit_id"] == BAG


async def test_guard_a_load_keeps_the_natural_unit_and_the_size_question() -> None:
    done, add = await _adopt(LOAD)
    assert not done and add.body["default_unit_id"] == CFT


async def test_guard_a_line_already_in_the_materials_unit_changes_nothing() -> None:
    done, add = await _adopt(CFT)
    assert not done and add.summary.startswith("➕ Add Metal Chips · counted in Cubic Feet")


async def test_guard_no_add_waiting_for_that_name() -> None:
    new = [_add()]
    assert not await adopt_line_unit(_Client(), {"unit_id": BAG}, f"{NEW}Primer", [], new)  # type: ignore[arg-type]
    assert new[0].body["default_unit_id"] == CFT
