"""NXT-11 (WA-68): machines on WhatsApp through the dashboard's own routes (/equipment).

"JCB 6 hrs, 2 hrs breakdown, 30 L diesel" is one `log_machines` line held for Save (the machine in their words, the
breakdown hours raise the issue in the API, never a second `report_issue`). "Where is the JCB" only reads.
Guards: work done with a machine stays work; `source` is the code's, never the model's; until v3 had these tools a
machine's hours had nowhere to go (request 104 A1 answered "✅ Saved" with nothing behind it).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.replaykit import _real_tools
from tests.agent_api.standin import ACTOR, SITE

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.receipts import kind_of
from agent_api.record_links import RECORD_PAGES
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

NAMES = ("machines", "machine_logs", "log_machines", "add_machine", "move_machine", "off_hire_machine", "hire_check")
WRITES = ("log_machines", "add_machine", "move_machine", "off_hire_machine")


class Line(BaseModel):
    machine: str | None = None
    equipment_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    worked_hours: Decimal | None = None
    idle_hours: Decimal | None = None
    breakdown_hours: Decimal | None = None
    breakdown_reason: str | None = None
    fuel_litres: Decimal | None = None


class Logs(BaseModel):
    occurred_date: str | None = None
    lines: list[Line]
    source: str = "dashboard"


def _app(read: list, saved: list) -> FastAPI:
    app = FastAPI()

    @app.get("/equipment")
    async def machines(jwt: dict = Depends(get_current_user)):
        read.append("machines")
        return {"items": [{"name": "JCB", "ref": "EQ-0001", "site_name": "Green Villa", "state": "working"}]}

    @app.post("/equipment/logs", status_code=201)
    async def log(body: Logs, jwt: dict = Depends(get_current_user)):
        saved.append(body)
        return {"items": [], "replaced": [], "moved": [], "issues": []}

    return app


async def _turn(script: list, text: str):  # noqa: ANN202
    read: list = []
    saved: list = []
    app = _app(read, saved)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in ("machines", "log_machines")))
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text), read, saved
    finally:
        await client.close()


def test_the_machine_tools_are_the_dashboards_routes() -> None:
    tools = _real_tools()
    assert {n: (tools[n].method, tools[n].path) for n in NAMES} == {
        "machines": ("GET", "/equipment"),
        "machine_logs": ("GET", "/equipment/logs"),
        "log_machines": ("POST", "/equipment/logs"),
        "add_machine": ("POST", "/equipment"),
        "move_machine": ("POST", "/equipment/{machine_id}/move"),
        "off_hire_machine": ("POST", "/equipment/{machine_id}/off-hire"),
        "hire_check": ("GET", "/equipment/hire-check"),
    }
    log = tools["log_machines"]
    assert {"lines", "occurred_date"} <= set(log.body_fields) and "source" not in log.body_fields
    assert dict(log.fixed) == {"source": "whatsapp"}
    assert {"name", "ownership", "hire_company", "rate", "rate_unit", "site_id"} <= set(tools["add_machine"].body_fields)
    assert all(tools[n].is_write for n in WRITES) and not tools["machines"].is_write
    assert all(RECORD_PAGES[n] for n in WRITES) and {kind_of(n) for n in WRITES} == {"machine"}


async def test_jcb_six_hours_breakdown_and_diesel_is_one_line_held_for_save() -> None:
    line = ("log_machines", {"lines": [{"machine": "JCB", "site_id": SITE, "worked_hours": 6, "breakdown_hours": 2,
                                        "breakdown_reason": "Hydraulic leak", "fuel_litres": 30}],
                             CONFIRM_ARG: "JCB: 6 hrs, 2 hrs breakdown (hydraulic leak), 30 L diesel"})
    turn, _, saved = await _turn([[line], "Ready."], "JCB 6 hrs pani, 2 hrs breakdown hydraulic leak, 30 L diesel")
    assert saved == []  # held until Save
    assert [(p.tool, p.method, p.path) for p in turn.pending] == [("log_machines", "POST", "/equipment/logs")]
    body = turn.pending[0].body
    assert body["source"] == "whatsapp"
    assert (body["lines"][0]["machine"], body["lines"][0]["worked_hours"], body["lines"][0]["breakdown_hours"]) == ("JCB", 6, 2)


async def test_guard_where_is_the_jcb_only_reads() -> None:
    turn, read, saved = await _turn([[("machines", {})], "JCB is at Green Villa, working today."], "JCB evide aanu?")
    assert read == ["machines"] and turn.pending == [] and saved == []


def test_the_sop_keeps_a_machine_day_off_work_labour_and_issues() -> None:
    sop = (Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8")
    assert "ONE\n   `log_machines` line per machine" in sop
    assert "Never `record_work` or `record_attendance` for a machine's hours" in sop
    assert "never `report_issue` for its breakdown" in sop
    assert 'Work done WITH a machine ("20 cum slab with the\n   mixer") is still `record_work`' in sop
