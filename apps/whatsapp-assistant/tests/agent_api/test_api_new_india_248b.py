"""[248] follow-up (5 Nov 10:12-10:18, New India, a new owner's first real day; cor_b80d8743, cor_dbc41949, cor_34b43357).

1. "20 wash basins, 20 toilets, 30 flush pipes" right after the model added Wash Basin, Toilet and Flushing Pipe: each
   delivery got a made-up material id, was refused, and was lost; the reply still said all were ready. Now the line's
   word in English ("വാഷ് ബേസിൻ" -> "Wash basin") puts it on the material being added; a line still refused for its
   material gets one more try, then the reply says plainly it is not on the card.
2. "one load = one truck of M-sand" was saved as "1 load M-sand = 60 cum" for the whole company: a size nobody said is
   never held (a conversion or an admin's size answer).
3. "how many kg is a ton?": a standard measure (ton -> kg, brass -> cft, a cement bag) is never asked or held as a size.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from tests.agent_api.standin import ACTOR, PROJECT, SITE
from tests.agent_api.test_api_english_bodies_243 import CEMENT, UNIT
from tests.agent_api.test_api_translate_248 import Translating, _run

from agent_api.agent import PendingWrite, not_held, size_check
from agent_api.client import ApiClient
from agent_api.tools import CONFIRM_ARG, MATERIAL_SAID
from mesiri.domains.shared.auth import get_current_user
from runtime.agent.wording import say

# -- 1. a delivery for a material added in the same message --------------------------------------------------------


def _add(name: str) -> tuple[str, dict]:
    return "add_material", {"name": name, "default_unit_id": UNIT, CONFIRM_ARG: f"പുതിയ മെറ്റീരിയൽ: {name}"}


def _line(said: str, quantity: float, material: str) -> tuple[str, dict]:
    return "record_receipt", {"project_id": PROJECT, "site_id": SITE, "material_id": material, "unit_id": UNIT,
                              "quantity": quantity, "occurred_date": dt.date.today().isoformat(), MATERIAL_SAID: said,
                              CONFIRM_ARG: f"{quantity:g} പീസ് {said}"}


async def test_reported_new_materials_and_their_deliveries_save_together() -> None:
    made_up = str(uuid.uuid4())  # the model's invented id for the material it had just added
    script = [[_add("Wash Basin"), _line("വാഷ് ബേസിൻ", 20, made_up), _add("Toilet"), _line("ടോയ്‌ലറ്റ്", 20, made_up)],
              "റെഡി."]
    model = Translating(script, {"വാഷ് ബേസിൻ": "Wash basin", "ടോയ്‌ലറ്റ്": "Toilet"})
    turn, saved, results = await _run(model, "വാഷ് ബേസിൻ 20 പീസ്, ടോയ്‌ലറ്റ് 20 പീസ് വന്നു")
    assert [e.tool for e in turn.pending] == ["add_material", "record_receipt", "add_material", "record_receipt"]
    assert all(r.ok for r in results)
    assert [s for s in saved if s[0] == "receipt"] == [("receipt", s[1], 20.0) for s in saved if s[0] == "receipt"]
    assert len([s for s in saved if s[0] == "receipt"]) == 2 and turn.not_held == []


async def test_a_line_still_refused_after_one_more_try_is_said_plainly() -> None:
    made_up = str(uuid.uuid4())
    lost = _line("ഫ്ലഷിന്റെ പൈപ്പ്", 30, made_up)  # no material is being added for it, and the model never adds one
    turn, saved, _ = await _run(Translating([[lost], "റെഡി.", [lost], "റെഡി."], {}), "ഫ്ലഷിന്റെ പൈപ്പ് 30 പീസ്")
    assert turn.not_held == ["30 പീസ് ഫ്ലഷിന്റെ പൈപ്പ്"] and saved == []
    assert "30 പീസ് ഫ്ലഷിന്റെ പൈപ്പ്" in say("api.not_held", "malayalam", lines=turn.not_held[0])


def _call(name: str, arguments: dict, error: str = "") -> SimpleNamespace:
    return SimpleNamespace(name=name, arguments=arguments,
                           outcome=SimpleNamespace(content={"error": error} if error else {"status": "ready"}))


def test_guard_only_material_refusals_count_and_a_line_taken_up_later_is_not_listed() -> None:
    line = {"quantity": 20, CONFIRM_ARG: "20 Wash Basin"}
    refused = _call("record_receipt", line, "'Wash basin' is not in the company's material list (nearest: …)")
    held = PendingWrite(tool="record_receipt", method="POST", path="/materials/inflows", params={},
                        body={"quantity": 20}, summary="20 Wash Basin", idempotency_key="k")
    assert not_held([refused], []) == ["20 Wash Basin"]
    assert not_held([refused], [held]) == []  # prepared after the refusal
    rate = _call("record_receipt", {"quantity": 1, CONFIRM_ARG: "1 bag"}, "310 is a rate they said, but …")
    asked = _call("record_receipt", line, "Already saved at 10:12: …")
    assert not_held([rate, asked], []) == []  # meant refusals: a question, a rate


# -- 2 and 3. sizes: never made up, never a standard measure -------------------------------------------------------

M_SAND, STEEL, CEMENT_ID = (str(uuid.uuid4()) for _ in range(3))
LOAD, CUM, TONS, KG, BAGS = (str(uuid.uuid4()) for _ in range(5))
_UNITS = {LOAD: ("load", "Loads"), CUM: ("cum", "Cubic Meters"), TONS: ("tons", "Tons"), KG: ("kg", "Kilograms"),
          BAGS: ("bags", "Bags")}
_STOCK = {M_SAND: ("M Sand", CUM), STEEL: ("Steel", KG), CEMENT_ID: ("Cement", BAGS)}


def _units_api() -> FastAPI:
    app = FastAPI()

    @app.get("/materials/{material_id}/unit-check")
    async def unit_check(material_id: str, unit_id: str, jwt: dict = Depends(get_current_user)):
        name, stock = _STOCK[material_id]
        return {"material": name, "unit": _UNITS[unit_id][0], "unit_name": _UNITS[unit_id][1],
                "stock_unit": _UNITS[stock][0], "stock_unit_name": _UNITS[stock][1], "stock_unit_id": stock,
                "fits": False, "one_unit_equals": None}

    return app


async def _size(material: str, unit: str, size: str, said: str | None) -> dict:
    client = ApiClient(ACTOR, app=_units_api())
    try:
        return await size_check(client, material, unit, Decimal(size), said)
    finally:
        await client.close()


async def test_reported_a_size_nobody_said_is_never_held() -> None:
    said = "ഒരു ലോഡ് എം സാൻഡ് എന്ന് പറഞ്ഞാൽ ഒരു ട്രക്ക്, വൺ ട്രക്ക് എം സാൻഡ് വന്നു"
    got = await _size(M_SAND, LOAD, "60", said)
    assert "is not a size they said" in got["error"]


async def test_guard_a_size_they_said_is_held() -> None:
    got = await _size(M_SAND, LOAD, "3", "1 load M-sand is 3 cum")
    assert got == {"line": "📏 1 Loads M Sand = 3 Cubic Meters"}


async def test_reported_tons_to_kg_is_never_a_size_to_ask_or_set() -> None:
    got = await _size(STEEL, TONS, "1000", "Bro, one ton enn parnja 1000 kg")
    assert "already converts Tons to Kilograms" in got["error"]  # even when they said it: it is known
    assert "already converts" in (await _size(CEMENT_ID, KG, "0.02", None))["error"]  # a cement bag is 50 kg


def test_the_sop_knows_standard_measures() -> None:
    from agent_api.agent import SOP

    text = " ".join(SOP.split())
    assert "1 ton = 1000 kg" in text and "never make one up" in text
    assert CEMENT  # shared fixture
