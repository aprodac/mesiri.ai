"""MP-04 (8 Nov 2026): the material plan on WhatsApp through the dashboard's own route.

"What do I need to order?" / "is cement enough for the slab?" only reads `material_plan`, never prepares a save.
Guards: "what to order" no longer goes straight to running-low stock when a plan exists, and the old answer stays
the fallback when there is no plan.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import Depends, FastAPI
from tests.agent_api.replaykit import _real_tools
from tests.agent_api.standin import ACTOR

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.links import PAGES
from agent_api.tools import ALLOWED, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

PROJECT = str(uuid.uuid4())


def _app(read: list) -> FastAPI:
    app = FastAPI()

    @app.get("/projects/{project_id}/material-plan")
    async def material_plan(project_id: str, weeks: int = 8, jwt: dict = Depends(get_current_user)):
        read.append((project_id, weeks))
        return {"weeks": ["2026-11-09"], "materials": [
            {"material": "Cement OPC 53", "unit": "bags", "still_needed": "661.26", "on_hand": "180.000",
             "on_order": "0.000", "short_day": "2026-11-12", "short_by": "481.260", "supplier": "Malabar Traders",
             "lead_days": 4, "order_by": "2026-11-08", "order_now": True}]}

    return app


async def _turn(script: list, text: str):  # noqa: ANN202
    read: list = []
    app = _app(read)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "material_plan"))
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text), read
    finally:
        await client.close()


def test_the_material_plan_tool_is_the_dashboards_route_and_read_only() -> None:
    tool = _real_tools()["material_plan"]
    assert (tool.method, tool.path) == ("GET", "/projects/{project_id}/material-plan")
    assert not tool.is_write
    assert PAGES["material_plan"][0] == "/planning/materials?project={project_id}"


async def test_what_to_order_only_reads_the_plan() -> None:
    turn, read = await _turn([[("material_plan", {"project_id": PROJECT})],
                              "Cement: 482 bags more, short from Thu 12 Nov. Order today (Malabar Traders, 4 days)."],
                             "next week enthokke order cheyyanam?")
    assert read == [(PROJECT, 8)] and turn.pending == []


def test_the_sop_puts_the_plan_first_and_keeps_running_low_as_the_fallback() -> None:
    sop = (Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8")
    assert "call `material_plan` for the project" in sop
    assert '"what to order" is the material plan first (rule 16)' in sop
    # The guard: no plan (no norms, or a role that may not read it) still answers from stock.
    assert "answer from\n   `stock_summary` (running_low) as before" in sop
    assert "Never invent a need, a date or a supplier." in sop
