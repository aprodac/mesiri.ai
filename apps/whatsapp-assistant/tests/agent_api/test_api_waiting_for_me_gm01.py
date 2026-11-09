"""GM-01 (9 Nov 2026): "what is waiting for me?" on WhatsApp through the dashboard's own route.

It only reads `waiting_for_me` (never prepares a save); deciding stays each module's own tool. Guards: the old
"my requests" (what I asked for) is not this, and work to confirm / RA bills are never said done in chat.
"""

from __future__ import annotations

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


def _app(read: list) -> FastAPI:
    app = FastAPI()

    @app.get("/approvals/inbox")
    async def inbox(project_id: str | None = None, kind: str | None = None, jwt: dict = Depends(get_current_user)):
        read.append((project_id, kind))
        return {"items": [{"kind": "subcontract_bill", "id": "b1", "ref": "RA-3", "title": "Sreedhar team · RA-3 on WO-0007",
                           "project_name": "Marina Heights", "site_name": "Tower A", "flagged": True, "group": "flagged",
                           "fact": "Billed 220 sqm more than measured on Plastering · ₹50,600 at risk", "amount": "271400.00"}],
                "counts": {"total": 1, "flagged": 1}}

    return app


async def _turn(script: list, text: str):  # noqa: ANN202
    read: list = []
    app = _app(read)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "waiting_for_me"))
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text), read
    finally:
        await client.close()


def test_the_tool_is_the_dashboards_route_read_only_with_a_page() -> None:
    tool = _real_tools()["waiting_for_me"]
    assert (tool.method, tool.path) == ("GET", "/approvals/inbox")
    assert not tool.is_write
    assert PAGES["waiting_for_you"][0] == "/site/approvals"


async def test_what_is_waiting_only_reads() -> None:
    turn, read = await _turn([[("waiting_for_me", {})],
                              "1 waiting: Sreedhar team RA-3, Tower A: billed 220 sqm more than measured, ₹50,600 at risk."],
                             "enthokke approve cheyyanam?")
    assert read == [(None, None)] and turn.pending == []


def test_the_sop_routes_decisions_to_each_modules_own_tool() -> None:
    sop = (Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8")
    assert "call `waiting_for_me`" in sop
    for tool in ("decide_material_request", "approve_subcontract_bill", "answer_size_request"):
        assert f"`{tool}`" in sop
    # Guards: what cannot be decided in chat is never said done; "my requests" stays the material_requests rule.
    assert "never that it was done" in sop
    assert "a bare \"my requests\" / \"ente requests\" is BOTH lists" in sop
