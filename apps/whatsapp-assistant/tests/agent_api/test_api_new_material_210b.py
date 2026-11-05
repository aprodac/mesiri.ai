"""[217], follow-up to [210] (Mesiri Test Builders, 3 Nov ~16:25-16:35 IST): "2 drum primer vannu" -> "➕ Add Primer"
-> "20 litre" -> Save: "✅ Primer added; ❌ 1 drum = 20 litres for Primer: Material not found", and the 2 drums were
never received. Three things: Save ran the unit conversion before the new material existed; the Add branch told the
model the receipt "follows once it is saved", so it was never held; the near-match question came as plain text.

Now a line for a material waiting to be added names it ``new:<name>``; Save adds the material first, then the
settings (conversion, alias) and the lines with its id. (Scripted: the replay of these correlation ids could not
be fetched on the bot server, no control-plane token, as for [210].)
"""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR, PROJECT, SITE

from agent_api.agent import ApiAgent, confirm
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, MATERIAL_SAID, build_tools
from agent_api.whatsapp import without_numbered_lines
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_ai.models import ChatMessage

LITRE, DRUM, TIN = (str(uuid.uuid4()) for _ in range(3))
PAINT = str(uuid.uuid4())
TOOLS = ("record_receipt", "add_material", "set_unit_conversion", "add_material_alias")


class Inflow(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID | None = None
    material_id: str
    unit_id: uuid.UUID
    quantity: float
    occurred_date: str


class NewMaterial(BaseModel):
    name: str
    default_unit_id: uuid.UUID


class Conversion(BaseModel):
    from_unit_id: uuid.UUID
    one_unit_equals: float


class Alias(BaseModel):
    alias: str


class Store:
    """A company with Paint (litres, 1 drum = 20 L already set)."""

    def __init__(self) -> None:
        self.catalog = [{"id": PAINT, "name": "Paint", "aliases": [], "default_unit_id": LITRE}]
        self.conversions = {(PAINT, DRUM): 20.0}
        self.received: list[tuple[str, float]] = []  # (material name, stock units)

    def material(self, material_id: str) -> dict:
        row = next((r for r in self.catalog if r["id"] == material_id), None)
        if row is None:
            raise HTTPException(status_code=404, detail="Material not found")
        return row

    def api(self) -> FastAPI:
        app = FastAPI()

        @app.get("/materials")
        async def materials(search: str | None = None, limit: int = 50, is_active: bool | None = None,
                            jwt: dict = Depends(get_current_user)):
            return {"items": self.catalog, "total": len(self.catalog)}

        @app.get("/materials/units-of-measure")
        async def units(jwt: dict = Depends(get_current_user)):
            return {"items": [{"id": LITRE, "code": "ltr", "display_name": "Litres", "is_active": True},
                              {"id": DRUM, "code": "drum", "display_name": "Drum", "is_active": True},
                              {"id": TIN, "code": "tin", "display_name": "Tin", "is_active": True}]}

        @app.post("/materials", status_code=201)
        async def add(body: NewMaterial, jwt: dict = Depends(get_current_user)):
            if any(r["name"].casefold() == body.name.casefold() for r in self.catalog):
                raise HTTPException(status_code=409, detail=f"{body.name} already exists")
            row = {"id": str(uuid.uuid4()), "name": body.name, "aliases": [], "default_unit_id": str(body.default_unit_id)}
            self.catalog.append(row)
            return row

        @app.put("/materials/{material_id}/unit-conversions")
        async def conversion(material_id: str, body: Conversion, jwt: dict = Depends(get_current_user)):
            self.material(material_id)
            self.conversions[(material_id, str(body.from_unit_id))] = body.one_unit_equals
            return {"ok": True}

        @app.post("/materials/{material_id}/aliases", status_code=201)
        async def alias(material_id: str, body: Alias, jwt: dict = Depends(get_current_user)):
            self.material(material_id)["aliases"].append(body.alias)
            return {"material_id": material_id, "alias": body.alias}

        @app.post("/materials/inflows", status_code=201)
        async def inflow(body: Inflow, jwt: dict = Depends(get_current_user),
                         idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
            row = self.material(body.material_id)
            unit = str(body.unit_id)
            factor = 1.0 if unit == row["default_unit_id"] else self.conversions.get((row["id"], unit))
            if factor is None:
                raise HTTPException(status_code=422, detail="no conversion for this unit")
            self.received.append((row["name"], body.quantity * factor))
            return {"id": str(uuid.uuid4())}

        return app


def _receipt(material: str, said: str, unit: str, quantity: float, line: str) -> tuple[str, dict]:
    return ("record_receipt", {"project_id": PROJECT, "site_id": SITE, "material_id": material, "unit_id": unit,
                               "quantity": quantity, "occurred_date": "2026-11-03", MATERIAL_SAID: said,
                               CONFIRM_ARG: line})


def _add(name: str) -> tuple[str, dict]:
    return ("add_material", {"name": name, "default_unit_id": LITRE, CONFIRM_ARG: f"➕ {name} (new)"})


def _conversion(material: str, unit: str, size: float, line: str) -> tuple[str, dict]:
    return ("set_unit_conversion", {"material_id": material, "from_unit_id": unit, "one_unit_equals": size,
                                    CONFIRM_ARG: line})


async def _turn(store: Store, script: list, text: str, ready: list | None = None, history: list | None = None):  # noqa: ANN202
    app = store.api()
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in TOOLS))
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(
            client, text, ready=ready, history=history)
    finally:
        await client.close()


async def _save(store: Store, pending: list):  # noqa: ANN202
    client = ApiClient(ACTOR, app=store.api())
    try:
        return await confirm(client, pending)
    finally:
        await client.close()


async def test_the_reported_conversation_adds_primer_sets_the_drum_and_receives_40_litres() -> None:
    store = Store()
    # 1. "2 drum primer vannu": the model picks Paint; the code refuses it and says to add Primer, no question.
    # WA-194: the model holds the new material AND the receipt in the same turn: never a blocker.
    second = await _turn(store, [[_receipt(PAINT, "primer", DRUM, 2, "2 drum Paint")],
                                 [_add("Primer"), _receipt("new:Primer", "primer", DRUM, 2, "📥 2 drum Primer · Green Villa")],
                                 "Primer is new: Save adds it to your list."], "2 drum primer vannu")
    assert second.options == []
    assert [e.tool for e in second.pending] == ["add_material", "record_receipt"]
    assert second.pending[1].body["material_id"] == "new:Primer"
    assert "new:Primer" in second.calls[1]["result"]["note"]
    history = [ChatMessage(role="user", text="2 drum primer vannu"), ChatMessage(role="model", text="Primer is new.")]
    # 3. "20 litre": the size, for the material by its name.
    third = await _turn(store, [[_conversion("Primer", DRUM, 20, "1 drum = 20 L")], "Ready."], "20 litre",
                        ready=second.pending, history=history)
    assert [e.tool for e in third.pending] == ["add_material", "record_receipt", "set_unit_conversion"]
    assert third.pending[2].path == "/materials/new:Primer/unit-conversions"
    # 4. Save.
    results = await _save(store, third.pending)
    assert all(r.ok for r in results), [(r.pending.summary, r.body) for r in results]
    primer = next(r for r in store.catalog if r["name"] == "Primer")
    assert store.conversions[(primer["id"], DRUM)] == 20
    assert store.received == [("Primer", 40.0)]  # Paint stock unchanged


async def test_sibling_3_tin_putty_adds_putty_with_1_tin_1_litre_and_the_receipt() -> None:
    store = Store()
    turn = await _turn(store, [[_add("Putty"), _receipt("Putty", "putty", TIN, 3, "📥 3 tin Putty"),
                                _conversion("new:Putty", TIN, 1, "1 tin = 1 L")], "Ready."], "➕ Add Putty",
                       history=[ChatMessage(role="user", text="3 tin putty vannu")])
    assert [e.tool for e in turn.pending] == ["add_material", "record_receipt", "set_unit_conversion"]
    results = await _save(store, turn.pending)
    assert all(r.ok for r in results)
    assert store.received == [("Putty", 3.0)]


async def test_adding_failed_the_dependent_lines_say_why_and_never_material_not_found() -> None:
    store = Store()
    turn = await _turn(store, [[_add("Primer"), _receipt("new:Primer", "primer", DRUM, 2, "2 drum Primer"),
                                _conversion("new:Primer", DRUM, 20, "1 drum = 20 L")], "Ready."], "➕ Add Primer",
                       history=[ChatMessage(role="user", text="2 drum primer vannu")])
    # Someone else added Primer between the card and the Save ([243]: one already listed is refused before it is held).
    store.catalog.append({"id": str(uuid.uuid4()), "name": "Primer", "aliases": [], "default_unit_id": LITRE})
    results = await _save(store, turn.pending)
    assert [r.status for r in results] == [409, 424, 424]
    assert all("Material not found" not in str(r.body) for r in results)
    assert "Primer is not in the material list yet" in results[1].body["detail"]
    assert store.received == []


async def test_guard_2_drum_paint_saves_with_no_question() -> None:
    store = Store()
    turn = await _turn(store, [[_receipt(PAINT, "paint", DRUM, 2, "2 drum Paint")], "Ready."], "2 drum paint vannu")
    assert [e.tool for e in turn.pending] == ["record_receipt"] and turn.options == []
    assert all(r.ok for r in await _save(store, turn.pending))
    assert store.received == [("Paint", 40.0)]


async def test_guard_an_existing_material_with_a_new_conversion_saves_the_conversion_first() -> None:
    store = Store()
    turn = await _turn(store, [[_receipt(PAINT, "paint", TIN, 5, "5 tin Paint"), _conversion(PAINT, TIN, 4, "1 tin = 4 L")],
                               "Ready."], "5 tin paint vannu, 1 tin 4 litre")
    assert all(r.ok for r in await _save(store, turn.pending))
    assert store.received == [("Paint", 20.0)]


def test_the_models_own_numbered_lines_are_cut_when_the_list_is_drawn() -> None:
    assert without_numbered_lines("Njan ippo cheyyunnavayum: 1.\nDrum ethra litres?") == "Drum ethra litres?"
    words = "Sheri. Ready aakki: 1.2. 1 drum = 20 litres\n3. 2 drum Primer Green Villa site-il vannu\nSave tap cheyyu."
    assert without_numbered_lines(words) == "Sheri.\nSave tap cheyyu."
    assert without_numbered_lines("20.5 kg vannu. 1 drum = 20 L.") == "20.5 kg vannu. 1 drum = 20 L."
