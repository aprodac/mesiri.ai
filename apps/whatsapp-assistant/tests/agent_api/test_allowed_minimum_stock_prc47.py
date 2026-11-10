"""PRC-47: minimum stock on WhatsApp -- the Stock page's own routes as tools.

"set minimum cement at Villa 100 bags" holds a minimum for that site and material (source fixed to whatsapp), never a
request or a delivery. Sibling: "what is below minimum?" reads `below_minimum` at once (a GET, nothing held). Guards:
the tools exist on the real API with the fields the model fills (``source`` hidden); the SOP keeps a minimum apart
from a request, an order and a delivery, and "need 200 bags by Friday" stays `ask_for_material`.
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


class Level(BaseModel):
    site_id: str
    material_id: str
    min_qty: float
    reorder_qty: float | None = None
    unit_id: str | None = None
    source: str = "typed"


def _app() -> FastAPI:
    app = FastAPI()

    @app.put("/materials/stock-levels")
    async def set_level(body: Level, jwt: dict = Depends(get_current_user)):
        return {"id": str(uuid.uuid4()), "said": "Minimum 100 bags of Cement at Villa"}

    @app.get("/materials/stock-levels/below")
    async def below(site_id: str | None = None, jwt: dict = Depends(get_current_user)):
        return {"items": [{"material": "Cement", "closing": "40", "min_qty": "100", "to_order": "160",
                           "covered_by": None}], "total": 1, "not_covered": 1, "sites": []}

    return app


async def _turn(script: list, said: str, names: tuple[str, ...]):
    app = _app()
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in names))
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, said)
    finally:
        await client.close()


async def test_set_minimum_cement_holds_a_minimum_for_that_site() -> None:
    said = "set minimum cement at Villa 100 bags"
    turn = await _turn([[("set_minimum_stock", {"site_id": SITE, "material_id": CEMENT, "min_qty": 100,
                                                CONFIRM_ARG: said})], "Ready."], said, ("set_minimum_stock",))
    assert turn.pending, turn.calls
    held = turn.pending[0]
    assert (held.method, held.path) == ("PUT", "/materials/stock-levels")
    assert held.body["source"] == "whatsapp" and held.body["min_qty"] == 100 and held.body["site_id"] == SITE


async def test_sibling_what_is_below_minimum_is_read_at_once() -> None:
    turn = await _turn([[("below_minimum", {})], "Cement: 40 of 100 bags, order 160."], "what is below minimum?",
                       ("below_minimum",))
    assert not turn.pending
    looked = next(c for c in turn.calls if c["tool"] == "below_minimum")
    assert looked["result"]["status"] == 200 and '"to_order": "160"' in looked["result"]["result"]  # read by the model


def test_the_minimum_tools_are_on_the_real_api() -> None:
    tools = _real_tools()
    assert {"below_minimum", "minimum_stock", "suggest_minimum_stock", "set_minimum_stock"} <= set(tools)
    write = tools["set_minimum_stock"]
    assert write.is_write and (write.method, write.path) == ("PUT", "/materials/stock-levels")
    assert {"site_id", "material_id", "min_qty", "reorder_qty", "unit_id"} <= set(write.body_fields)
    assert "source" not in write.body_fields
    assert not tools["below_minimum"].is_write and not tools["suggest_minimum_stock"].is_write


def test_guard_a_minimum_is_never_a_request_and_a_need_stays_a_request() -> None:
    sop = (Path(__file__).resolve().parents[2] / "src" / "agent_api" / "SOP.md").read_text(encoding="utf-8")
    assert "`set_minimum_stock` for that site and material" in sop
    assert "never a request, an order or a delivery" in sop
    assert "Material a site NEEDS" in sop and "is\n   `ask_for_material`" in sop
