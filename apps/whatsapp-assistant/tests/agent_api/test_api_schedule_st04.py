"""ST-04 (8 Nov 2026): the project schedule on WhatsApp through the dashboard's own routes.

"What is planned this week?" / "what is late?" only reads `schedule`. "Slab postponed to the 20th" is one
`update_schedule_activity` held for Save. Guards: reporting work never moves the schedule; the SOP no longer says
Mesiri has no plan to compare with.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.replaykit import _real_tools
from tests.agent_api.standin import ACTOR

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.receipts import kind_of
from agent_api.record_links import RECORD_PAGES
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

PROJECT = str(uuid.uuid4())
SLAB = str(uuid.uuid4())


class Move(BaseModel):
    start: str | None = None
    end: str | None = None
    done: bool | None = None
    preview: bool = False
    push: bool = True


def _app(read: list, saved: list) -> FastAPI:
    app = FastAPI()

    @app.get("/projects/{project_id}/schedule")
    async def schedule(project_id: str, jwt: dict = Depends(get_current_user)):
        read.append(project_id)
        return {"activities": [{"id": SLAB, "name": "Slab", "start": "2026-11-12", "end": "2026-11-14",
                                "state": "behind", "progress": 40}],
                "summary": {"scheduled": 1, "forecast_finish": "2026-11-16", "slip_days": 2}}

    @app.patch("/projects/{project_id}/schedule/activities/{activity_id}")
    async def move(project_id: str, activity_id: str, body: Move, jwt: dict = Depends(get_current_user)):
        saved.append((activity_id, body))
        return {"saved": True, "moved": []}

    return app


async def _turn(script: list, text: str):  # noqa: ANN202
    read: list = []
    saved: list = []
    app = _app(read, saved)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in ("schedule", "update_schedule_activity")))
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text), read, saved
    finally:
        await client.close()


def test_the_schedule_tools_are_the_dashboards_routes() -> None:
    tools = _real_tools()
    assert (tools["schedule"].method, tools["schedule"].path) == ("GET", "/projects/{project_id}/schedule")
    move = tools["update_schedule_activity"]
    assert (move.method, move.path) == ("PATCH", "/projects/{project_id}/schedule/activities/{activity_id}")
    assert move.is_write and not tools["schedule"].is_write
    assert {"start", "end", "done"} <= set(move.body_fields)
    assert not {"preview", "push", "clear_dates"} & set(move.body_fields)
    assert RECORD_PAGES["update_schedule_activity"] == "schedule" and kind_of("update_schedule_activity") == "schedule"


async def test_whats_planned_this_week_only_reads() -> None:
    turn, read, saved = await _turn([[("schedule", {"project_id": PROJECT})],
                                     "This week: Slab Thu 12 - Sat 14 Nov (40%, behind)."],
                                    "ee aazhcha enthaa cheyyendath?")
    assert read == [PROJECT] and turn.pending == [] and saved == []


async def test_slab_postponed_is_one_move_held_for_save() -> None:
    move = ("update_schedule_activity", {"project_id": PROJECT, "activity_id": SLAB, "start": "2026-11-20",
                                         "end": "2026-11-22", CONFIRM_ARG: "Slab moved to 20-22 Nov"})
    turn, _, saved = await _turn([[move], "Ready."], "slab 20th-ilekk maatti")
    assert saved == []  # held until Save
    assert [(p.tool, p.method) for p in turn.pending] == [("update_schedule_activity", "PATCH")]
    assert turn.pending[0].body["start"] == "2026-11-20"


def test_the_sop_reads_the_schedule_and_never_moves_it_for_work_done() -> None:
    sop = (Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8")
    assert "Mesiri has no plan to compare with" not in sop
    assert "call `schedule` for the project" in sop
    assert "never change a schedule's dates because work was reported" in sop
