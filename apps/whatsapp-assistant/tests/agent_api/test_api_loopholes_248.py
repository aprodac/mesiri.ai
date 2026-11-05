"""[248] follow-ups (5 Nov): the loopholes left after WA-204.

1. A quantity nobody said is never held: "310 a bag" became a receipt of 1 bag. Sent back to the model once; a number
   they said in words goes through when it comes back.
2. A material word in Latin letters that is not English (Manglish "manal", "kambi") is translated by Mesiri, then
   matched to a material's own name only (never part of one); not listed: the new material gets the English name.
3. Structural and safety questions always end with "a structural engineer must check it on site" (SOP).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from tests.agent_api.standin import PROJECT, SITE
from tests.agent_api.test_api_english_bodies_243 import CEMENT, UNIT, _receipt
from tests.agent_api.test_api_translate_248 import Translating, _run

from agent_api.agent import made_up
from agent_api.tools import CONFIRM_ARG, MATERIAL_SAID

SAND, WIRE = str(uuid.uuid4()), str(uuid.uuid4())


def _line(said: str, material: str, quantity: float, rate: float | None = None) -> tuple[str, dict]:
    name, body = _receipt(said, material)
    body = {**body, "quantity": quantity, CONFIRM_ARG: f"{quantity:g} {said}"}
    return name, ({**body, "unit_cost": rate} if rate is not None else body)


# -- 1. no made-up quantity ---------------------------------------------------------------------------------------


def test_a_rate_is_not_a_quantity() -> None:
    words = "SMK 20 bag cement 300 rupees, VMV 310 a bag, FMR 312. which is better?"
    assert "the quantity 1 is not in their words" in made_up(words, {"quantity": 1, "unit_cost": 310})
    assert made_up(words, {"quantity": 20, "unit_cost": 300}) == ""


def test_guards_only_a_line_with_a_rate_they_said_is_checked() -> None:
    assert made_up("2 drum primer", {"quantity": 40}) == ""  # no rate: WA-200 owns worked-out quantities
    assert made_up("cement 310 a bag", {"quantity": 50, "unit_cost": 300}) == ""  # rate not theirs: not this check
    assert made_up("aaru bag cement 310", {"quantity": 6, "unit_cost": 310}) != ""  # sent back once; resend passes
    assert made_up("bill\nWhat the photo shows: 12 bags cement @ 400", {"quantity": 12, "unit_cost": 400}) == ""


async def test_journey_a_made_up_quantity_goes_back_once_and_a_said_one_is_held() -> None:
    words = "20 ചാക്ക് cement 300, ഒരു ബാഗിന് 310"
    made = _line("cement", CEMENT, 1, 310)
    turn, saved, _ = await _run(Translating([[_line("cement", CEMENT, 20, 300), made], "ശരി."]), words)
    assert "is not in their words" in turn.calls[1]["result"]["error"]
    assert saved == [("receipt", CEMENT, 20.0)]  # the 1 bag nobody said is not held
    # The model says it again (it was "oru" = 1): it goes through.
    turn, saved, _ = await _run(Translating([[made], [made], "ശരി."]), "ഒരു ബാഗ് cement 310")
    assert saved == [("receipt", CEMENT, 1.0)]


# -- 2. Manglish material words ---------------------------------------------------------------------------------


async def test_manglish_material_is_translated_and_matched_to_its_own_name() -> None:
    catalog = [{"id": SAND, "name": "Sand", "aliases": []}, {"id": CEMENT, "name": "Cement", "aliases": []}]
    turn, saved, _ = await _run(Translating([[_line("manal", CEMENT, 3)], "Sheri."], {"manal": "Sand"}),
                                "3 load manal vannu", catalog=catalog)
    assert saved == [("receipt", SAND, 3.0)]  # never the near one the model picked


async def test_a_translation_matches_a_whole_name_only_never_part_of_one() -> None:
    catalog = [{"id": WIRE, "name": "Binding Wire", "aliases": []}]
    turn, saved, _ = await _run(Translating([[_line("kambi", WIRE, 70)], "Sheri."], {"kambi": "Wire"}),
                                "70 kambi vannu", catalog=catalog)
    assert saved == []
    told = turn.calls[0]["result"]["error"]
    assert "'Wire'" in told and "not in the company's material list" in told  # the English name offered, no guess


async def test_guard_an_english_word_that_translates_to_itself_costs_no_match_change() -> None:
    catalog = [{"id": CEMENT, "name": "Cement", "aliases": []}]
    model = Translating([[_line("primer", CEMENT, 2)], "Ok."], {})
    turn, saved, _ = await _run(model, "2 drum primer came", catalog=catalog)
    assert saved == [] and "'Primer' is not in the company's material list" in turn.calls[0]["result"]["error"]


# -- 3. structural questions -----------------------------------------------------------------------------------


def test_the_sop_sends_structural_questions_to_an_engineer() -> None:
    sop = " ".join((Path(__file__).resolve().parents[2] / "src" / "agent_api" / "SOP.md").read_text("utf-8").split())
    assert "structural engineer (or a licensed electrician) must check it on site" in sop
    assert "Never say a structure is safe" in sop
    assert MATERIAL_SAID and PROJECT and SITE and UNIT
