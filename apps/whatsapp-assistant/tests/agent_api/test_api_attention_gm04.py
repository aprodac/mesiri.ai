"""GM-04 (9 Nov 2026): "anything I should know?" on WhatsApp through the dashboard's own attention route.

It only reads `attention` (never prepares a save). Guards: a question about one thing keeps its own rule (cost,
schedule, what to order, what waits for a decision), and no rupee is added to an answer that has none.
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

    @app.get("/attention")
    async def attention(project_id: str | None = None, jwt: dict = Depends(get_current_user)):
        read.append(project_id)
        return {"date": "2026-11-09", "items": [
            {"key": "late:a2", "kind": "late", "severity": "bad", "title": "Slab 6F is 2 days late",
             "detail": "On the critical path: each day late moves the handover", "project_name": "Marina Heights",
             "site_name": "Tower A", "action": {"label": "Open the schedule", "link": "/planning/schedule"}}],
            "snoozed": [], "counts": {"total": 1, "bad": 1, "warn": 0, "snoozed": 0}}

    return app


async def _turn(script: list, text: str):  # noqa: ANN202
    read: list = []
    app = _app(read)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "attention"))
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text), read
    finally:
        await client.close()


def test_the_tool_is_the_dashboards_route_read_only_with_a_page() -> None:
    tool = _real_tools()["attention"]
    assert (tool.method, tool.path) == ("GET", "/attention")
    assert not tool.is_write
    assert PAGES["attention"][0] == "/site/attention"


async def test_anything_to_worry_about_only_reads() -> None:
    turn, read = await _turn([[("attention", {})], "1 to act on: Marina Heights, Tower A: Slab 6F is 2 days late."],
                             "inn enthaa sradhikkendath?")
    assert read == [None] and turn.pending == []


def test_the_sop_keeps_each_specific_question_on_its_own_rule() -> None:
    sop = (Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8")
    assert "call `attention`" in sop
    assert "cost is rule 20, the\n   schedule rule 15, what to order rule 16, what waits for their decision rule 22" in sop
    assert "never a rupee when the answer has none" in sop
