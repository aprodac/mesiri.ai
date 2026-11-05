"""PRC-17: "previous stock, used, balance" for a period, and "what is running low", answered on WhatsApp.

The client (5 Nov): "if someone asks me how many bags of cement remain at the site, I should get that figure at a
glance, showing previous stock, consumption and the current balance". `stock_summary` gives it for any dates; with
no dates it is the last week, which is also what "running low" is judged on. Guard: a question only reads.
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

CEMENT = str(uuid.uuid4())
ROW = {"material_name": "Cement", "material_id": CEMENT, "unit": "bags", "category": "Structural › Masonry",
       "main_category": "Structural", "opening": "420", "received": "480", "used": "210", "adjusted": "0",
       "closing": "690", "days_left": 23, "running_low": False}
SAND = {**ROW, "material_name": "Sand", "closing": "2", "days_left": 1, "running_low": True}


def _api(asked: list) -> FastAPI:
    app = FastAPI()

    @app.get("/materials/stock-summary")
    async def summary(date_from: str | None = None, date_to: str | None = None, material_id: str | None = None,
                      jwt: dict = Depends(get_current_user)):
        asked.append({"date_from": date_from, "date_to": date_to, "material_id": material_id})
        return [ROW] if material_id == CEMENT else [ROW, SAND]

    return app


async def _turn(script: list, text: str):  # noqa: ANN202
    asked: list = []
    app = _api(asked)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "stock_summary"))
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text)
        return turn, asked
    finally:
        await client.close()


def test_stock_summary_is_a_read_tool_on_the_real_api() -> None:
    tool = _real_tools()["stock_summary"]
    assert not tool.is_write
    assert {"date_from", "date_to", "category_id", "site_id", "material_id"} <= set(tool.query_params)


async def test_previous_stock_used_and_balance_for_this_week() -> None:
    script = [
        [("stock_summary", {"material_id": CEMENT, "date_from": "2026-11-03", "date_to": "2026-11-05"})],
        "Cement: 420 bags before Monday, 480 came, 210 used, *690 bags* now.",
    ]
    turn, asked = await _turn(script, "cement previous stock, used, balance this week?")
    assert asked == [{"date_from": "2026-11-03", "date_to": "2026-11-05", "material_id": CEMENT}]
    row = json.loads(turn.calls[0]["result"]["result"])[0]
    assert (row["opening"], row["received"], row["used"], row["closing"]) == ("420", "480", "210", "690")
    assert turn.pending == []  # a question never prepares anything


async def test_running_low_is_read_from_the_rows() -> None:
    script = [[("stock_summary", {})], "Sand: 2 bags, about 1 day left."]
    turn, asked = await _turn(script, "what is running low?")
    assert asked == [{"date_from": None, "date_to": None, "material_id": None}]  # the API's own last week
    low = [r["material_name"] for r in json.loads(turn.calls[0]["result"]["result"]) if r["running_low"]]
    assert low == ["Sand"]


def test_the_sop_routes_period_and_running_low_questions() -> None:
    from pathlib import Path

    sop = (Path(__file__).resolve().parents[2] / "src" / "agent_api" / "SOP.md").read_text(encoding="utf-8")
    assert "`stock_summary` with those dates" in sop and "the rows with running_low" in sop
