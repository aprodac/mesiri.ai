"""LP-02 / LP-04 (8 Nov 2026): floors and rooms on WhatsApp through the dashboard's own routes.

"What's left on the first floor?" only reads `place_progress`, never prepares a save; work said at a place is
`record_work` with `place` (and `finished` when said), held for Save like any work. Guard: work with no place said
carries no place.
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

    @app.get("/projects/{project_id}/places/progress")
    async def place_progress(project_id: str, place: str | None = None, jwt: dict = Depends(get_current_user)):
        read.append((project_id, place))
        return {"place": "First Floor", "kinds": [{"key": "plastering", "name": "Plastering"}], "set_up": True,
                "places": [{"label": "First Floor", "left": ["Brickwork"], "done": ["Plastering"]}]}

    return app


async def _turn(script: list, text: str):  # noqa: ANN202
    read: list = []
    app = _app(read)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "place_progress"))
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text), read
    finally:
        await client.close()


def test_place_progress_is_the_dashboards_route_and_read_only() -> None:
    tool = _real_tools()["place_progress"]
    assert (tool.method, tool.path) == ("GET", "/projects/{project_id}/places/progress")
    assert not tool.is_write and "place" in tool.query_params
    assert PAGES["places"][0] == "/planning/places?project={project_id}"


def test_record_work_takes_a_place_and_finished() -> None:
    tool = _real_tools()["record_work"]
    assert tool.is_write
    assert {"place", "finished"} <= set(tool.body_fields)
    assert "place_id" in tool.body_fields  # the dashboard's picker; the model uses words


async def test_whats_left_on_the_first_floor_only_reads() -> None:
    turn, read = await _turn([[("place_progress", {"project_id": PROJECT, "place": "first floor"})],
                              "First Floor: plastering done. Left: brickwork."],
                             "first floor il enthokke baaki?")
    assert read == [(PROJECT, "first floor")] and turn.pending == []


def test_the_sop_rule_for_places() -> None:
    sop = (Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8")
    sop = " ".join(sop.split())
    assert "17. Floors and rooms." in sop
    assert "`finished` true only when they said that work is finished there" in sop
    # Guards: never ask a place for labour / material / expense, never guess between places.
    assert "never ask for a place for labour, material or an expense" in sop
    assert "never guess one" in sop
