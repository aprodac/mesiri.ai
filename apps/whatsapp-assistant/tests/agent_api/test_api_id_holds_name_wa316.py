"""WA-316 (20 Nov, recording episode 3, the local copy on production's model): Anil, a project manager, typed
"Annex: Manoj, Satheesh, Vinod present. Rahim crew 4 helpers" into New. The card was right ("3 workers present, Rahim
crew 4 helpers, Annex"); Save said "Not everything could be saved" (Ravi's same words saved). The trace: each named
line was held with ``worker_id: "Manoj"`` (the name in the id field) and the API refused the whole report, 422 "Input
should be a valid UUID".
Journey: the words -> card -> Save -> what the API got.
Class: a name the model puts in an id field, in any write's body or its lines, where the row has the name's own field
(worker_id / worker_name): the code moves it there, read from the tool's own schema; then a named person is the
register's (GET /labour/workers), so the line keeps the worker's trade and wage. Guards: a real id is never
touched; a name with no name field beside it is left for the look-up checks (PRC-32, WA-261)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel
from tests.agent_api.standin import PROJECT, SITE, stand_in_api
from tests.agent_api.test_api_agent_124 import CTX, _message, _service

from agent_api import whatsapp as wa
from agent_api.fill import names_for_ids
from agent_api.tools import ALLOWED, CONFIRM_ARG
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

NAMES = {"record_attendance", "list_projects", "list_sites"}
MANOJ = str(uuid.uuid4())


class _Line(BaseModel):  # as the API's RecordAttendanceLine (domains/workforce/router.py), unchanged
    worker_name: str | None = None
    worker_id: uuid.UUID | None = None
    trade: str | None = None
    daily_wage: float | None = None
    headcount: int = 1
    contractor: str | None = None
    attendance_status: str = "present"


class _Att(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID
    occurred_date: dt.date
    lines: list[_Line]
    recorded_via: str = "dashboard"


@pytest.fixture(autouse=True)
def _tools(monkeypatch):
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda o: real(o, tuple(a for a in ALLOWED if a.name in NAMES)))


SATHEESH = str(uuid.uuid4())
REGISTER = [{"id": MANOJ, "name": "Manoj", "status": "active", "trade": "mason", "default_daily_wage": 1050},
            {"id": SATHEESH, "name": "Satheesh", "status": "active", "trade": "plumber", "default_daily_wage": 1150},
            {"id": str(uuid.uuid4()), "name": "Biju", "status": "active"}, {"id": str(uuid.uuid4()), "name": "Biju", "status": "active"}]


def _app(posted: list) -> FastAPI:
    app = stand_in_api([])

    @app.get("/labour/workers")
    async def workers(limit: int = Query(default=50, ge=1, le=200), offset: int = 0,  # as the API's own route
                      jwt: dict = Depends(get_current_user)):
        return {"items": REGISTER[offset:offset + limit], "total": len(REGISTER)}

    @app.post("/labour/attendance", status_code=201)
    async def att(body: _Att, jwt: dict = Depends(get_current_user)):
        posted.append(body.model_dump(mode="json"))
        return {"id": str(uuid.uuid4())}

    return app


WORDS = "Annex: Manoj, Satheesh, Vinod present. Rahim crew 4 helpers"
HELD = ("record_attendance", {"project_id": PROJECT, "site_id": SITE, "lines": [
    {"worker_id": "Satheesh", "worker_name": "Satheesh", "trade": "Site Engineer", "attendance_status": "present"},
    {"worker_id": "Vinod", "attendance_status": "present"},
    {"worker_id": MANOJ, "worker_name": "Manoj", "attendance_status": "present"},
    {"worker_name": "Biju", "attendance_status": "present"},
    {"trade": "helper", "headcount": 4, "contractor": "Rahim"}],
    CONFIRM_ARG: "3 workers present, Rahim crew 4 helpers, Annex"})


async def test_the_reported_message_saves_with_the_names_as_names() -> None:
    posted: list = []
    service, sent = _service(FakeToolCallingProvider([[HELD], "OK."]), app=_app(posted))
    await service.handle(_message(WORDS), CTX)
    card = sent[-1]
    await service.handle(_message("Save", tap=card.buttons[0].id), CTX)
    assert "❌" not in sent[-1].text, sent[-1].text
    lines = posted[0]["lines"]
    # The register's person when the name is one person's; a name that is no one's or two people's stays a name; a
    # real id is never changed.
    assert [(x["worker_name"], x["worker_id"]) for x in lines[:4]] == [
        ("Satheesh", SATHEESH), ("Vinod", None), ("Manoj", MANOJ), ("Biju", None)]
    assert lines[4]["headcount"] == 4 and lines[4]["contractor"] == "Rahim"
    # The register's trade and wage, not a trade nobody said ("Site Engineer"): the day has its labour cost.
    assert (lines[0]["trade"], lines[0]["daily_wage"]) == ("plumber", 1150)
    assert (lines[2]["trade"], lines[2]["daily_wage"]) == ("mason", 1050)


async def test_guard_a_trade_the_person_said_is_kept() -> None:
    from agent_api.agent import register_ids
    from agent_api.client import ApiClient

    client = ApiClient(__import__("agent_api.whatsapp", fromlist=["_actor"])._actor(CTX), app=_app([]))
    try:
        body = {"lines": [{"worker_name": "Manoj", "trade": "helper"}]}
        out = await register_ids(client, body, "Manoj worked as helper today")
        unsaid = await register_ids(client, body, "Manoj present")
    finally:
        await client.close()
    assert (out["lines"][0]["worker_id"], out["lines"][0]["trade"]) == (MANOJ, "helper")
    assert unsaid["lines"][0]["trade"] == "mason"


SCHEMA = {"properties": {
    "site_id": {"type": "string", "format": "uuid"},
    "vendor_id": {"anyOf": [{"type": "string", "format": "uuid"}, {"type": "null"}]},
    "vendor_name": {"type": "string"},
    "lines": {"type": "array", "items": {"type": "object", "properties": {
        "worker_id": {"anyOf": [{"type": "string", "format": "uuid"}, {"type": "null"}]},
        "worker_name": {"type": "string"}, "trade": {"type": "string"}}}}}}


def test_sibling_a_top_level_id_with_a_name_field_beside_it() -> None:
    assert names_for_ids(SCHEMA, {"vendor_id": "Kerala Steels"}) == {"vendor_name": "Kerala Steels"}


def test_guard_ids_and_names_already_given_are_kept() -> None:
    real = {"vendor_id": MANOJ, "lines": [{"worker_id": MANOJ, "worker_name": "Manoj"}]}
    assert names_for_ids(SCHEMA, real) == real
    said = {"lines": [{"worker_id": "Manu", "worker_name": "Manoj"}]}
    assert names_for_ids(SCHEMA, said) == {"lines": [{"worker_name": "Manoj"}]}  # their own spelling wins


def test_guard_an_id_with_no_name_field_is_left_for_the_look_up() -> None:
    body = {"site_id": "Annex"}
    assert names_for_ids(SCHEMA, body) == body
