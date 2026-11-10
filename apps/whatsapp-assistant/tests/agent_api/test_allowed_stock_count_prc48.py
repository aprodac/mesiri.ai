"""PRC-48: "count: cement 92 bags" fills the site's open stock count -- the count page's own routes as tools.

The message holds a count line on the open count, said by its number (PRC-32's rule). Sibling: "start a count at
Block A" holds starting one. Guards: the tools exist on the real API; the SOP never takes a count for a delivery or
a use.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.replaykit import _real_tools
from tests.agent_api.standin import ACTOR, CEMENT, SITE

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

SC = str(uuid.uuid4())


class Line(BaseModel):
    material_id: str
    counted: float | None = None


class Lines(BaseModel):
    lines: list[Line]


class Start(BaseModel):
    site_id: str
    scope: str = "all"


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/materials/stock-counts")
    async def counts(status: str | None = None, jwt: dict = Depends(get_current_user)):
        return {"items": [{"id": SC, "number": 1, "ref": "SC-0001"}], "total": 1}

    @app.post("/materials/stock-counts", status_code=201)
    async def start(body: Start, jwt: dict = Depends(get_current_user)):
        return {"id": SC}

    @app.put("/materials/stock-counts/{count_id}/lines")
    async def lines(count_id: uuid.UUID, body: Lines, jwt: dict = Depends(get_current_user)):
        return {"id": str(count_id)}

    return app


async def _held(tool: str, args: dict, said: str):
    app = _app()
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in ("stock_counts", tool)))
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(FakeToolCallingProvider([[(tool, {**args, CONFIRM_ARG: said})], "Ready."]), tools).run(
            client, said)
    finally:
        await client.close()
    assert turn.pending, turn.calls
    return turn.pending[0]


async def test_count_cement_92_bags_fills_the_open_count() -> None:
    held = await _held("count_stock", {"count_id": "SC-0001", "lines": [{"material_id": CEMENT, "counted": 92}]},
                       "count: cement 92 bags")
    assert (held.method, held.path) == ("PUT", f"/materials/stock-counts/{SC}/lines")
    assert held.body["lines"][0]["counted"] == 92


async def test_sibling_start_a_count_at_a_site() -> None:
    held = await _held("start_stock_count", {"site_id": SITE}, "start a stock count at Block A")
    assert (held.method, held.path) == ("POST", "/materials/stock-counts") and held.body["site_id"] == SITE


def test_the_count_tools_are_on_the_real_api() -> None:
    tools = _real_tools()
    assert {"stock_counts", "start_stock_count", "count_stock"} <= set(tools)
    assert {"lines"} <= set(tools["count_stock"].body_fields)
    assert {"site_id", "scope", "category_id"} <= set(tools["start_stock_count"].body_fields)


def test_guard_a_count_is_never_a_delivery_or_a_use() -> None:
    sop = (Path(__file__).resolve().parents[2] / "src" / "agent_api" / "SOP.md").read_text(encoding="utf-8")
    assert "`count_stock` on the" in sop and "never a delivery, a use or an adjustment" in sop
