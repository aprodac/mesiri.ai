"""PRC-02: a new material added from WhatsApp goes into the company's category, shown on the Save card.

The code asks the API (``GET /materials/categories/suggest``, the dashboard's own rule): the name against the standard
list first, then the model's ``category`` in words. The id is never the model's guess (``category_id`` stays hidden).
No category fits, or the company has none: the material is added without one, exactly as before.
Journey: their words -> card line with "📂 Main › Sub" -> Save -> what the API got."""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR

from agent_api.agent import ApiAgent, confirm
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.materials.categories import (
    category_label,
    find_category,
    read_hint,
    suggest_path,
)
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

UNIT = str(uuid.uuid4())
ELECTRICAL, MCB, PLUMBING, PIPES = (str(uuid.uuid4()) for _ in range(4))
TREE = [{"id": ELECTRICAL, "name": "Electrical", "parent_id": None, "is_active": True},
        {"id": MCB, "name": "DB & MCBs", "parent_id": ELECTRICAL, "is_active": True},
        {"id": PLUMBING, "name": "Plumbing & CP", "parent_id": None, "is_active": True},
        {"id": PIPES, "name": "Pipes", "parent_id": PLUMBING, "is_active": True}]


class _New(BaseModel):
    name: str
    default_unit_id: str | None = None
    category: str | None = None
    category_id: uuid.UUID | None = None


def _api(saved: list, tree: list[dict]) -> FastAPI:
    app = FastAPI()

    @app.get("/materials")
    async def materials(limit: int = 50, is_active: bool | None = None, jwt: dict = Depends(get_current_user)):
        return {"items": [], "total": 0}

    @app.get("/materials/units-of-measure")
    async def units(jwt: dict = Depends(get_current_user)):
        return {"items": [{"id": UNIT, "code": "nos", "display_name": "Nos", "is_active": True}]}

    @app.get("/materials/categories/suggest")
    async def suggest(name: str, hint: str | None = None, jwt: dict = Depends(get_current_user)):
        # the backend's own rule functions, on this company's tree
        path = suggest_path(name)
        found, source = (find_category(tree, path), "rule") if path else (None, "")
        if found is None and hint:
            found, source = read_hint(tree, hint), "hint"
        if found is None:
            return {"category_id": None, "label": "", "source": ""}
        return {"category_id": found["id"], "label": category_label(tree, found), "source": source}

    @app.post("/materials", status_code=201)
    async def new(body: _New, jwt: dict = Depends(get_current_user)):
        saved.append(body.model_dump())
        return {"id": str(uuid.uuid4())}

    return app


async def _journey(add: dict, tree: list[dict] = TREE) -> tuple:
    saved: list = []
    app = _api(saved, tree)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "add_material"))
    assert "category_id" not in tools["add_material"].spec.parameters["properties"]  # never the model's guess
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(FakeToolCallingProvider([[("add_material", add)], "Ready."]), tools).run(
            client, "add material")
        results = await confirm(client, turn.pending) if turn.pending else []
        return turn, saved, results
    finally:
        await client.close()


def _add(name: str, category: str | None = None) -> dict:
    body = {"name": name, "default_unit_id": UNIT, CONFIRM_ARG: f"New: {name}"}
    return {**body, "category": category} if category else body


async def test_whole_journey_a_new_mcb_goes_into_electrical_and_the_card_says_so() -> None:
    turn, saved, results = await _journey(_add("MCB 32A"))
    assert turn.pending[0].summary.endswith("📂 Electrical › DB & MCBs")
    assert all(r.ok for r in results)
    assert saved[0]["category_id"] == uuid.UUID(MCB) and saved[0]["category"] is None


async def test_sibling_the_models_words_place_what_the_name_alone_cannot() -> None:
    turn, saved, _ = await _journey(_add("CPVC pipe 1 inch", "Plumbing & CP > Pipes"))  # "pipe": several categories
    assert "📂 Plumbing & CP › Pipes" in turn.pending[0].summary and saved[0]["category_id"] == uuid.UUID(PIPES)


async def test_guard_nothing_fits_added_without_a_category_as_before() -> None:
    turn, saved, _ = await _journey(_add("Fevicol", "Adhesives"))  # not in their list: never created
    assert "📂" not in turn.pending[0].summary
    assert saved[0]["category_id"] is None and saved[0]["category"] == "Adhesives"  # the old text stays as a hint


async def test_guard_a_company_without_categories_is_unchanged() -> None:
    turn, saved, _ = await _journey(_add("MCB 32A"), tree=[])
    assert "📂" not in turn.pending[0].summary and saved[0]["category_id"] is None
