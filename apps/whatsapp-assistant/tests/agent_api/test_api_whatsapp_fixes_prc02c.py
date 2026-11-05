"""PRC-02c and [248] follow-up (5 Nov): what New India's owner needs to put right, from WhatsApp itself.

1. Categories: "set up categories" (an admin or a project manager, as on the dashboard) and "what categories do I
   have" are tools; a site engineer is told to ask their admin.
2. A corrected size ("1 load M-sand is 3 cum", after 60 was saved) changes lines from now on; the receipts already
   saved with the old size are named for the model, which offers to redo them in one Save.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.replaykit import _real_tools
from tests.agent_api.standin import ACTOR

from agent_api.agent import ApiAgent, saved_with_old_size
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

M_SAND, LOAD, CUM = (str(uuid.uuid4()) for _ in range(3))
LIVE, TAKEN_BACK, OTHER = (str(uuid.uuid4()) for _ in range(3))
TODAY = dt.date.today().isoformat()


class _Size(BaseModel):
    from_unit_id: str
    one_unit_equals: float


def _api(applied: list) -> FastAPI:
    app = FastAPI()

    @app.get("/materials")
    async def materials(limit: int = 50, is_active: bool | None = None, jwt: dict = Depends(get_current_user)):
        return {"items": [{"id": M_SAND, "name": "M Sand", "aliases": [], "default_unit_id": CUM}], "total": 1}

    @app.get("/materials/units-of-measure")
    async def units(jwt: dict = Depends(get_current_user)):
        return {"items": [{"id": LOAD, "code": "load", "display_name": "Loads", "is_active": True},
                          {"id": CUM, "code": "cum", "display_name": "Cubic Meters", "is_active": True}]}

    @app.get("/materials/{material_id}/unit-check")
    async def unit_check(material_id: str, unit_id: str, jwt: dict = Depends(get_current_user)):
        return {"material": "M Sand", "unit": "load", "unit_name": "Loads", "stock_unit": "cum",
                "stock_unit_name": "Cubic Meters", "stock_unit_id": CUM, "fits": True, "one_unit_equals": "60"}

    @app.get("/materials/inflows")
    async def inflows(material_id: str | None = None, date_from: str | None = None, limit: int = 50,
                      jwt: dict = Depends(get_current_user)):
        row = {"material_name": "M Sand", "unit": "cum", "occurred_date": TODAY, "supplier": None,
               "reverses_movement_id": None}
        return {"items": [
            {**row, "id": LIVE, "quantity": "60.00", "notes": "reported as 1 Loads", "is_reversed": False},
            {**row, "id": TAKEN_BACK, "quantity": "120.00", "notes": "reported as 2 Loads", "is_reversed": True},
            {**row, "id": OTHER, "quantity": "3.00", "notes": None, "is_reversed": False},  # said in cum: unaffected
        ], "total": 3}

    @app.put("/materials/{material_id}/unit-conversions")
    async def size(material_id: str, body: _Size, jwt: dict = Depends(get_current_user)):
        return {"ok": True}

    @app.get("/materials/categories")
    async def categories(jwt: dict = Depends(get_current_user)):
        return {"items": [], "uncategorised": 22}

    @app.post("/materials/categories/standard")
    async def standard(jwt: dict = Depends(get_current_user)):
        applied.append("standard")
        return {"categories_added": 34, "materials_placed": 19}

    return app


async def _turn(script: list, text: str, *, may_set_sizes: bool = True):  # noqa: ANN202
    applied: list = []
    app = _api(applied)
    names = ("set_unit_conversion", "material_categories", "add_standard_categories")
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in names))
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text, may_set_sizes=may_set_sizes)
        return turn, applied
    finally:
        await client.close()


# -- 1. categories from WhatsApp ----------------------------------------------------------------------------------


def test_the_category_routes_are_tools_on_the_real_api() -> None:
    tools = _real_tools()
    assert not tools["material_categories"].is_write and tools["add_standard_categories"].is_write


async def test_an_admin_sets_up_the_standard_categories_with_one_save() -> None:
    setup = ("add_standard_categories", {CONFIRM_ARG: "Standard categories"})
    turn, _ = await _turn([[setup], "Ready."], "set up categories")
    assert [e.tool for e in turn.pending] == ["add_standard_categories"]


async def test_guard_a_site_engineer_is_told_to_ask_their_admin() -> None:
    setup = ("add_standard_categories", {CONFIRM_ARG: "Standard categories"})
    turn, _ = await _turn([[setup], "Ask your admin."], "set up categories", may_set_sizes=False)
    assert turn.pending == [] and "Only an admin or a project manager" in turn.calls[0]["result"]["error"]


# -- 2. a corrected size names what was saved with the old one ------------------------------------------------------


async def test_the_receipts_saved_with_the_old_size_are_named() -> None:
    client = ApiClient(ACTOR, app=_api([]))
    try:
        told = await saved_with_old_size(client, M_SAND, LOAD)
    finally:
        await client.close()
    assert LIVE in told and "60 cum saved for 1 Loads" in told
    assert TAKEN_BACK not in told and OTHER not in told  # taken back, or not said in loads


async def test_journey_correcting_the_load_size_offers_to_redo_the_60_cum() -> None:
    size = ("set_unit_conversion", {"material_id": M_SAND, "from_unit_id": LOAD, "one_unit_equals": 3,
                                    CONFIRM_ARG: "1 load M-sand = 3 cum"})
    turn, _ = await _turn([[size], "Done. The 60 cum saved earlier used the old size: redo it?"],
                          "1 load M-sand is 3 cum, not 60")
    note = turn.calls[0]["result"]["note"]
    assert "Already SAVED with the old size" in note and LIVE in note
    assert [e.tool for e in turn.pending] == ["set_unit_conversion"]  # nothing redone until they say yes
