"""[301] (15 Nov, Ilan's voice notes on Aprodac and the test company): "innu steel vannu, 2 ton Tata steel, 3 ton TMT
steel". The model put both lines on the listed "Steel"; the code then kept "T M T steel" on plain Steel (TMT was a
trade name of Steel, [254]), so the card said "Steel · 3 tons" and TMT was lost, while "Tata steel" became a new
material. In the test company, whose list has "TMT steel bars", the trade name even outranked that listed material.
A correction ("Tmt steelo?") then made "TMT steel" a separate material ([285]): two rules disagreed.

Now one rule (Ilan, #9652: sites read stock by type): a type word is never folded into the generic material. The
line goes on the listed material of that type, or becomes a new one beside the generic, the way a brand does.
Siblings: spelled-out letters from speech ("T M T", "P P C"), cement grades. Guards: words that only say "steel"
("kambi", "steel rods") stay Steel; plain "steel" stays Steel; "metal" still asks which aggregate.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from agent_api.materials import narrower_than, settle_material, title
from mesiri.domains.materials.defaults import trade_name_of

STEEL, TMT_BARS, CEMENT, AGG20, AGG40 = (str(uuid.uuid4()) for _ in range(5))
ONLY_STEEL = [{"id": STEEL, "name": "Steel", "aliases": []}, {"id": CEMENT, "name": "Cement", "aliases": []},
              {"id": AGG20, "name": "Aggregate 20mm", "aliases": []}, {"id": AGG40, "name": "Aggregate 40mm",
                                                                          "aliases": []}]
WITH_TMT = [*ONLY_STEEL, {"id": TMT_BARS, "name": "TMT steel bars", "aliases": []}]


class _Client:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def call(self, method: str, path: str, params: Any = None, **kw: Any) -> Any:  # noqa: ANN401
        return SimpleNamespace(ok=True, body={"items": self._rows})


async def _settle(rows: list[dict], said: str, picked: str = STEEL) -> tuple[dict, str, dict]:
    body = {"material_id": picked, "quantity": 3}
    found: dict = {}
    problem, _ = await settle_material(_Client(rows), body, said, said, [], None, found)  # type: ignore[arg-type]
    return body, problem, found


# -- the reported messages -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("said", ["T M T steel", "TMT steel", "tmt"])
async def test_tmt_on_steel_goes_to_the_listed_tmt_material(said: str) -> None:
    """Test company, 14:31: the model picked plain Steel; the listed "TMT steel bars" is the one."""
    body, problem, _ = await _settle(WITH_TMT, said)
    assert problem == "" and body["material_id"] == TMT_BARS


async def test_tmt_steel_with_only_steel_listed_is_a_new_type_never_plain_steel() -> None:
    """Aprodac, 15:13: the line said "Steel · 3 tons"; now it is held as the new material TMT steel, named so."""
    body, problem, found = await _settle(ONLY_STEEL, "T M T steel")
    assert body["material_id"] == STEEL  # untouched: the code prepares the new material with the line
    assert "is not in the company's material list" in problem and "Steel" in problem
    assert found["new_name"] == "TMT steel" and "Steel" in found["near"]


async def test_a_brand_and_a_type_said_together_are_treated_alike() -> None:
    _, tata, _ = await _settle(ONLY_STEEL, "Tata steel")
    _, tmt, _ = await _settle(ONLY_STEEL, "TMT steel")
    assert "not in the company's material list" in tata and "not in the company's material list" in tmt


async def test_the_correction_rule_agrees_with_the_line_rule() -> None:
    """[285] (a correction "Tmt steelo?") and the line check now say the same: TMT steel is narrower than Steel."""
    assert await narrower_than(_Client(ONLY_STEEL), "TMT steel", STEEL) == "Steel"  # type: ignore[arg-type]
    assert trade_name_of("tmt steel") == () and trade_name_of("tmt") == ()


# -- siblings -------------------------------------------------------------------------------------------------------

async def test_a_cement_grade_spelled_out_is_its_own_type() -> None:
    body, problem, found = await _settle(ONLY_STEEL, "P P C cement", picked=CEMENT)
    assert "not in the company's material list" in problem and found["new_name"] == "PPC cement"


def test_spelled_out_letters_make_one_word_in_a_new_name() -> None:
    assert title("T M T steel") == "TMT steel" and title("u p v c pipe") == "UPVC pipe"


# -- guards ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("said", ["steel", "Steel", "kambi", "steel rods"])
async def test_guard_words_that_only_say_steel_stay_steel(said: str) -> None:
    body, problem, _ = await _settle(ONLY_STEEL, said)
    assert problem == "" and body["material_id"] == STEEL


async def test_guard_plain_metal_still_asks_which_aggregate() -> None:
    _, problem, _ = await _settle(ONLY_STEEL, "metal", picked=str(uuid.uuid4()))
    assert "NOT a new material" in problem
