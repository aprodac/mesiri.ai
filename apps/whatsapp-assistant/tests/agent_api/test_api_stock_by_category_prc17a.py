"""PRC-17a (Ilan, 5 Nov: "in messages the categories should come too"): stock answers know the categories.

"Electrical stock?" finds the category with `material_categories`, then asks `stock_levels` for it (a main category
brings its sub-categories); every stock row names its category, so a long answer can be grouped. Guard: a stock
question without a category asks for everything, as before.
"""

from __future__ import annotations

import json
import uuid

from fastapi import Depends, FastAPI
from tests.agent_api.replaykit import _real_tools
from tests.agent_api.standin import ACTOR

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

ELECTRICAL, SWITCHES, STRUCTURAL = (str(uuid.uuid4()) for _ in range(3))
SITE = str(uuid.uuid4())

_ROWS = [
    {"material_name": "2-way switch 6A", "category": "Electrical › Switches & sockets", "main_category": "Electrical",
     "category_id": SWITCHES, "current_stock": "8", "unit": "nos", "site_id": SITE},
    {"material_name": "Cement", "category": "Structural › Masonry", "main_category": "Structural",
     "category_id": STRUCTURAL, "current_stock": "690", "unit": "bags", "site_id": SITE},
]


def _api(asked: list) -> FastAPI:
    app = FastAPI()

    @app.get("/materials/categories")
    async def categories(jwt: dict = Depends(get_current_user)):
        return {"items": [
            {"id": ELECTRICAL, "parent_id": None, "name": "Electrical", "sort_order": 20, "is_active": True,
             "material_count": 1},
            {"id": SWITCHES, "parent_id": ELECTRICAL, "name": "Switches & sockets", "sort_order": 20,
             "is_active": True, "material_count": 1},
            {"id": STRUCTURAL, "parent_id": None, "name": "Structural", "sort_order": 10, "is_active": True,
             "material_count": 1},
        ], "uncategorised": 0}

    @app.get("/materials/inventory")
    async def inventory(category_id: str | None = None, site_id: str | None = None,
                        jwt: dict = Depends(get_current_user)):
        asked.append(category_id)
        if category_id == ELECTRICAL:
            return [r for r in _ROWS if r["main_category"] == "Electrical"]
        return _ROWS

    return app


def _rows(call: dict) -> list[dict]:
    """What the model was shown: the tool result's body."""
    return json.loads(call["result"]["result"])


async def _turn(script: list, text: str):  # noqa: ANN202
    asked: list = []
    app = _api(asked)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in ("material_categories", "stock_levels")))
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text)
        return turn, asked
    finally:
        await client.close()


def test_stock_levels_takes_a_category_on_the_real_api() -> None:
    tool = _real_tools()["stock_levels"]
    assert "category_id" in tool.query_params
    assert "categor" in tool.spec.description.lower()


async def test_electrical_stock_is_asked_by_its_category() -> None:
    script = [
        [("material_categories", {})],
        [("stock_levels", {"category_id": ELECTRICAL})],
        "*Electrical*: 2-way switch 6A 8 nos.",
    ]
    turn, asked = await _turn(script, "electrical stock?")
    assert asked == [ELECTRICAL]
    rows = _rows(turn.calls[-1])
    assert [r["material_name"] for r in rows] == ["2-way switch 6A"]
    assert rows[0]["category"] == "Electrical › Switches & sockets"  # the model can name where it sits
    assert turn.pending == []  # a question never prepares anything


async def test_guard_a_plain_stock_question_still_asks_for_everything() -> None:
    script = [[("stock_levels", {})], "Cement 690 bags; 2-way switch 6A 8 nos."]
    turn, asked = await _turn(script, "what stock is there?")
    assert asked == [None]
    assert {r["main_category"] for r in _rows(turn.calls[-1])} == {"Electrical", "Structural"}


def test_the_sop_says_how_to_answer_by_category() -> None:
    from pathlib import Path

    sop = (Path(__file__).resolve().parents[2] / "src" / "agent_api" / "SOP.md").read_text(encoding="utf-8")
    assert "stock_levels` with its `category_id`" in sop


def test_deliveries_and_use_take_a_category_on_the_real_api() -> None:
    """PRC-17b: the same filter on list_receipts / list_usage."""
    tools = _real_tools()
    for name in ("list_receipts", "list_usage"):
        assert "category_id" in tools[name].query_params
        assert "categor" in tools[name].spec.description.lower()
