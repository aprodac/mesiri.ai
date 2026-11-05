"""[254] (5 Nov 12:30, an admin's voice note: "10 bags of metal came"): "Metal" was held as a NEW material in cft beside
its line, though in Kerala "metal" / "jelly" IS aggregate and the company's list has Aggregate 20mm and 40mm. The
material check knew only names and taught aliases. Now the starter list's trade names (backend
``materials.defaults.TRADE_NAMES``) count: one listed match takes the line, plain "metal" asks which size with both
as buttons, and adding "Metal" as a new material is refused.

Siblings: "20mm jelly", "msand", "kambi", a Malayalam word translated to "jelly". Guards: "metal sheet" and "baby
metal" are not aggregate; M Sand and P Sand never merge; a listed "Baby Metal" stays itself; after they pick a size,
no second question.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from agent_api.materials import already_listed, settle_material, trade_rows
from mesiri.domains.materials.defaults import STARTER_MATERIALS, TRADE_NAMES, trade_name_of

AGG20, AGG40, MSAND, PSAND, STEEL, BABY = (str(uuid.uuid4()) for _ in range(6))
ROWS = [
    {"id": AGG20, "name": "Aggregate 20mm", "aliases": []},
    {"id": AGG40, "name": "Aggregate 40mm", "aliases": []},
    {"id": MSAND, "name": "M Sand", "aliases": []},
    {"id": PSAND, "name": "P Sand", "aliases": []},
    {"id": STEEL, "name": "Steel", "aliases": []},
    {"id": BABY, "name": "Baby Metal", "aliases": []},
]


class _Client:
    def __init__(self, rows: list[dict] = ROWS) -> None:
        self._rows = rows

    async def call(self, method: str, path: str, params: Any = None, **kw: Any) -> Any:  # noqa: ANN401
        return SimpleNamespace(ok=True, body={"items": self._rows})


async def _settle(said: str, picked: str = "", words: str = "", english: Any = None) -> tuple[dict, str, list]:
    body = {"material_id": picked or str(uuid.uuid4()), "quantity": 10}
    problem, buttons = await settle_material(_Client(), body, said, words or said, [], english)  # type: ignore[arg-type]
    return body, problem, buttons


async def test_plain_metal_asks_which_aggregate_with_both_as_buttons_never_new() -> None:
    _body, problem, buttons = await _settle("metal", words="10 bag metal vannu")
    assert buttons == ["Aggregate 20mm", "Aggregate 40mm"]
    assert "NOT a new material" in problem and "add_material" in problem


@pytest.mark.parametrize(("said", "expected"), [
    ("20mm jelly", AGG20), ("40 mm metal", AGG40), ("msand", MSAND), ("M-sand", MSAND), ("p sand", PSAND),
    ("kambi", STEEL), ("TMT bars", STEEL),
])
async def test_a_trade_name_of_one_listed_material_takes_the_line(said: str, expected: str) -> None:
    body, problem, buttons = await _settle(said)
    assert (problem, buttons) == ("", []) and body["material_id"] == expected


async def test_after_they_pick_a_size_there_is_no_second_question() -> None:
    body, problem, _ = await _settle("metal", picked=AGG20, words="10 bag metal vannu Aggregate 20mm")
    assert problem == "" and body["material_id"] == AGG20


async def test_a_malayalam_word_translated_to_jelly_asks_the_same() -> None:
    async def english(word: str) -> str:
        return "jelly"

    _body, problem, buttons = await _settle("ജല്ലി", english=english)
    assert buttons == ["Aggregate 20mm", "Aggregate 40mm"] and "NOT a new material" in problem


async def test_adding_metal_as_a_new_material_is_refused_and_names_both() -> None:
    listed = await already_listed(_Client(), "Metal")  # type: ignore[arg-type]
    assert "Aggregate 20mm" in listed and "Aggregate 40mm" in listed and " or " in listed


# -- guards -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("said", ["metal sheet", "GI sheet", "cement", "primer"])
def test_guard_words_that_are_not_trade_names(said: str) -> None:
    assert trade_rows(said, ROWS) == []


async def test_guard_a_listed_baby_metal_stays_itself() -> None:
    body, problem, _ = await _settle("baby metal", picked=BABY)
    assert problem == "" and body["material_id"] == BABY


def test_guard_m_sand_and_p_sand_never_merge() -> None:
    assert trade_name_of("msand") == ("M Sand",) and trade_name_of("psand") == ("P Sand",)


def test_guard_only_names_the_company_still_has() -> None:
    assert [r["name"] for r in trade_rows("metal", ROWS[1:])] == ["Aggregate 40mm"]


def test_every_trade_name_points_at_a_starter_material() -> None:
    starters = {m.name for m in STARTER_MATERIALS}
    assert set(TRADE_NAMES) <= starters
