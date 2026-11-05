"""[210] (Mesiri Test Builders, 3 Nov 08:58-08:59, cor_c5790dcf2ad34204922cfd7f54769406,
cor_f90a33076477477b81f1c7190c7357a1, cor_01692818e9404b5786d6a40e7777d13c): "2 drum primer vannu" -> "20 litre
drum" -> "2 drum (40 litres) Paint received" -> Save: saved as Paint. Primer is not in the list; the model took the
nearest item and nothing checked it. The ready sentence also came out garbled (a copied, translated memory note).

Now the code checks the material id against the word they said: the list's name or a learned alias goes through,
anything else is buttons (the nearest + "➕ Add Primer") and nothing is prepared. The choice is remembered as an
alias. (The replay of cor_f90a... could not be fetched on the bot server: no control-plane token; this scripts it.)
"""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, Header
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR, PROJECT, SITE

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.materials import is_material
from agent_api.tools import ALLOWED, CONFIRM_ARG, MATERIAL_SAID, build_tools
from agent_api.whatsapp import without_copied_lines
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_ai.models import ChatMessage

PAINT, CEMENT, TMT, MSAND, WIRE = (str(uuid.uuid4()) for _ in range(5))
LITRE = str(uuid.uuid4())
CATALOG = [
    {"id": PAINT, "name": "Paint", "aliases": []},
    {"id": CEMENT, "name": "Cement OPC 53", "aliases": ["സിമന്റ്"]},
    {"id": TMT, "name": "TMT bar 12mm", "aliases": ["kambi"]},
    {"id": MSAND, "name": "M-Sand", "aliases": []},
]


class Inflow(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID | None = None
    material_id: uuid.UUID
    unit_id: uuid.UUID
    quantity: float
    occurred_date: str


class Alias(BaseModel):
    alias: str


def _api(catalog: list[dict], saved: list[dict]) -> FastAPI:
    app = FastAPI()

    @app.get("/materials")
    async def materials(search: str | None = None, limit: int = 50, is_active: bool | None = None,
                        jwt: dict = Depends(get_current_user)):
        return {"items": catalog, "total": len(catalog)}

    @app.get("/materials/units-of-measure")
    async def units(jwt: dict = Depends(get_current_user)):
        return {"items": [{"id": LITRE, "code": "ltr", "display_name": "Litres", "is_active": True}]}

    @app.post("/materials/inflows", status_code=201)
    async def inflow(body: Inflow, jwt: dict = Depends(get_current_user),
                     idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        saved.append({"material": str(body.material_id), "quantity": body.quantity})
        return {"id": str(uuid.uuid4())}

    @app.post("/materials/{material_id}/aliases", status_code=201)
    async def alias(material_id: str, body: Alias, jwt: dict = Depends(get_current_user)):
        saved.append({"alias": body.alias, "material": material_id})
        return {"material_id": material_id, "alias": body.alias}

    return app


def _receipt(material: str, said: str | None, line: str) -> tuple[str, dict]:
    args = {"project_id": PROJECT, "site_id": SITE, "material_id": material, "unit_id": LITRE,
            "quantity": 40, "occurred_date": "2026-11-03", CONFIRM_ARG: line}
    if said is not None:
        args[MATERIAL_SAID] = said
    return ("record_receipt", args)


async def _run(script: list, text: str, catalog: list[dict] = CATALOG, history: list[ChatMessage] | None = None):  # noqa: ANN202
    saved: list[dict] = []
    app = _api(catalog, saved)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in ("record_receipt", "add_material_alias")))
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text, history=history), saved
    finally:
        await client.close()


async def test_the_reported_message_primer_is_never_saved_as_paint() -> None:
    turn, saved = await _run([[_receipt(PAINT, "primer", "2 drum (40 litres) Paint received")],
                              "Primer isn't in your list."], "2 drum primer vannu")
    assert turn.pending == [] and saved == []
    error = turn.calls[0]["result"]["error"]
    assert "Primer" in error and "Never record it as another material" in error
    # WA-194: no question, no buttons: the model holds the new material and the line in this same turn.
    assert "do NOT ask" in error and "new:" in error and "Paint" in error
    assert turn.options == []


async def test_the_reported_message_without_material_said_is_checked_on_their_words() -> None:
    turn, _ = await _run([[_receipt(PAINT, None, "2 drum Paint")], "Which material?"], "20 litre drum",
                         history=[ChatMessage(role="user", text="2 drum primer vannu")])
    assert turn.pending == []


async def test_choosing_paint_remembers_primer_and_prepares_the_line() -> None:
    alias = ("add_material_alias", {"material_id": PAINT, "alias": "primer", CONFIRM_ARG: "Primer = Paint"})
    turn, _ = await _run([[alias, _receipt(PAINT, "primer", "2 drum (40 L) primer as Paint")], "Ready."], "Paint")
    assert [e.tool for e in turn.pending] == ["add_material_alias", "record_receipt"]
    assert turn.pending[0].body == {"alias": "primer"}


async def test_sibling_binding_wire_is_not_tmt() -> None:
    turn, _ = await _run([[_receipt(TMT, "binding wire", "10 kg binding wire")], "?"], "10 kg binding wire vannu")
    assert turn.pending == [] and "Binding wire" in turn.calls[0]["result"]["error"] and turn.options == []


async def test_sibling_p_sand_is_not_m_sand() -> None:
    turn, _ = await _run([[_receipt(MSAND, "P-sand", "1 load P-sand")], "?"], "1 load P-sand vannu")
    assert turn.pending == [] and "nearest: M-Sand" in turn.calls[0]["result"]["error"]


async def test_sibling_43_grade_cement_is_not_opc_53() -> None:
    turn, _ = await _run([[_receipt(CEMENT, "43 grade cement", "50 bags 43 grade cement")], "?"], "50 bag 43 grade cement")
    assert turn.pending == []


async def test_guard_an_exact_name_or_a_learned_alias_saves_with_no_question() -> None:
    for material, said in ((PAINT, "paint"), (TMT, "kambi"), (CEMENT, "സിമൻറ്"), (CEMENT, "cement")):
        turn, _ = await _run([[_receipt(material, said, f"40 {said}")], "Ready."], f"40 {said} vannu")
        assert [e.tool for e in turn.pending] == ["record_receipt"], said
        assert turn.options == []


async def test_guard_a_word_that_is_another_material_in_the_list_takes_that_one() -> None:
    catalog = [*CATALOG, {"id": WIRE, "name": "Binding wire", "aliases": []}]
    turn, _ = await _run([[_receipt(TMT, "binding wire", "10 kg binding wire")], "Ready."], "10 kg binding wire",
                         catalog=catalog)
    assert turn.pending[0].body["material_id"] == WIRE


def test_a_word_shared_by_two_materials_is_neither() -> None:
    rows = [{"id": "a", "name": "M-Sand"}, {"id": "b", "name": "P-Sand"}]
    assert not is_material("sand", rows[0], rows)
    assert is_material("m sand", rows[0], rows)


def test_the_ready_sentence_loses_a_copied_line_and_its_stray_bracket() -> None:
    line = "2 drum (40 litres) Paint Green Villa, Kakkanad സൈറ്റിൽ ലഭിച്ചു"
    words = f"2 drum primer ലഭിച്ചു. (നിങ്ങൾ സേവ് ചെയ്യുമ്പോൾ: {line})"
    assert without_copied_lines(words, [line]) == "2 drum primer ലഭിച്ചു."
    assert without_copied_lines("Ready, tap Save.", [line]) == "Ready, tap Save."
