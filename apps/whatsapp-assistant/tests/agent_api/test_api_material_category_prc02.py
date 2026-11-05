"""PRC-02: a new material added from WhatsApp goes into one of the company's own categories, shown on the Save card.

The model reads the whole name and says the category in words ("Stainless steel sink" is sanitaryware, not steel);
the API (``GET /materials/categories/suggest``) takes that first, then the name alone when it settles it. A category
that is not theirs: the model gets their own list once (renamed / added categories), then "none" or one of them. The
id is never the model's guess (``category_id`` stays hidden). A waiting material that is renamed gets its category
again; a category switched off before Save saves the material without it; "put it in Plumbing" moves a listed one.
Journey: their words -> card line with "📂 Main › Sub" -> Save -> what the API got."""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR

from agent_api.agent import CATEGORY_REFUSAL, ApiAgent, confirm
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.materials.categories import suggest
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

UNIT, MATERIAL = str(uuid.uuid4()), str(uuid.uuid4())
ELECTRICAL, MCB, PLUMBING, PIPES, SANITARY = (str(uuid.uuid4()) for _ in range(5))


def _tree() -> list[dict]:
    return [{"id": ELECTRICAL, "name": "Electrical", "parent_id": None, "is_active": True},
            {"id": MCB, "name": "DB & MCBs", "parent_id": ELECTRICAL, "is_active": True},
            {"id": PLUMBING, "name": "Plumbing & CP", "parent_id": None, "is_active": True},
            {"id": PIPES, "name": "Pipes", "parent_id": PLUMBING, "is_active": True},
            {"id": SANITARY, "name": "Sanitaryware", "parent_id": PLUMBING, "is_active": True}]


class _New(BaseModel):
    name: str
    default_unit_id: str | None = None
    category: str | None = None
    category_id: uuid.UUID | None = None


class _Change(BaseModel):
    name: str | None = None
    category: str | None = None
    category_id: uuid.UUID | None = None


def _api(saved: list, tree: list[dict]) -> FastAPI:
    app = FastAPI()

    def _check(category_id: uuid.UUID | None) -> None:
        if category_id and not any(c["id"] == str(category_id) and c["is_active"] for c in tree):
            raise HTTPException(status_code=422, detail=CATEGORY_REFUSAL)

    @app.get("/materials")
    async def materials(limit: int = 50, is_active: bool | None = None, jwt: dict = Depends(get_current_user)):
        return {"items": [{"id": MATERIAL, "name": "Kitchen sink", "aliases": []}], "total": 1}

    @app.get("/materials/units-of-measure")
    async def units(jwt: dict = Depends(get_current_user)):
        return {"items": [{"id": UNIT, "code": "nos", "display_name": "Nos", "is_active": True}]}

    @app.get("/materials/categories")
    async def categories(jwt: dict = Depends(get_current_user)):
        return {"items": tree, "uncategorised": 0}

    @app.get("/materials/categories/suggest")
    async def suggestion(name: str | None = None, hint: str | None = None, jwt: dict = Depends(get_current_user)):
        return suggest(tree, name, hint)  # the backend's own decision

    @app.post("/materials", status_code=201)
    async def new(body: _New, jwt: dict = Depends(get_current_user)):
        _check(body.category_id)
        saved.append(("new", body.model_dump()))
        return {"id": str(uuid.uuid4())}

    @app.patch("/materials/{material_id}")
    async def change(material_id: str, body: _Change, jwt: dict = Depends(get_current_user)):
        _check(body.category_id)
        saved.append(("change", body.model_dump(exclude_unset=True)))
        return {"id": material_id}

    return app


async def _run(script: list, tree: list[dict] | None = None, *, ready: list | None = None,
               off_before_save: bool = False) -> tuple:
    saved: list = []
    tree = _tree() if tree is None else tree
    app = _api(saved, tree)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in ("add_material", "update_material")))
    for name in ("add_material", "update_material"):
        assert "category_id" not in tools[name].spec.parameters["properties"]  # never the model's guess
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(FakeToolCallingProvider(script), tools).run(client, "material", ready=ready)
        if off_before_save:
            for c in tree:
                c["is_active"] = False
        results = await confirm(client, turn.pending) if turn.pending else []
        return turn, saved, results
    finally:
        await client.close()


def _add(name: str, category: str | None = None) -> tuple[str, dict]:
    body = {"name": name, "default_unit_id": UNIT, CONFIRM_ARG: f"New: {name}"}
    return "add_material", ({**body, "category": category} if category else body)


async def test_whole_journey_a_name_that_settles_it_goes_in_and_the_card_says_so() -> None:
    turn, saved, results = await _run([[_add("MCB 32A")], "Ready."])
    assert turn.pending[0].summary.endswith("📂 Electrical › DB & MCBs") and all(r.ok for r in results)
    assert saved == [("new", {"name": "MCB 32A", "default_unit_id": UNIT, "category": None,
                              "category_id": uuid.UUID(MCB)})]


async def test_loophole_1_the_model_reads_the_whole_name_stainless_steel_sink_is_sanitaryware() -> None:
    turn, saved, _ = await _run([[_add("Stainless steel sink", "Plumbing & CP > Sanitaryware")], "Ready."])
    assert "📂 Plumbing & CP › Sanitaryware" in turn.pending[0].summary
    assert saved[0][1]["category_id"] == uuid.UUID(SANITARY)


async def test_loophole_2_a_category_not_theirs_gets_their_own_list_once() -> None:
    civil = [{"id": ELECTRICAL, "name": "Civil", "parent_id": None, "is_active": True},
             {"id": MCB, "name": "Brickwork", "parent_id": ELECTRICAL, "is_active": True}]
    turn, saved, _ = await _run([[_add("Red bricks", "Structural > Masonry")],
                                 [_add("Red bricks", "Civil > Brickwork")], "Ready."], tree=civil)
    told = turn.calls[0]["result"]["error"]
    assert "Civil > Brickwork" in told and "Never a category that is not in this list" in told
    assert saved[0][1]["category_id"] == uuid.UUID(MCB) and "📂 Civil › Brickwork" in turn.pending[0].summary


async def test_none_fits_after_the_list_added_without_one_and_never_a_third_round() -> None:
    turn, saved, _ = await _run([[_add("Fevicol", "Adhesives")], [_add("Fevicol", "Glue")], "Ready."])
    assert len([c for c in turn.calls if "error" in c["result"]]) == 1
    assert saved[0][1]["category_id"] is None and "📂" not in turn.pending[0].summary
    turn, saved, _ = await _run([[_add("Fevicol", "Adhesives")], [_add("Fevicol", "none")], "Ready."])
    assert saved[0][1]["category"] is None and saved[0][1]["category_id"] is None


async def test_guard_a_company_without_categories_is_unchanged_and_never_asked() -> None:
    turn, saved, _ = await _run([[_add("MCB 32A", "Electrical > DB & MCBs")], "Ready."], tree=[])
    assert not any("error" in c["result"] for c in turn.calls)
    assert saved[0][1]["category_id"] is None and "📂" not in turn.pending[0].summary


async def test_loophole_3_a_category_switched_off_before_save_saves_the_material_without_it() -> None:
    turn, saved, results = await _run([[_add("MCB 32A")], "Ready."], off_before_save=True)
    assert all(r.ok for r in results) and saved[0][1]["category_id"] is None
    assert "📂" not in results[0].pending.summary  # the saved line no longer claims the category


async def test_loophole_4_a_waiting_material_renamed_gets_its_category_again() -> None:
    first, _, _ = await _run([[_add("MCB 32A")], "Ready."])
    rename = ("change_ready_entry", {"number": 1, "changes": [{"field": "name", "value": "Fevicol"}],
                                     "confirm_line": "New: Fevicol"})
    turn, saved, _ = await _run([[rename], "Ready."], ready=first.pending)
    assert "📂" not in turn.pending[0].summary
    assert saved[0][1]["name"] == "Fevicol" and saved[0][1]["category_id"] is None  # never MCB's category
    move = ("change_ready_entry", {"number": 1, "changes": [{"field": "name", "value": "Switches"}],
                                   "confirm_line": "New: Switches"})
    turn, _, _ = await _run([[move], "Ready."], ready=first.pending)
    # this company has no "Switches & sockets": the main category, never the old name's DB & MCBs
    assert turn.pending[0].summary.endswith("📂 Electrical") and "DB & MCBs" not in turn.pending[0].summary


async def test_loophole_6_put_it_in_plumbing_moves_a_listed_material() -> None:
    change = ("update_material", {"material_id": MATERIAL, "category": "Plumbing & CP > Sanitaryware",
                                  CONFIRM_ARG: "Kitchen sink -> Plumbing"})
    turn, saved, results = await _run([[change], "Ready."])
    assert "📂 Plumbing & CP › Sanitaryware" in turn.pending[0].summary and all(r.ok for r in results)
    assert saved == [("change", {"category_id": uuid.UUID(SANITARY)})]


async def test_guard_an_update_without_a_category_never_touches_it() -> None:
    rename = ("update_material", {"material_id": MATERIAL, "name": "Kitchen sink SS", CONFIRM_ARG: "rename"})
    _, saved, _ = await _run([[rename], "Ready."])
    assert saved == [("change", {"name": "Kitchen sink SS"})]
