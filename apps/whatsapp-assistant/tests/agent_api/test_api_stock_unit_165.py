"""WA-165 (request #cdcdc4, Paraclette, 3 Nov 19:09-19:10 IST): a voice note "4 bags cement and 1 load M-sand came",
site Tower A, Save: cement saved, "❌ 1 load M-sand: എംസാന്റ് is counted in bags in your stock. How many bags is one
load?", in English, with Save offered again; the second Save was refused the same way. The person was stuck.

Root cause: (1) nothing checked a line's unit against the material's stock unit before Save, so the question came
after the list said "ready"; (2) after that refusal the card offered a Save that could not work; (3) the language
was re-read from every message with no fallback, so the tap "Tower A" made the next line English.

Fix: the API says whether a unit can be recorded for a material (``GET /materials/{id}/unit-check``, the decision
saving makes); the code asks it before a line is held (new line or a correction); after a size refusal at Save only
Cancel is offered and the size question is the open one; a message that does not tell its language keeps theirs.
Scripted: the voice note's transcript is not stored (inbound ``body_text`` is empty for voice), so the reported
words are paraphrased from the reply.
"""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR, ORG, PROJECT, SITE, USER
from tests.agent_api.test_api_whatsapp_119 import CTX, FakeRedis, _message

from agent_api import whatsapp as wa
from agent_api.agent import ApiAgent, PendingWrite, confirm
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, MATERIAL_SAID, build_tools
from agent_api.units import is_stock_unit_refusal
from mesiri_ai.fakes import FakeToolCallingProvider

BAG, LOAD, KG, NOS, CFT = (str(uuid.uuid4()) for _ in range(5))
MSAND, CEMENT, TMT = (str(uuid.uuid4()) for _ in range(3))
TOOLS = ("record_receipt", "set_unit_conversion")
UNITS = {BAG: ("bags", "Bags"), LOAD: ("load", "Loads"), KG: ("kg", "Kilograms"), NOS: ("nos", "Numbers"),
         CFT: ("cft", "Cubic Feet")}


class Inflow(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID | None = None
    material_id: uuid.UUID
    unit_id: uuid.UUID
    quantity: float
    occurred_date: str
    notes: str | None = None
    unit_cost: float | None = None


class Conversion(BaseModel):
    from_unit_id: uuid.UUID
    one_unit_equals: float


class NewMaterial(BaseModel):
    name: str
    default_unit_id: uuid.UUID


class Store:
    """Paraclette's shape: M-sand and cement counted in bags, TMT in kg with 1 bar (nos) = 10.67 kg already set."""

    def __init__(self) -> None:
        self.catalog = [{"id": MSAND, "name": "എംസാന്റ്", "aliases": ["msand", "m-sand", "എംസാൻഡ്"],
                         "default_unit_id": BAG},
                        {"id": CEMENT, "name": "Cement", "aliases": ["സിമന്റ്"], "default_unit_id": BAG},
                        {"id": TMT, "name": "TMT 12mm", "aliases": [], "default_unit_id": KG}]
        self.one_unit: dict[tuple[str, str], float] = {(TMT, NOS): 10.67}  # stock units in ONE of the unit
        self.received: list[tuple[str, float]] = []
        self.notes: list[str | None] = []
        self.checks = 0
        self.size_requests: list[dict] = []  # WA-168

    def row(self, material_id: str) -> dict:
        found = next((r for r in self.catalog if r["id"] == material_id), None)
        if found is None:
            raise HTTPException(status_code=404, detail="Material not found")
        return found

    def factor(self, material_id: str, unit_id: str) -> float | None:
        row = self.row(material_id)
        return 1.0 if unit_id == row["default_unit_id"] else self.one_unit.get((material_id, unit_id))

    def api(self) -> FastAPI:
        from mesiri.domains.shared.auth import get_current_user

        app = FastAPI()

        @app.get("/materials")
        async def materials(search: str | None = None, limit: int = 50, is_active: bool | None = None,
                            jwt: dict = Depends(get_current_user)):
            return {"items": self.catalog, "total": len(self.catalog)}

        @app.get("/materials/units-of-measure")
        async def units(jwt: dict = Depends(get_current_user)):
            return {"items": [{"id": i, "code": c, "display_name": n, "is_active": True} for i, (c, n) in UNITS.items()]}

        @app.get("/materials/{material_id}/unit-check")
        async def unit_check(material_id: str, unit_id: str, jwt: dict = Depends(get_current_user)):
            self.checks += 1
            row, per = self.row(material_id), self.factor(material_id, unit_id)
            stock = UNITS[row["default_unit_id"]]
            return {"material": row["name"], "unit": UNITS[unit_id][0], "unit_name": UNITS[unit_id][1],
                    "stock_unit": stock[0], "stock_unit_name": stock[1], "stock_unit_id": row["default_unit_id"],
                    "fits": per is not None,
                    "one_unit_equals": None if per is None else str(per)}

        @app.get("/materials/size-requests")
        async def size_requests(status: str | None = "open", jwt: dict = Depends(get_current_user)):
            return {"items": [r for r in self.size_requests if r["status"] == status]}

        @app.post("/materials/size-requests", status_code=201)
        async def open_size(body: dict, jwt: dict = Depends(get_current_user)):
            request = next((r for r in self.size_requests if r["status"] == "open" and r["material_id"] ==
                            body["material_id"] and r["from_unit_id"] == body["from_unit_id"]), None)
            if request is None:
                request = {"id": str(uuid.uuid4()), "material_id": body["material_id"], "status": "open",
                           "from_unit_id": body["from_unit_id"], "held_lines": [], "proposed_one_unit_equals": None}
                self.size_requests.append(request)
            if body.get("one_unit_equals"):
                request["proposed_one_unit_equals"] = str(body["one_unit_equals"])
            if body.get("line_body"):
                request["held_lines"].append({"path": body["line_path"], "body": body["line_body"],
                                              "summary": body["line_summary"], "key": body.get("line_key")})
            return request

        @app.post("/materials/size-requests/{request_id}/answer")
        async def answer_size(request_id: str, body: dict, jwt: dict = Depends(get_current_user)):
            if jwt.get("role") not in ("ADMIN", "PROJECT_MANAGER"):
                raise HTTPException(status_code=403, detail="Only an admin or a project manager can set a size.")
            request = next(r for r in self.size_requests if r["id"] == request_id)
            request["status"] = "answered"
            self.one_unit[(request["material_id"], request["from_unit_id"])] = float(body["one_unit_equals"])
            for line in request["held_lines"]:
                per = self.factor(line["body"]["material_id"], line["body"]["unit_id"])
                self.received.append((self.row(line["body"]["material_id"])["name"], line["body"]["quantity"] * per))
            return {"message": f"1 load = {body['one_unit_equals']}, for the whole company. "
                               f"{len(request['held_lines'])} of {len(request['held_lines'])} waiting lines saved."}

        @app.post("/materials", status_code=201)
        async def add(body: NewMaterial, jwt: dict = Depends(get_current_user)):
            row = {"id": str(uuid.uuid4()), "name": body.name, "aliases": [], "default_unit_id": str(body.default_unit_id)}
            self.catalog.append(row)
            return row

        @app.put("/materials/{material_id}/unit-conversions")
        async def conversion(material_id: str, body: Conversion, jwt: dict = Depends(get_current_user)):
            self.row(material_id)
            self.one_unit[(material_id, str(body.from_unit_id))] = body.one_unit_equals
            return {"ok": True}

        @app.post("/materials/inflows", status_code=201)
        async def inflow(body: Inflow, jwt: dict = Depends(get_current_user),
                         idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
            row = self.row(str(body.material_id))
            per = self.factor(row["id"], str(body.unit_id))
            if per is None:  # the backend's own words (materials/router.py)
                stock = UNITS[row["default_unit_id"]][0]
                raise HTTPException(status_code=422, detail=(
                    f"unit_id does not match {row['name']}'s Stock Unit (expected {stock}); no conversion from "
                    f"{UNITS[str(body.unit_id)][1]} is set (PUT /materials/{row['id']}/unit-conversions sets one)"))
            self.received.append((row["name"], body.quantity * per))
            self.notes.append(body.notes)
            return {"id": str(uuid.uuid4())}

        return app


def _receipt(material: str, said: str, unit: str, quantity: float, line: str) -> tuple[str, dict]:
    return ("record_receipt", {"project_id": PROJECT, "site_id": SITE, "material_id": material, "unit_id": unit,
                               "quantity": quantity, "occurred_date": "2026-11-03", MATERIAL_SAID: said,
                               CONFIRM_ARG: line})


def _conversion(material: str, unit: str, size: float) -> tuple[str, dict]:
    return ("set_unit_conversion", {"material_id": material, "from_unit_id": unit, "one_unit_equals": size,
                                    CONFIRM_ARG: f"1 load = {size:g} bags"})


async def _turn(store: Store, script: list, text: str, ready: list | None = None) -> Any:
    app = store.api()
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in TOOLS))
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text, ready=ready)
    finally:
        await client.close()


async def _save(store: Store, pending: list) -> Any:
    client = ApiClient(ACTOR, app=store.api())
    try:
        return await confirm(client, pending)
    finally:
        await client.close()


CEMENT_LINE = _receipt(CEMENT, "സിമന്റ്", BAG, 4, "4 ചാക്ക് സിമന്റ് Tower A-ൽ എത്തിച്ചു.")
MSAND_LINE = _receipt(MSAND, "എംസാൻഡ്", LOAD, 1, "1 ലോഡ് എംസാൻഡ് Tower A-ൽ എത്തിച്ചു.")
SAID = "4 ചാക്ക് സിമന്റും 1 ലോഡ് എംസാൻഡും Tower A-ൽ എത്തിച്ചു"


# -- the reported conversation ---------------------------------------------------------------------------------------


async def test_the_load_of_msand_is_held_with_its_size_asked_beside_it() -> None:
    # WA-197: never a blocker: the M-sand line is on the list (size unknown) and the size is asked in the same reply.
    store = Store()
    turn = await _turn(store, [[CEMENT_LINE, MSAND_LINE],
                               [("ask", {"question": "ഒരു ലോഡ് എംസാന്റ് എത്ര ചാക്ക് ആണ്?"})],
                               "സിമന്റ് തയ്യാർ. ഒരു ലോഡ് എംസാന്റ് എത്ര ചാക്ക് ആണ്?"], SAID)
    assert [e.summary for e in turn.pending] == ["4 ചാക്ക് സിമന്റ് Tower A-ൽ എത്തിച്ചു.",
                                                 "1 ലോഡ് എംസാൻഡ് Tower A-ൽ എത്തിച്ചു. (1 Loads = ? Bags)"]
    note = turn.calls[1]["result"]["note"]
    assert "counted in Bags" in note and "ONLY `set_unit_conversion`" in note and "tap Save" in note
    assert turn.question.endswith("ആണ്?") and turn.size_needed[0]["key"] == turn.pending[1].idempotency_key


async def test_the_answer_holds_the_size_and_the_load_and_one_save_records_60_bags() -> None:
    store = Store()
    first = await _turn(store, [[CEMENT_LINE, MSAND_LINE], "ഒരു ലോഡ് എത്ര ചാക്ക്?"], SAID)
    second = await _turn(store, [[_conversion(MSAND, LOAD, 60)], "തയ്യാർ."], "60 ചാക്ക്", ready=first.pending)
    # WA-197: the waiting line converts with the size; it is never prepared a second time.
    assert [e.tool for e in second.pending] == ["record_receipt", "record_receipt", "set_unit_conversion"]
    assert second.pending[1].summary == "1 ലോഡ് എംസാൻഡ് Tower A-ൽ എത്തിച്ചു. (= 60 Bags)"
    assert second.size_needed == []
    results = await _save(store, second.pending)
    assert all(r.ok for r in results), [(r.pending.summary, r.body) for r in results]
    assert sorted(store.received) == sorted([("Cement", 4.0), ("എംസാന്റ്", 60.0)])


# -- siblings ------------------------------------------------------------------------------------------------------


async def test_sibling_a_correction_to_loads_is_made_and_its_size_asked() -> None:
    # WA-197: the correction goes through (it is what they said); the size is asked beside it, not instead of it.
    store = Store()
    first = await _turn(store, [[_receipt(MSAND, "msand", BAG, 40, "40 bags msand")], "Ready."], "40 bag msand vannu")
    second = await _turn(store, [[("change_ready_entry", {"number": 1, "changes": [{"field": "unit_id", "value": LOAD}],
                                                          "confirm_line": "1 load msand"})], "Ok."],
                         "alla, 1 load aanu", ready=first.pending)
    assert "ONLY `set_unit_conversion`" in second.calls[0]["result"]["size"]
    assert second.pending[0].summary == "1 load msand (1 Loads = ? Bags)" and second.pending[0].body["unit_id"] == LOAD
    assert second.size_needed[0]["key"] == second.pending[0].idempotency_key


async def test_sibling_the_conversion_names_its_unit_in_words_and_saves_with_its_id() -> None:
    store = Store()
    turn = await _turn(store, [[("set_unit_conversion", {"material_id": MSAND, "from_unit_id": "load",
                                                         "one_unit_equals": 60, CONFIRM_ARG: "1 load = 60 bags"})],
                               "Ready."], "oru load 60 chaakku")
    assert turn.pending[0].body["from_unit_id"] == LOAD
    assert all(r.ok for r in await _save(store, turn.pending))
    assert store.one_unit[(MSAND, LOAD)] == 60


def test_sibling_only_a_missing_conversion_counts_as_a_size_refusal() -> None:
    reason = ("unit_id does not match എംസാന്റ്'s Stock Unit (expected bags); no conversion from Loads is set "
              "(PUT /materials/x/unit-conversions sets one)")
    assert is_stock_unit_refusal(reason)
    assert not is_stock_unit_refusal("Not authorized for this site")
    assert not is_stock_unit_refusal("unit_id is not a valid active unit")


# -- guards: what must not change ------------------------------------------------------------------------------------


async def test_guard_a_known_conversion_and_the_stock_unit_go_straight_through() -> None:
    store = Store()
    turn = await _turn(store, [[_receipt(TMT, "tmt", NOS, 10, "10 TMT bars"), CEMENT_LINE], "Ready."], "10 tmt 4 bag cement")
    assert len(turn.pending) == 2 and store.checks == 2
    assert all(r.ok for r in await _save(store, turn.pending))


async def test_guard_an_api_that_cannot_answer_leaves_the_decision_to_save() -> None:
    store = Store()
    app = store.api()
    app.router.routes = [r for r in app.router.routes if "unit-check" not in getattr(r, "path", "")]
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in TOOLS))
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(FakeToolCallingProvider([[MSAND_LINE], "Ready."]), tools).run(client, SAID)
    finally:
        await client.close()
    assert len(turn.pending) == 1  # held as before; Save's own check decides


def test_guard_a_message_in_its_own_language_still_sets_it() -> None:
    assert wa._language("Tower A", "malayalam") == "malayalam"
    assert wa._language("Main Block", "manglish") == "manglish"
    assert wa._language("50 bag cement vannu", "english") == "manglish"
    assert wa._language("ഇന്ന് 200 ഇഷ്ടിക വന്നു", "english") == "malayalam"
    assert wa._language("how much cement is left?", "malayalam") == "english"


# -- end to end through WhatsApp: the Save tap ---------------------------------------------------------------------


class Harness:
    def __init__(self, store: Store, model: Any) -> None:
        from unittest.mock import AsyncMock

        self.sent: list = []
        self.redis = FakeRedis()

        async def send(spec: Any, wa_id: str) -> None:
            self.sent.append(spec)

        self.service = wa.ApiWhatsApp(provider=model, database=None, redis=self.redis, send=send, transcribe=None,
                                      message_logger=AsyncMock(), trace_logger=AsyncMock(), app=store.api())

    async def hold(self, *lines: tuple[str, dict], language: str = "malayalam") -> None:
        entries = [PendingWrite("record_receipt", "POST", "/materials/inflows", {},
                                {k: v for k, v in args.items() if k not in (CONFIRM_ARG, MATERIAL_SAID)},
                                args[CONFIRM_ARG], f"k{i}") for i, (_, args) in enumerate(lines)]
        await self.redis.set_json(f"agent_api:{ORG}:{USER}", {
            "pending": [e.to_json() for e in entries], "batch": "b1", "pending_at": time.time(), "language": language})

    async def state(self) -> dict:
        return await self.redis.get_json(f"agent_api:{ORG}:{USER}")


@pytest.fixture(autouse=True)
def _tools(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(openapi, tuple(a for a in ALLOWED if a.name in TOOLS)))


async def test_the_reported_save_saves_the_cement_and_holds_the_msand_for_the_admin_in_malayalam() -> None:
    # WA-197: Save is never stuck: the line with no size goes to the admin (it saves itself when they answer).
    store = Store()
    h = Harness(store, FakeToolCallingProvider(["Ok."]))
    await h.hold(CEMENT_LINE, MSAND_LINE)
    await h.service.handle(_message("Save", tap="apiag:save:b1"), CTX)
    reply = h.sent[-1]
    assert store.received == [("Cement", 4.0)]
    assert "മാറ്റിവെച്ചു: 1 ലോഡ് എംസാൻഡ് Tower A-ൽ എത്തിച്ചു. സൈസ്" in reply.text  # their language, one full stop
    assert "Not everything" not in reply.text and not reply.buttons
    assert (await h.state())["pending"] == []
    assert [line["summary"] for line in store.size_requests[0]["held_lines"]] == [MSAND_LINE[1][CONFIRM_ARG]]


async def test_sibling_a_save_with_another_refusal_drops_that_line_and_says_so() -> None:  # [233]
    store = Store()
    h = Harness(store, FakeToolCallingProvider(["Ok."]))
    await h.hold(MSAND_LINE, _receipt(str(uuid.uuid4()), "x", BAG, 1, "1 bag of something gone"))
    await h.service.handle(_message("Save", tap="apiag:save:b1"), CTX)
    # the other line is taken off and said so; the M-sand line is held for the admin (WA-197)
    assert "Not everything could be saved" in h.sent[-1].text and len(store.size_requests[0]["held_lines"]) == 1
    assert (await h.state())["pending"] == []


async def test_the_tapped_site_name_keeps_their_language() -> None:
    store = Store()
    h = Harness(store, FakeToolCallingProvider(["ശരി."]))
    await h.hold(CEMENT_LINE)
    await h.service.handle(_message("Tower A"), SimpleNamespace(**{**vars(CTX)}))
    assert (await h.state())["language"] == "malayalam"
