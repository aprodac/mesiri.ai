"""MK-02b (live, 7 Nov 2026 19:57, test company): "M sand oru load 60 cum aanu, athu set cheyyu" put "1 load M Sand =
60 cum" on the card; Save was then refused with a reason cut mid-word ("as the bill or the supplie"), in English, ending
"send it again". The size is now checked before it is held (``size_check`` -> ``GET /materials/{id}/unit-check``
with the proposed size, the same reference the Save uses), and an API reason is never cut mid-word.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR

from agent_api.agent import _short, size_check
from agent_api.client import ApiClient
from mesiri.domains.materials.plausibility import Kind, Range, Reference, assess
from mesiri.domains.shared.auth import get_current_user

M_SAND, TMT12, TMT = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
LOAD, CUM, NOS, KG = (str(uuid.uuid4()) for _ in range(4))
_UNITS = {LOAD: ("load", "Loads"), CUM: ("cum", "Cubic Meters"), NOS: ("nos", "Numbers"), KG: ("kg", "Kilograms")}
_STOCK = {M_SAND: ("M Sand", CUM), TMT12: ("TMT 12mm", KG), TMT: ("TMT steel bars", KG)}
#: As migration 0515 seeds it (the API reads the tables; the stand-in reads this).
REF = Reference(
    kinds=(Kind("tmt_bar", "TMT steel bar", ("tmt", "bar"), {"rule": "round_bar", "divisor": 162, "length_m": 12,
                                                             "tolerance": 0.10}),
           Kind("sand", "Sand (M-sand, P-sand, river sand)", ("sand", "m sand"))),
    ranges={("sand", "load"): Range(Decimal(50), Decimal(600), "cft", "s"),
            ("tmt_bar", "nos"): Range(Decimal(2), Decimal(100), "kg", "s")},
    facts={("cum", "cft"): Decimal("35.3147")},
)


def _units_api() -> FastAPI:
    app = FastAPI()

    @app.get("/materials/{material_id}/unit-check")
    async def unit_check(material_id: str, unit_id: str, one_unit_equals: Decimal | None = None,
                         jwt: dict = Depends(get_current_user)):
        name, stock = _STOCK[material_id]
        answer = {"material": name, "unit": _UNITS[unit_id][0], "unit_name": _UNITS[unit_id][1],
                  "stock_unit": _UNITS[stock][0], "stock_unit_name": _UNITS[stock][1], "stock_unit_id": stock,
                  "fits": False, "one_unit_equals": None}
        if one_unit_equals is not None:
            verdict = assess(REF, material_name=name, from_code=_UNITS[unit_id][0], from_label=_UNITS[unit_id][0],
                             stock_code=_UNITS[stock][0], stock_label=_UNITS[stock][1], one_unit_equals=one_unit_equals)
            answer["plausible"] = verdict is None
            if verdict:
                answer["implausible"] = {"reason": verdict.reason, "usual_low": f"{verdict.low:f}",
                                         "usual_high": f"{verdict.high:f}", "usual_unit": verdict.unit,
                                         "said_in_usual_unit": f"{verdict.value.quantize(Decimal(1)):f}"}
        return answer

    return app


async def _size(material: str, unit: str, size: str, said: str) -> dict:
    client = ApiClient(ACTOR, app=_units_api())
    try:
        return await size_check(client, material, unit, Decimal(size), said)
    finally:
        await client.close()


async def test_reported_a_sixty_cum_load_is_never_held_and_one_question_is_asked() -> None:
    got = await _size(M_SAND, LOAD, "60", "M sand oru load 60 cum aanu, athu set cheyyu")
    assert "Nothing is prepared" in got["error"]
    assert "would be 2119 cft" in got["error"] and "usually 50 to 600 cft" in got["error"]
    assert "as the bill or the supplier says" in got["error"]
    assert "never ask them to send anything again" in got["error"]


async def test_sibling_an_impossible_bar_weight_is_never_held() -> None:
    got = await _size(TMT, NOS, "500", "oru kambi 500 kg")
    assert "Nothing is prepared" in got["error"] and "usually 2 to 100 kg" in got["error"]


async def test_guard_a_sized_bars_weight_is_never_asked_the_code_knows_it() -> None:
    """"TMT 12mm": the weight follows from the size (D²/162 x 12), so no size is set or asked, right or wrong."""
    for said in ("50", "10.7"):
        assert "already converts" in (await _size(TMT12, NOS, said, f"oru kambi {said} kg"))["error"]


async def test_guard_a_usual_size_is_still_held_with_its_line() -> None:
    assert await _size(M_SAND, LOAD, "4.25", "oru load 4.25 cum") == {"line": "📏 1 Loads M Sand = 4.25 Cubic Meters"}
    assert await _size(TMT, NOS, "10.7", "oru kambi 10.7 kg") == {"line": "📏 1 Numbers TMT steel bars = 10.7 Kilograms"}


def test_an_api_reason_is_never_cut_mid_word() -> None:
    reason = ("1 load of M Sand = 60 Cubic Meters looks wrong: that is 2119 cft, and 1 load of Sand is usually 50 to "
              "600 cft. How much is 1 load, as the bill or the supplier says? ") * 3
    cut = _short(reason)
    assert len(cut) <= 300 and cut.endswith(("?", ".", "…"))
    assert not cut.endswith("supplie")
    assert _short("short reason") == "short reason"


# -- sibling (live, 7 Nov 22:24): the same size as an admin's answer to a waiting size request --------------------

REQUEST = str(uuid.uuid4())


class SizeAnswer(BaseModel):
    one_unit_equals: Decimal


def _requests_api() -> FastAPI:
    app = _units_api()

    @app.get("/materials/size-requests")
    async def size_requests(jwt: dict = Depends(get_current_user)):
        return {"items": [{"id": REQUEST, "material_id": M_SAND, "from_unit_id": LOAD, "material": "M Sand"}]}

    @app.post("/materials/size-requests/{request_id}/answer")
    async def answer(request_id: str, body: SizeAnswer, jwt: dict = Depends(get_current_user)):
        return {"status": "answered"}

    return app


async def _answer(size: float, message: str):  # noqa: ANN202
    from agent_api.agent import ApiAgent
    from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
    from mesiri_ai.fakes import FakeToolCallingProvider

    app = _requests_api()
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "answer_size_request"))
    model = FakeToolCallingProvider([
        [("answer_size_request", {"request_id": REQUEST, "one_unit_equals": size, CONFIRM_ARG: f"1 load = {size:g} cum"})],
        "ok",
    ])
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(model, tools).run(client, message)
    finally:
        await client.close()


async def test_reported_an_admins_answer_of_sixty_cum_is_never_held() -> None:
    turn = await _answer(60, "M sand oru load 60 cum aanu, athu set cheyyu")
    assert turn.pending == []
    assert "usually 50 to 600 cft" in turn.calls[0]["result"]["error"]


async def test_guard_an_admins_usual_answer_is_held() -> None:
    turn = await _answer(4.25, "M sand oru load 4.25 cum aanu")
    assert [e.tool for e in turn.pending] == ["answer_size_request"]


# -- live, 7 Nov 22:30: "I could not ... try again in a minute" with no tool called ---------------------------------


def test_a_could_not_reply_with_no_tool_tried_is_caught() -> None:
    """The model copied the outage reply from the history instead of trying. WA-199's check now knows the past tense,
    so it sends the model back to its tools (a turn where a tool WAS called and failed is not touched: the guard runs
    only when no tool was called)."""
    from agent_api.reply_guard import claims_cannot

    for reply in ("I could not set the unit conversion right now. Please try again in a minute.",
                  "We couldn't save it.", "Ippo set cheyyan kazhinjilla.", "Save cheyyan pattiyilla.",
                  "ഇപ്പോൾ സേവ് ചെയ്യാൻ കഴിഞ്ഞില്ല."):
        assert claims_cannot(reply), reply
    for reply in ("Could not be better!", "Saved. The supplier could not come today.", "Couldn't you send it?"):
        assert not claims_cannot(reply), reply  # guard: not Mesiri saying it could not
