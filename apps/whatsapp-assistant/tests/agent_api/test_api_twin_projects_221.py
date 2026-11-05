"""[221] part 3 (Ilan, 3 Nov 23:48: "Rana Mart already exists ✅ (3 of them: please tidy them up on the dashboard)"):
a dead end, though update_project is one of Mesiri's tools. Now the code lists the copies with their sites and records
(the timeline's total) and holds archiving the empty ones on the Save card; nothing is ever deleted. When more than one
copy has records it asks which to keep, and the model is given the copies' ids by number.

Guards: one existing project still says only "already exists ✅"; a copy whose records can't be read is never archived;
a new name is prepared as today ([219]).
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR

from agent_api.agent import ApiAgent, Places
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri_ai.fakes import FakeToolCallingProvider

R1, R2, R3, SITE1, SITE2 = (str(uuid.uuid4()) for _ in range(5))
PLACES = Places(projects=((R1, "Rana Mart"), (R2, "Rana Mart"), (R3, "rana mart")),
                sites=((SITE1, "Main", R1), (SITE2, "Annex", R1)))


class _ProjectIn(BaseModel):
    name: str


def _api(records: dict[str, int | None]) -> FastAPI:
    app = FastAPI()

    @app.post("/projects", status_code=201)
    async def create(body: _ProjectIn):  # noqa: ANN202
        return {"id": str(uuid.uuid4()), "name": body.name}

    @app.get("/timeline")
    async def timeline(project_id: str, limit: int = 50):  # noqa: ANN202
        total = records.get(project_id)
        if total is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=500, detail="down")
        return {"items": [], "total": total}

    return app


async def _create(records: dict[str, int | None], language: str | None = None, places: Places = PLACES):  # noqa: ANN202
    app = _api(records)
    client = ApiClient(ACTOR, app=app)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "create_project"))
    model = FakeToolCallingProvider([[("create_project", {"name": "Rana Mart", CONFIRM_ARG: "New project Rana Mart"})],
                                     ""])
    try:
        turn = await ApiAgent(model, tools).run(client, "try again", places=places, language=language)
    finally:
        await client.close()
    return turn, model


async def test_the_copies_are_listed_and_the_empty_ones_held_for_archiving() -> None:
    turn, _ = await _create({R1: 14, R2: 0, R3: 0})
    assert "You have 3 projects with this name:" in turn.reply
    assert "1. Rana Mart · 2 sites · 14 records" in turn.reply and "3. rana mart · 0 sites · 0 records" in turn.reply
    assert "dashboard" not in turn.reply and "nothing is deleted" in turn.reply
    assert [(e.tool, e.path, e.body) for e in turn.pending] == [
        ("update_project", f"/projects/{R2}", {"status": "archived"}),
        ("update_project", f"/projects/{R3}", {"status": "archived"})]
    assert turn.pending[0].summary == "🗂️ Archive copy 2 of *Rana Mart* (no records)"


async def test_in_manglish() -> None:
    turn, _ = await _create({R1: 14, R2: 0, R3: 0}, "manglish")
    assert turn.reply.startswith("Rana Mart ippo thanne undu ✅ Ee peril 3 project undu:")
    assert "onnum delete aakilla" in turn.reply


async def test_more_than_one_with_records_asks_which_to_keep_and_holds_nothing() -> None:
    turn, _ = await _create({R1: 14, R2: 3, R3: 0})
    assert turn.pending == [] and "which number to keep" in turn.reply
    told = turn.calls[0]["result"]["status"]
    assert f"1. project_id {R1}" in told and f"3. project_id {R3}" in told  # the model knows which number is which


async def test_guard_a_copy_whose_records_cant_be_read_is_never_archived() -> None:
    turn, _ = await _create({R1: 14, R2: None, R3: 0})
    assert turn.pending == [] and "· — records" in turn.reply


async def test_guard_one_existing_project_is_only_said() -> None:
    turn, _ = await _create({R1: 14}, places=Places(projects=((R1, "Rana Mart"),), sites=()))
    assert turn.reply == "Rana Mart already exists ✅" and turn.pending == []
