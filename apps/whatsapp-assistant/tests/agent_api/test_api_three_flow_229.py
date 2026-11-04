"""[229] (4 Nov, Paraclette, voice note: cement + masons + slab): the reply said "ready, press Save" and nothing was held.
Journey: voice words -> three lines held with one Save -> Save tap -> what the API got.
Class: labour / work / receipt with no date; a question for one line; prose that claims Save with nothing held."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.standin import BAG, CEMENT, PROJECT, SITE, stand_in_api
from tests.agent_api.test_api_agent_124 import CTX, _message, _service

from agent_api import whatsapp as wa
from agent_api.tools import ALLOWED, CONFIRM_ARG
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

TODAY = dt.datetime.now(dt.UTC).astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).date().isoformat()
NAMES = {"record_receipt", "record_attendance", "record_work", "list_projects", "list_sites",
         "search_materials", "list_units"}


class _Att(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID
    occurred_date: dt.date
    lines: list[dict]
    recorded_via: str = "dashboard"


class _Work(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID
    occurred_date: dt.date
    description: str
    source: str = "web"


@pytest.fixture(autouse=True)
def _tools(monkeypatch):
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda o: real(o, tuple(a for a in ALLOWED if a.name in NAMES)))


def _app(posted: list) -> FastAPI:
    app = stand_in_api([])

    @app.post("/labour/attendance", status_code=201)
    async def att(body: _Att, jwt: dict = Depends(get_current_user)):
        posted.append(("attendance", body.model_dump()))
        return {"id": str(uuid.uuid4())}

    @app.post("/progress/activities", status_code=201)
    async def work(body: _Work, jwt: dict = Depends(get_current_user)):
        posted.append(("work", body.model_dump()))
        return {"id": str(uuid.uuid4())}

    return app


BASE = {"project_id": PROJECT, "site_id": SITE}
CEMENT_CALL = ("record_receipt", {**BASE, "material_id": CEMENT, "unit_id": BAG, "quantity": 20,
                                  "occurred_date": "2026-11-04", CONFIRM_ARG: "20 bag Cement received at Tower A"})
LABOUR = ("record_attendance", {**BASE, "lines": [{"trade": "mason", "headcount": 20}],
                                CONFIRM_ARG: "20 masons at Tower A"})
WORK = ("record_work", {**BASE, "description": "Slab work done", CONFIRM_ARG: "Slab work done at Tower A"})


async def test_three_updates_in_one_voice_note_are_held_with_one_save_and_saved_together() -> None:
    posted: list = []
    model = FakeToolCallingProvider([[CEMENT_CALL, LABOUR, WORK], "Ready. Press Save to record."])
    service, sent = _service(model, app=_app(posted))
    await service.handle(_message("20 bag cement vannu, 20 mason pani eduthu, slab pani kazhinju"), CTX)
    reply = sent[-1]
    assert reply.text.count("\n1. ") == 1 and "\n3. " in reply.text  # three lines held
    assert [b.title for b in reply.buttons] == ["Save", "Cancel"]
    assert reply.text.lower().count("save") == 2  # "Ready to save:" and the code's own line; the model's was cut
    assert "Press Save" not in reply.text
    await service.handle(_message("Save", tap=reply.buttons[0].id), CTX)
    kinds = sorted(k for k, _ in posted)
    assert kinds == ["attendance", "work"]
    by = dict(posted)
    assert by["attendance"]["occurred_date"].isoformat() == TODAY and by["work"]["occurred_date"].isoformat() == TODAY  # no date question
    assert by["attendance"]["lines"][0]["headcount"] == 20


async def test_a_date_said_is_kept() -> None:
    posted: list = []
    said = ("record_attendance", {**LABOUR[1], "occurred_date": "2026-11-03"})
    model = FakeToolCallingProvider([[said], "Ready."])
    service, sent = _service(model, app=_app(posted))
    await service.handle(_message("innale 20 mason undarunnu"), CTX)
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    assert posted[0][1]["occurred_date"] == dt.date(2026, 11, 3)


async def test_one_line_with_a_question_keeps_the_others_held_with_save() -> None:
    model = FakeToolCallingProvider([[CEMENT_CALL, WORK, ("ask", {"question": "Which trade?", "options": ["Mason", "Helper"]})],
                                     "Two lines are ready; which trade for the third?"])
    service, sent = _service(model, app=_app([]))
    await service.handle(_message("cement vannu, slab kazhinju, 5 pani"), CTX)
    reply = sent[-1]
    assert "1. " in reply.text and "2. " in reply.text
    assert [b.title for b in reply.buttons] == ["Mason", "Helper", "Save"]


async def test_prose_that_says_press_save_with_nothing_held_is_replaced_by_the_truth() -> None:
    model = FakeToolCallingProvider(["20 bag cement ready-aanu. Save button amarthuka.",
                                     "20 bag cement ready-aanu. Save button amarthuka."])
    service, sent = _service(model, app=_app([]))
    await service.handle(_message("20 bag cement vannu"), CTX)
    reply = sent[-1]
    assert not reply.buttons and "amarthuka" not in reply.text
    assert "ready aayittilla" in reply.text
