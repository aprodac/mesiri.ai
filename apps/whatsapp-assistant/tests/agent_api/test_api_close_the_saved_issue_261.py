"""WA-261 (Ilan's chat, Aprodac, 8 Nov 02:03-02:04): "Water tank leak" was saved; then "the water tank leakage has been
fixed ... save it that it has been solved" was prepared with an id that was no issue, and Save said "Issue not found".

Now (1) the records saved in this chat are listed for the model with their ids, and (2) an id in a write's path is
checked against that collection's own list when it is prepared, so a wrong one is looked up in the same turn, never
discovered by the person at Save.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR, SITE

from agent_api.agent import ApiAgent, PendingWrite, WriteResult, remember_saves, saved_records_note
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

LEAK = {"id": str(uuid.uuid4()), "issue_type": "EQUIPMENT", "narrative": "Water tank leak", "status": "OPEN"}
MESSAGE = "The water tank leakage has been fixed, save it that it has been solved."


class Resolve(BaseModel):
    resolution_notes: str | None = None


def _api() -> FastAPI:
    app = FastAPI()

    @app.get("/progress/issues")
    async def list_issues(site_id: str | None = None, status: str | None = None,
                          jwt: dict = Depends(get_current_user)):
        return {"items": [LEAK], "total": 1}

    @app.post("/progress/issues/{issue_id}/resolve")
    async def resolve(issue_id: uuid.UUID, body: Resolve, jwt: dict = Depends(get_current_user)):
        return {"id": issue_id, "status": "RESOLVED"}

    return app


async def _turn(script: list):  # noqa: ANN202
    app = _api()
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in ("list_issues", "resolve_issue")))
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, MESSAGE)
    finally:
        await client.close()


async def test_the_reported_wrong_id_is_refused_when_prepared_not_at_save() -> None:
    turn = await _turn([[("resolve_issue", {"issue_id": SITE, CONFIRM_ARG: "Water tank leak fixed"})], "Sheri."])
    assert turn.pending == []
    error = turn.calls[0]["result"]["error"]
    assert "is not one of these records" in error and "list_issues" in error


async def test_sibling_the_right_id_is_held_for_save() -> None:
    turn = await _turn([[("resolve_issue", {"issue_id": LEAK["id"], CONFIRM_ARG: "Water tank leak fixed"})], "Sheri."])
    (entry,) = turn.pending
    assert entry.path == f"/progress/issues/{LEAK['id']}/resolve"


def test_the_saved_issue_is_listed_for_the_model_with_its_id() -> None:
    saved = WriteResult(PendingWrite(tool="report_issue", method="POST", path="/progress/issues", params={},
                                     body={"site_id": SITE, "issue_type": "EQUIPMENT", "severity": "MEDIUM",
                                           "narrative": "Water tank leak"},
                                     summary="Water tank leak Main block-il", idempotency_key="i1"),
                        201, {"id": LEAK["id"]})
    note = saved_records_note(remember_saves([], [saved], 1000.0))
    assert f"report_issue: Water tank leak Main block-il (id {LEAK['id']})" in note


def test_guard_nothing_saved_no_note() -> None:
    assert saved_records_note([]) == ""
