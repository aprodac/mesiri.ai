"""BOQ-01 (15 Nov 2026: "messages and everything get connected to the BOQ and the schedule?"): a work update saved
on WhatsApp sat on no BOQ line until someone in the office linked it, so the BOQ's "done" and the Gantt stayed at 0%.

Now the API puts the work on its BOQ line by itself when the line is clear, and the "Saved" reply says so; when no
line is clear it asks "which BOQ line?" with the lines to tap, and one tap puts it there (no model turn).
Journey: the words -> card -> Save -> the reply under "Saved" -> the tap -> what the API got.
Class: every saved work line (one or several); the guard: no BOQ says nothing, and a Save that left lines waiting
keeps its Save buttons (no list on top of them)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from tests.agent_api.standin import PROJECT, SITE, stand_in_api
from tests.agent_api.test_api_agent_124 import CTX, _message, _service

from agent_api import whatsapp as wa
from agent_api.tools import ALLOWED, CONFIRM_ARG
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

NAMES = {"record_work", "list_projects", "list_sites"}
ACTIVITY, QUANTITY = str(uuid.uuid4()), str(uuid.uuid4())
WALLS, CEILING = str(uuid.uuid4()), str(uuid.uuid4())


class _Q(BaseModel):
    quantity: float
    unit: str


class _Work(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID
    activity_date: dt.date
    work_type: str | None = None
    narrative: str | None = None
    quantities: list[_Q] = []
    source: str = "dashboard"


class _Line(BaseModel):
    line_id: uuid.UUID | None = None


@pytest.fixture(autouse=True)
def _tools(monkeypatch):
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda o: real(o, tuple(a for a in ALLOWED if a.name in NAMES)))


def _app(boq: list[dict], put: list) -> FastAPI:
    app = stand_in_api([])

    @app.post("/progress/activities", status_code=201)
    async def work(body: _Work, jwt: dict = Depends(get_current_user)):
        return {"status": "created", "id": ACTIVITY, **({"boq": boq} if boq else {})}

    @app.put("/progress/activities/{activity_id}/quantities/{quantity_id}/boq-line")
    async def line(activity_id: str, quantity_id: str, body: _Line, jwt: dict = Depends(get_current_user)):
        if body.line_id is None:
            put.append((activity_id, quantity_id, None))
            return {"quantity_id": quantity_id, "line": None}
        if str(body.line_id) not in (WALLS, CEILING):
            raise HTTPException(422, "That BOQ line is not in this project.")
        put.append((activity_id, quantity_id, str(body.line_id)))
        return {"quantity_id": quantity_id, "line": {"id": str(body.line_id),
                                                     "work": "Plastering walls" if str(body.line_id) == WALLS
                                                     else "Plastering ceiling"}}

    return app


WORK = ("record_work", {"project_id": PROJECT, "site_id": SITE, "work_type": "plastering",
                        "quantities": [{"quantity": 400, "unit": "sqft"}],
                        CONFIRM_ARG: "400 sqft plastering at Green Villa"})


async def _saved(boq: list[dict], put: list):
    service, sent = _service(FakeToolCallingProvider([[WORK], "OK."]), app=_app(boq, put))
    await service.handle(_message("400 sqft plastering done, Green Villa"), CTX)
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    return service, sent


async def test_the_clear_line_is_said_under_saved() -> None:
    _, sent = await _saved([{"quantity_id": QUANTITY, "work": "plastering", "auto": True, "choices": [],
                             "line": {"id": WALLS, "work": "Plastering walls"}}], [])
    assert "📐 On the BOQ: Plastering walls" in sent[-1].text
    assert not sent[-1].list_rows  # nothing to ask


async def test_no_clear_line_asks_with_the_lines_and_one_tap_puts_it_there() -> None:
    put: list = []
    service, sent = await _saved([{"quantity_id": QUANTITY, "work": "plastering", "auto": False, "line": None,
                                   "choices": [{"id": WALLS, "work": "Plastering walls"},
                                               {"id": CEILING, "work": "Plastering ceiling"}]}], put)
    reply = sent[-1]
    assert reply.text.startswith("Saved.") and "Which BOQ line is *plastering* on?" in reply.text
    assert [r.title for r in reply.list_rows] == ["Plastering walls", "Plastering ceiling", wa.BOQ_SKIP_TITLE]
    assert reply.list_button_label == wa.BOQ_LIST_BUTTON
    await service.handle(_message("Plastering ceiling", tap=reply.list_rows[1].id), CTX)
    assert put == [(ACTIVITY, QUANTITY, CEILING)]
    assert sent[-1].text == "✅ Put on the BOQ line *Plastering ceiling*."


async def test_a_refused_tap_says_why_in_plain_words() -> None:
    service, sent = await _saved([], [])
    await service.handle(_message("x", tap=f"{wa.BOQ_PREFIX}{ACTIVITY}:{QUANTITY}:{uuid.uuid4()}"), CTX)
    assert "not in this project" in sent[-1].text


async def test_guard_no_boq_says_nothing_about_it() -> None:
    _, sent = await _saved([], [])
    assert "BOQ" not in sent[-1].text and not sent[-1].list_rows


def test_one_question_at_a_time_and_lines_put_by_themselves_are_said_once() -> None:
    from agent_api.agent import PendingWrite, WriteResult

    e = PendingWrite("record_work", "POST", "/progress/activities", {}, {"work_type": "brickwork"}, "x", "k")
    ask = {"quantity_id": "q", "work": "brickwork", "auto": False, "line": None,
           "choices": [{"id": "l1", "work": "Brickwork 9 inch"}, {"id": "l2", "work": "Brickwork 4.5 inch"}]}
    auto = {"quantity_id": "q2", "work": "brickwork", "auto": True, "choices": [],
            "line": {"id": "l1", "work": "Brickwork 9 inch"}}
    on, question, rows, label, queue = wa.boq_follow_up(
        [WriteResult(e, 201, {"id": "a", "boq": [ask, ask, auto, auto]})], None)
    assert on == "📐 On the BOQ: Brickwork 9 inch"
    assert question.count("Which") == 1 and "(1 more after this)" in question and label == wa.BOQ_LIST_BUTTON
    assert [r.title for r in rows] == ["Brickwork 9 inch", "Brickwork 4.5 inch", wa.BOQ_SKIP_TITLE]
    assert len(queue) == 1  # BOQ-01d: the second is asked after the first is answered
    assert wa.boq_follow_up([WriteResult(e, 422, {"detail": "no"})], None) == ("", "", (), wa.BOQ_LIST_BUTTON, [])


# -- BOQ-01b: a wrong guess is put right in one tap; a line it would overrun is asked ---------------------------------


async def test_a_line_put_by_itself_can_be_changed_or_taken_off_in_one_tap() -> None:
    put: list = []
    service, sent = await _saved([{"quantity_id": QUANTITY, "work": "plastering", "auto": True,
                                   "line": {"id": WALLS, "work": "Plastering walls"},
                                   "choices": [{"id": CEILING, "work": "Plastering ceiling"}]}], put)
    reply = sent[-1]
    assert "📐 On the BOQ: Plastering walls" in reply.text and "Wrong line? Change it below." in reply.text
    assert reply.list_button_label == wa.BOQ_CHANGE_BUTTON
    assert [r.title for r in reply.list_rows] == ["Plastering ceiling", wa.BOQ_NONE_TITLE]
    await service.handle(_message("Not on the BOQ", tap=reply.list_rows[1].id), CTX)
    assert put == [(ACTIVITY, QUANTITY, None)] and sent[-1].text == wa.BOQ_OFF


async def test_a_quantity_past_the_plan_says_why_it_is_asked() -> None:
    _, sent = await _saved([{"quantity_id": QUANTITY, "work": "ceiling plastering", "auto": False, "line": None,
                             "over": {"line": {"id": CEILING, "work": "Plastering ceiling"}, "done": "0",
                                      "planned": "300", "after": "400.000", "unit": "sqft"},
                             "choices": [{"id": CEILING, "work": "Plastering ceiling"}]}], [])
    assert "would take *Plastering ceiling* to 400 of 300 sqft" in sent[-1].text
    assert [r.title for r in sent[-1].list_rows] == ["Plastering ceiling", wa.BOQ_SKIP_TITLE]


async def test_guard_a_line_with_nothing_else_it_could_be_asks_nothing() -> None:
    _, sent = await _saved([{"quantity_id": QUANTITY, "work": "plastering", "auto": True, "choices": [],
                             "line": {"id": WALLS, "work": "Plastering walls"}}], [])
    assert "Wrong line" not in sent[-1].text and not sent[-1].list_rows


# -- BOQ-01d: several unclear quantities in one message are each asked, one after another ---------------------------


async def test_every_unclear_quantity_is_asked_in_turn_and_skip_moves_on() -> None:
    put: list = []
    second = str(uuid.uuid4())
    service, sent = await _saved([
        {"quantity_id": QUANTITY, "work": "plastering", "auto": False, "line": None,
         "choices": [{"id": WALLS, "work": "Plastering walls"}, {"id": CEILING, "work": "Plastering ceiling"}]},
        {"quantity_id": second, "work": "more plastering", "auto": False, "line": None,
         "choices": [{"id": WALLS, "work": "Plastering walls"}, {"id": CEILING, "work": "Plastering ceiling"}]},
    ], put)
    assert "*plastering*" in sent[-1].text and "(1 more after this)" in sent[-1].text
    await service.handle(_message("Plastering walls", tap=sent[-1].list_rows[0].id), CTX)
    assert put == [(ACTIVITY, QUANTITY, WALLS)]
    assert sent[-1].text.startswith("✅ Put on the BOQ line *Plastering walls*.") and "*more plastering*" in sent[-1].text
    await service.handle(_message("Skip", tap=sent[-1].list_rows[-1].id), CTX)
    assert len(put) == 1 and sent[-1].text == wa.BOQ_SKIPPED and not sent[-1].list_rows  # nothing left to ask
